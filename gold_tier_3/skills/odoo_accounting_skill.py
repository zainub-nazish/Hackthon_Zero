"""
OdooAccountingSkill — SKILL-008 (Rewrite: Direct XML-RPC, Odoo 19+)

Replaces the subprocess-based MCP approach with a pure Python xmlrpc.client
connection. Odoo 19+ continues to expose the same XML-RPC 2.0 endpoints; this
skill targets that API directly for maximum reliability in production.

Endpoints:
  /xmlrpc/2/common  → authenticate()
  /xmlrpc/2/object  → execute_kw() for all data operations

Authentication flow:
  uid = common.authenticate(db, username, password, {})
  Every subsequent call passes (db, uid, password) — uid is the session token.

Usage:
    skill = OdooAccountingSkill(vault_root)
    uid = skill.authenticate()                           # must call first
    summary = skill.get_weekly_sales_audit()            # returns dict
    invoice_id = skill.create_invoice(customer_name, lines, due_date)
"""

from __future__ import annotations

import logging
import os
import xmlrpc.client
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("OdooAccountingSkill")

# ---------------------------------------------------------------------------
# Defaults (overridden by .env)
# ---------------------------------------------------------------------------
_ODOO_URL      = os.environ.get("ODOO_URL",      "http://localhost:8069")
_ODOO_DB       = os.environ.get("ODOO_DB",       "odoo")
_ODOO_USER     = os.environ.get("ODOO_USER",     "admin")
_ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD", "admin")

_MAX_RETRIES = 3
_RETRY_WAIT  = 2  # seconds, doubles on each retry


# ---------------------------------------------------------------------------
# Typed result wrapper — keeps every return value consistent
# ---------------------------------------------------------------------------

class OdooResult:
    """Uniform return type for all OdooAccountingSkill methods."""

    def __init__(self, success: bool, data: Any = None, error: str = "") -> None:
        self.success = success
        self.data    = data
        self.error   = error

    def __repr__(self) -> str:
        if self.success:
            return f"OdooResult(ok, data={str(self.data)[:80]})"
        return f"OdooResult(FAIL, error={self.error[:80]})"


# ---------------------------------------------------------------------------
# OdooAccountingSkill
# ---------------------------------------------------------------------------

