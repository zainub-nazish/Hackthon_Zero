"""
OdooSkill — SKILL-008
Gold Tier: Odoo Community integration via JSON-RPC MCP server.

Wraps the odoo-mcp Node.js server in a Python skill interface.
Used by the orchestrator to sync vault data with Odoo.

Key operations:
  - create_customer_from_note(file_path)  — parse email/contact note → Odoo customer
  - create_invoice_from_note(file_path)   — parse invoice meta → Odoo invoice
  - sync_task_to_odoo(file_path)          — create Odoo task from plan note
  - get_accounting_summary()              — pull AR/AP/overdue from Odoo
  - run_weekly_audit()                    — full weekly accounting audit
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("OdooSkill")


class OdooMCPClient:
    """Thin JSON-RPC 2.0 client that spawns odoo-mcp/index.js as a subprocess."""

    def __init__(self, vault_root: Path) -> None:
        self._server  = Path(vault_root) / "odoo-mcp" / "index.js"
        self._msg_id  = 0

    def call(self, tool: str, args: dict) -> dict:
        if not self._server.exists():
            return self._err(f"odoo-mcp not found at {self._server}")

        try:
            proc = subprocess.Popen(
                ["node", str(self._server)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
            )
        except FileNotFoundError:
            return self._err("node not found — install Node.js")
        except Exception as e:
            return self._err(str(e))

        try:
            self._msg_id += 1
            # Handshake
            self._write(proc, {"jsonrpc":"2.0","id":self._msg_id,"method":"initialize",
                "params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"odoo_skill","version":"1.0"}}})
            self._read(proc)
            self._write(proc, {"jsonrpc":"2.0","method":"notifications/initialized","params":{}})

            # Tool call
            self._msg_id += 1
            self._write(proc, {"jsonrpc":"2.0","id":self._msg_id,"method":"tools/call",
                "params":{"name":tool,"arguments":args}})
            resp = self._read(proc)

            if not resp:
                return self._err("No response from odoo-mcp")
            if "error" in resp:
                return self._err(resp["error"].get("message","Unknown error"))

            result  = resp.get("result", {})
            content = result.get("content", [])
            is_err  = result.get("isError", False)
            text    = " ".join(c.get("text","") for c in content if c.get("type") == "text")
            if is_err:
                return self._err(text)
            return {"success": True, "text": text}

        except Exception as e:
            return self._err(str(e))
        finally:
            try:
                proc.stdin.close()
                proc.wait(timeout=15)
            except Exception:
                proc.kill()

    def _write(self, proc, msg):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def _read(self, proc, timeout: int = 20) -> dict | None:
        import time
        deadline = time.time() + timeout
        buf = ""
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    return None
                continue
            buf += line
            try:
                msg = json.loads(buf.strip())
                if "id" in msg:
                    return msg
                buf = ""
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _err(msg: str) -> dict:
        logger.error("OdooMCPClient: %s", msg)
        return {"success": False, "text": "", "error": msg}


class OdooSkill:
    """
    SKILL-008 — Odoo integration for the Gold Tier AI Employee.
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)
        self._client    = OdooMCPClient(vault_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_customer_from_note(self, file_path: Path) -> dict:
        """Parse an EMAIL_*.md or contact note and create an Odoo customer."""
        text = file_path.read_text(encoding="utf-8")

        name  = self._extract(text, r"From\s*\|\s*(.+?)\s*\|") or \
                self._extract(text, r"\*\*From:\*\*\s*(.+)") or "Unknown"
        email = self._extract(text, r"[\w.+-]+@[\w-]+\.[a-z]{2,}")
        phone = self._extract(text, r"(?:Phone|Tel|Mobile)[:\s]+([+\d\s\-()]{7,})")

        result = self._client.call("create_customer", {
            "name": name, "email": email, "phone": phone
        })

        logger.info("Customer sync: %s → %s", file_path.name, result.get("text", "")[:60])
        return result

    def create_invoice_from_note(self, file_path: Path) -> dict:
        """Parse an invoice .meta.md and create an Odoo invoice."""
        text = file_path.read_text(encoding="utf-8")

        customer = self._extract(text, r"(?:Vendor|From|Customer)[:\s|]+([^\n|]+)")
        amount   = self._extract_float(text, r"\$?([\d,]+\.?\d*)")
        due_date = self._extract(text, r"Due[:\s|]+(\d{4}-\d{2}-\d{2})")

        lines = []
        if amount:
            desc = self._extract(text, r"(?:Description|Item|Service)[:\s|]+([^\n|]+)") or "Service"
            lines.append({"description": desc.strip(), "quantity": 1, "unit_price": amount})

        result = self._client.call("create_invoice", {
            "customer_name": customer.strip() if customer else "Unknown",
            "lines":         lines,
            "due_date":      due_date or "",
        })

        logger.info("Invoice sync: %s → %s", file_path.name, result.get("text","")[:60])
        return result

    def sync_task_to_odoo(self, file_path: Path) -> dict:
        """Create an Odoo task from a Plans/*.md file."""
        text    = file_path.read_text(encoding="utf-8")
        name    = self._extract(text, r"^#\s+(.+)", re.MULTILINE) or file_path.stem
        project = self._extract(text, r"Project[:\s|]+([^\n|]+)") or "AI Employee Tasks"
        due     = self._extract(text, r"Due[:\s|]+(\d{4}-\d{2}-\d{2})")
        desc    = text[:500]

        result = self._client.call("create_task", {
            "name":         name.strip(),
            "project_name": project.strip(),
            "description":  desc,
            "deadline":     due or "",
        })

        logger.info("Task sync: %s → %s", file_path.name, result.get("text","")[:60])
        return result

    def get_accounting_summary(self) -> str:
        result = self._client.call("get_accounting_summary", {})
        return result.get("text", result.get("error", "Odoo not available"))

    def run_weekly_audit(self) -> str:
        result = self._client.call("run_weekly_audit", {})
        return result.get("text", result.get("error", "Odoo audit failed"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract(self, text: str, pattern: str, flags: int = 0) -> str:
        m = re.search(pattern, text, flags)
        return m.group(1).strip() if m else ""

    def _extract_float(self, text: str, pattern: str) -> float | None:
        m = re.search(pattern, text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
        return None
