"""
MCPEmailClient — JSON-RPC 2.0 client for the email-mcp stdio server.

Starts `node email-mcp/index.js` as a subprocess, performs the MCP
handshake, then exposes send_email() and draft_email() as Python methods.

The subprocess is started fresh for each call (stateless) to keep things
simple and avoid zombie processes in the orchestrator.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("MCPEmailClient")


class MCPEmailClient:
    """
    Thin Python wrapper around the email-mcp Node.js MCP server.

    Usage:
        client = MCPEmailClient(vault_root)

        # Send email immediately
        result = client.send_email(
            to="client@example.com",
            subject="Re: Invoice",
            body="Dear Client, ...",
        )

        # Save as draft for approval
        result = client.draft_email(
            to="client@example.com",
            subject="Proposal",
            body="Dear Client, ...",
            attachment_path="/path/to/proposal.pdf",  # optional
        )
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root   = Path(vault_root)
        self.server_path  = self.vault_root / "email-mcp" / "index.js"
        self._msg_id      = 0

    # ------------------------------------------------------------------
    # Public tools
    # ------------------------------------------------------------------

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        attachment_path: str = "",
    ) -> dict:
        """Send an email immediately via Gmail API."""
        return self._call_tool("send_email", {
            "to":              to,
            "subject":         subject,
            "body":            body,
            **({"cc": cc} if cc else {}),
            **({"attachment_path": attachment_path} if attachment_path else {}),
        })

    def draft_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        attachment_path: str = "",
    ) -> dict:
        """Save email as Gmail Draft (does NOT send — awaits human approval)."""
        return self._call_tool("draft_email", {
            "to":      to,
            "subject": subject,
            "body":    body,
            **({"cc": cc} if cc else {}),
            **({"attachment_path": attachment_path} if attachment_path else {}),
        })

    # ------------------------------------------------------------------
    # MCP protocol
    # ------------------------------------------------------------------

    def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Spawn the MCP server, handshake, call the tool, return the result.
        Returns {"success": bool, "text": str, "error": str|None}
        """
        if not self.server_path.exists():
            return self._error(f"MCP server not found: {self.server_path}")

        try:
            proc = subprocess.Popen(
                ["node", str(self.server_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=str(self.vault_root),
            )
        except FileNotFoundError:
            return self._error("node not found in PATH. Install Node.js.")
        except Exception as e:
            return self._error(f"Failed to start MCP server: {e}")

        try:
            # Step 1: Initialize handshake
            init_req = self._make_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities":    {},
                "clientInfo":      {"name": "orchestrator", "version": "1.0"},
            })
            self._write(proc, init_req)
            init_resp = self._read_response(proc)
            if init_resp is None:
                return self._error("No response to MCP initialize.")

            # Step 2: Send initialized notification (no response expected)
            self._write(proc, {
                "jsonrpc": "2.0",
                "method":  "notifications/initialized",
                "params":  {},
            })

            # Step 3: Call the tool
            tool_req = self._make_request("tools/call", {
                "name":      tool_name,
                "arguments": arguments,
            })
            self._write(proc, tool_req)
            tool_resp = self._read_response(proc)

            if tool_resp is None:
                return self._error(f"No response from tool '{tool_name}'.")

            # Parse result
            if "error" in tool_resp:
                return self._error(tool_resp["error"].get("message", "Unknown MCP error"))

            result = tool_resp.get("result", {})
            content = result.get("content", [])
            is_error = result.get("isError", False)
            text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")

            if is_error:
                return self._error(text)
            return {"success": True, "text": text, "error": None}

        except Exception as e:
            return self._error(f"MCP communication error: {e}")
        finally:
            try:
                proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    # ------------------------------------------------------------------
    # JSON-RPC helpers
    # ------------------------------------------------------------------

    def _make_request(self, method: str, params: dict) -> dict:
        self._msg_id += 1
        return {
            "jsonrpc": "2.0",
            "id":      self._msg_id,
            "method":  method,
            "params":  params,
        }

    def _write(self, proc: subprocess.Popen, msg: dict) -> None:
        line = json.dumps(msg) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()
        logger.debug("→ MCP: %s", line.strip()[:120])

    def _read_response(self, proc: subprocess.Popen, timeout: int = 15) -> dict | None:
        """Read lines from stdout until we get a JSON object with an 'id' field."""
        import select
        import time

        deadline = time.time() + timeout
        buf = ""

        while time.time() < deadline:
            # On Windows, use a simple readline approach
            try:
                line = proc.stdout.readline()
            except Exception:
                return None

            if not line:
                if proc.poll() is not None:
                    logger.debug("MCP server exited with code %d", proc.returncode)
                    return None
                continue

            buf += line
            logger.debug("← MCP: %s", line.strip()[:120])

            # Try to parse accumulated buffer as JSON
            try:
                msg = json.loads(buf.strip())
                # Only return if it's a response (has 'id') not a notification
                if "id" in msg:
                    return msg
                # It's a notification, keep reading
                buf = ""
            except json.JSONDecodeError:
                pass  # incomplete JSON, keep reading

        logger.warning("MCP response timed out after %ds.", timeout)
        return None

    @staticmethod
    def _error(msg: str) -> dict:
        logger.error("MCPEmailClient: %s", msg)
        return {"success": False, "text": "", "error": msg}