class OdooAccountingSkill:
    """
    SKILL-008 — Odoo 19+ accounting integration via XML-RPC.

    All methods return OdooResult(success, data, error) so callers never
    need to handle raw exceptions — every failure degrades gracefully.

    Audit trail:
      Every call writes a timestamped entry to Logs/odoo_skill.log.
      On error: full traceback captured; operation skipped, never raised.
    """

    def __init__(
        self,
        vault_root: Path,
        url:      str = _ODOO_URL,
        db:       str = _ODOO_DB,
        username: str = _ODOO_USER,
        password: str = _ODOO_PASSWORD,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.logs_dir   = self.vault_root / "Logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self._url      = url.rstrip("/")
        self._db       = db
        self._username = username
        self._password = password
        self._uid: int | None = None   # set by authenticate()

        # XML-RPC proxies (lazily connected)
        self._common: xmlrpc.client.ServerProxy | None = None
        self._models: xmlrpc.client.ServerProxy | None = None

        logger.info(
            "OdooAccountingSkill initialised | url=%s db=%s user=%s",
            self._url, self._db, self._username,
        )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> OdooResult:
        """
        Authenticate against Odoo and cache the uid.

        Returns:
            OdooResult(success=True, data=uid:int)
            OdooResult(success=False, error=<message>)

        Must be called before any data operation.
        Retries up to _MAX_RETRIES times on transient failures.
        """
        self._log("authenticate() — attempting login")

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self._common = xmlrpc.client.ServerProxy(
                    f"{self._url}/xmlrpc/2/common",
                    allow_none=True,
                )
                uid = self._common.authenticate(
                    self._db, self._username, self._password, {}
                )

                if not uid:
                    raise ValueError(
                        f"authenticate() returned falsy uid={uid!r}. "
                        "Check DB name, username, and password."
                    )

                self._uid = int(uid)
                self._models = xmlrpc.client.ServerProxy(
                    f"{self._url}/xmlrpc/2/object",
                    allow_none=True,
                )
                self._log(f"authenticate() — success | uid={self._uid}")
                logger.info("Odoo auth OK | uid=%d", self._uid)
                return OdooResult(success=True, data=self._uid)

            except xmlrpc.client.Fault as exc:
                msg = f"XML-RPC Fault: {exc.faultCode} — {exc.faultString}"
                self._log(f"authenticate() attempt {attempt} FAIL — {msg}")
                logger.error("Odoo auth Fault: %s", msg)
                return OdooResult(success=False, error=msg)  # no retry for auth faults

            except Exception as exc:
                wait = _RETRY_WAIT * (2 ** (attempt - 1))
                msg  = f"{type(exc).__name__}: {exc}"
                self._log(f"authenticate() attempt {attempt}/{_MAX_RETRIES} FAIL — {msg}")
                logger.warning("Odoo auth attempt %d failed: %s", attempt, msg)

                if attempt == _MAX_RETRIES:
                    return OdooResult(success=False, error=f"Auth failed after {_MAX_RETRIES} attempts. Last: {msg}")

                import time
                time.sleep(wait)

        return OdooResult(success=False, error="Auth failed (unreachable)")

    # ------------------------------------------------------------------
    # Weekly Sales Audit
    # ------------------------------------------------------------------

    def get_weekly_sales_audit(self) -> OdooResult:
        """
        Pull all posted customer invoices from the last 7 days.

        Odoo model: account.move
        Domain: move_type=out_invoice, invoice_date >= 7 days ago, state=posted

        Returns:
            OdooResult(success=True, data={
                "period":         "2026-05-02 → 2026-05-09",
                "total_invoices": int,
                "total_revenue":  float,   # sum of amount_total
                "currency":       str,
                "invoices":       [
                    {
                        "name":         str,  # invoice number (e.g. INV/2026/00012)
                        "partner":      str,  # customer name
                        "amount_total": float,
                        "invoice_date": str,
                        "state":        str,
                        "payment_state": str,
                    },
                    ...
                ],
                "overdue":        [...]     # same structure, overdue only
            })
        """
        self._require_auth()
        now      = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        today    = now.strftime("%Y-%m-%d")

        self._log(f"get_weekly_sales_audit() — period {week_ago} → {today}")

        domain = [
            ("move_type",    "=",  "out_invoice"),
            ("invoice_date", ">=", week_ago),
            ("state",        "=",  "posted"),
        ]
        fields = [
            "name", "partner_id", "amount_total", "amount_residual",
            "invoice_date", "invoice_date_due", "state", "payment_state",
            "currency_id",
        ]

        try:
            records = self._execute_kw(
                "account.move", "search_read",
                [domain],
                {"fields": fields, "order": "invoice_date desc", "limit": 200},
            )
        except Exception as exc:
            return self._handle_error("get_weekly_sales_audit", exc)

        invoices = []
        overdue  = []
        total    = 0.0
        currency = "USD"

        for rec in records:
            partner  = rec["partner_id"][1] if rec.get("partner_id") else "Unknown"
            currency = rec["currency_id"][1] if rec.get("currency_id") else "USD"
            amount   = float(rec.get("amount_total", 0))
            due_date = rec.get("invoice_date_due") or ""
            total   += amount

            entry = {
                "name":          rec.get("name", ""),
                "partner":       partner,
                "amount_total":  amount,
                "amount_due":    float(rec.get("amount_residual", 0)),
                "invoice_date":  str(rec.get("invoice_date", "")),
                "due_date":      str(due_date),
                "state":         rec.get("state", ""),
                "payment_state": rec.get("payment_state", ""),
            }
            invoices.append(entry)

            # Mark overdue: has residual amount AND due date in the past
            if due_date and due_date < today and entry["amount_due"] > 0:
                overdue.append(entry)

        result_data = {
            "period":         f"{week_ago} → {today}",
            "total_invoices": len(invoices),
            "total_revenue":  round(total, 2),
            "currency":       currency,
            "invoices":       invoices,
            "overdue":        overdue,
            "overdue_count":  len(overdue),
            "overdue_total":  round(sum(i["amount_due"] for i in overdue), 2),
        }

        self._log(
            f"get_weekly_sales_audit() — OK | invoices={len(invoices)} "
            f"revenue={total:.2f} overdue={len(overdue)}"
        )
        logger.info(
            "Weekly audit: %d invoice(s) | revenue=%.2f %s | overdue=%d",
            len(invoices), total, currency, len(overdue),
        )
        return OdooResult(success=True, data=result_data)

    # ------------------------------------------------------------------
    # Create Invoice
    # ------------------------------------------------------------------

    def create_invoice(
        self,
        customer_name: str,
        lines: list[dict],
        due_date: str = "",
        note: str = "",
    ) -> OdooResult:
        """
        Create a customer invoice (out_invoice) in Odoo.

        Args:
            customer_name: Exact name of the res.partner record.
            lines: List of dicts, each with keys:
                     description (str), quantity (float), unit_price (float)
                     Optional: account_id (int), tax_ids (list[int])
            due_date: ISO date string "YYYY-MM-DD". Empty = Odoo default.
            note:     Internal note attached to the invoice.

        Returns:
            OdooResult(success=True, data={"invoice_id": int, "name": str})
            OdooResult(success=False, error=<message>)

        Raises:
            Never. All errors are caught and returned as OdooResult(success=False).
        """
        self._require_auth()
        self._log(f"create_invoice() — customer={customer_name!r} lines={len(lines)}")

        # 1. Resolve or create partner
        partner_result = self._resolve_partner(customer_name)
        if not partner_result.success:
            return partner_result
        partner_id = partner_result.data

        # 2. Build invoice line records
        invoice_line_ids = []
        for line in lines:
            line_vals: dict[str, Any] = {
                "name":       str(line.get("description", "Service")),
                "quantity":   float(line.get("quantity",  1)),
                "price_unit": float(line.get("unit_price", 0)),
            }
            if "account_id" in line:
                line_vals["account_id"] = int(line["account_id"])
            if "tax_ids" in line:
                line_vals["tax_ids"] = [(6, 0, line["tax_ids"])]  # Odoo Many2many write
            invoice_line_ids.append((0, 0, line_vals))

        # 3. Build invoice vals
        invoice_vals: dict[str, Any] = {
            "move_type":         "out_invoice",
            "partner_id":        partner_id,
            "invoice_line_ids":  invoice_line_ids,
        }
        if due_date:
            invoice_vals["invoice_date_due"] = due_date
        if note:
            invoice_vals["narration"] = note

        # 4. Create + auto-confirm (action_post)
        try:
            invoice_id = self._execute_kw(
                "account.move", "create", [invoice_vals]
            )
            # Confirm (post) the invoice
            self._execute_kw(
                "account.move", "action_post", [[invoice_id]]
            )
            # Retrieve the assigned invoice number
            records = self._execute_kw(
                "account.move", "read", [[invoice_id]], {"fields": ["name"]}
            )
            invoice_name = records[0]["name"] if records else str(invoice_id)

        except Exception as exc:
            return self._handle_error("create_invoice", exc)

        self._log(
            f"create_invoice() — OK | id={invoice_id} name={invoice_name} "
            f"partner_id={partner_id} lines={len(lines)}"
        )
        logger.info("Invoice created: %s (id=%d) for '%s'", invoice_name, invoice_id, customer_name)
        return OdooResult(success=True, data={"invoice_id": invoice_id, "name": invoice_name})

    # ------------------------------------------------------------------
    # Partner resolution
    # ------------------------------------------------------------------

    def _resolve_partner(self, name: str) -> OdooResult:
        """
        Find an existing res.partner by name (case-insensitive) or create one.
        Returns OdooResult(success=True, data=partner_id:int).
        """
        try:
            ids = self._execute_kw(
                "res.partner", "search",
                [[("name", "ilike", name.strip())]], {"limit": 1}
            )
            if ids:
                logger.debug("Partner found: id=%d name=%r", ids[0], name)
                return OdooResult(success=True, data=ids[0])

            # Create new partner
            partner_id = self._execute_kw(
                "res.partner", "create",
                [{"name": name.strip(), "customer_rank": 1}]
            )
            self._log(f"_resolve_partner() — created new partner id={partner_id} name={name!r}")
            logger.info("New partner created: id=%d name=%r", partner_id, name)
            return OdooResult(success=True, data=partner_id)

        except Exception as exc:
            return self._handle_error("_resolve_partner", exc)

    # ------------------------------------------------------------------
    # Accounting Summary (quick snapshot)
    # ------------------------------------------------------------------

    def get_accounting_summary(self) -> OdooResult:
        """
        Return a quick AR/AP/cash snapshot for dashboard use.
        Uses account.move aggregates — no full query needed.
        """
        self._require_auth()
        self._log("get_accounting_summary() — start")

        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Accounts Receivable (open customer invoices)
            ar_ids = self._execute_kw(
                "account.move", "search",
                [[("move_type", "=", "out_invoice"), ("state", "=", "posted"),
                  ("payment_state", "!=", "paid")]],
            )
            ar_records = self._execute_kw(
                "account.move", "read", [ar_ids], {"fields": ["amount_residual"]}
            ) if ar_ids else []
            ar_total = sum(float(r["amount_residual"]) for r in ar_records)

            # Accounts Payable (open vendor bills)
            ap_ids = self._execute_kw(
                "account.move", "search",
                [[("move_type", "=", "in_invoice"), ("state", "=", "posted"),
                  ("payment_state", "!=", "paid")]],
            )
            ap_records = self._execute_kw(
                "account.move", "read", [ap_ids], {"fields": ["amount_residual"]}
            ) if ap_ids else []
            ap_total = sum(float(r["amount_residual"]) for r in ap_records)

            # Overdue invoices (customer)
            overdue_ids = self._execute_kw(
                "account.move", "search",
                [[("move_type", "=", "out_invoice"), ("state", "=", "posted"),
                  ("payment_state", "!=", "paid"), ("invoice_date_due", "<", today)]],
            )
            overdue_records = self._execute_kw(
                "account.move", "read", [overdue_ids], {"fields": ["amount_residual"]}
            ) if overdue_ids else []
            overdue_total = sum(float(r["amount_residual"]) for r in overdue_records)

            data = {
                "accounts_receivable": round(ar_total, 2),
                "accounts_payable":    round(ap_total, 2),
                "overdue_receivable":  round(overdue_total, 2),
                "open_invoices":       len(ar_ids),
                "open_bills":          len(ap_ids),
                "overdue_invoices":    len(overdue_ids),
                "as_of":               today,
            }
            self._log(
                f"get_accounting_summary() — OK | AR={ar_total:.2f} AP={ap_total:.2f} "
                f"overdue={overdue_total:.2f}"
            )
            return OdooResult(success=True, data=data)

        except Exception as exc:
            return self._handle_error("get_accounting_summary", exc)

    # ------------------------------------------------------------------
    # Low-level XML-RPC wrapper
    # ------------------------------------------------------------------

    def _execute_kw(
        self,
        model:  str,
        method: str,
        args:   list,
        kwargs: dict | None = None,
    ) -> Any:
        """
        Call models.execute_kw with the authenticated session.
        Raises xmlrpc.client.Fault or Exception on failure (caller handles).
        """
        if self._models is None or self._uid is None:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        return self._models.execute_kw(
            self._db,
            self._uid,
            self._password,
            model,
            method,
            args,
            kwargs or {},
        )

    # ------------------------------------------------------------------
    # Error handling + auth guard
    # ------------------------------------------------------------------

    def _require_auth(self) -> None:
        if self._uid is None:
            raise RuntimeError(
                "OdooAccountingSkill: Not authenticated. "
                "Call authenticate() and check result.success before data operations."
            )

    def _handle_error(self, method: str, exc: Exception) -> OdooResult:
        """Log the exception and return a graceful OdooResult(success=False)."""
        import traceback
        tb   = traceback.format_exc()
        msg  = f"{type(exc).__name__}: {exc}"
        self._log(f"{method}() — ERROR: {msg}\n{tb}")
        logger.error("%s() failed: %s", method, msg)
        return OdooResult(success=False, error=msg)

    # ------------------------------------------------------------------
    # Audit logger
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        now      = datetime.now(timezone.utc)
        log_file = self.logs_dir / "odoo_accounting_skill.log"
        entry    = f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] [SKILL-008] {message}\n"
        try:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        except OSError:
            pass
