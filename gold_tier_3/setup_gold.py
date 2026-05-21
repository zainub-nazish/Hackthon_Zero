"""
setup_gold.py — Gold Tier one-time setup script.

Run this once after cloning to:
  1. Create all required vault folders
  2. Install Python dependencies (uv)
  3. Install Node.js dependencies for all MCP servers
  4. Validate .env configuration
  5. Check Docker + Odoo readiness
  6. Print a startup checklist

Usage:
    python setup_gold.py
    python setup_gold.py --check-only   (validate without installing)
    python setup_gold.py --odoo-up      (also start Odoo via Docker Compose)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def header(title: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


def ok(msg: str)   -> None: print(f"  [OK]   {msg}")
def warn(msg: str) -> None: print(f"  [WARN] {msg}")
def fail(msg: str) -> None: print(f"  [FAIL] {msg}")
def info(msg: str) -> None: print(f"  [INFO] {msg}")


# ---------------------------------------------------------------------------
# Step 1 — Vault folders
# ---------------------------------------------------------------------------

VAULT_FOLDERS = [
    "Inbox", "Needs_Action", "Needs_Action",
    "Pending_Approval", "Approved", "Done",
    "Rejected", "Plans", "Logs", "Briefings",
    "history/prompts/general", "history/adr",
    "docs", "odoo/addons",
]

def create_folders() -> None:
    header("Creating Vault Folders")
    for folder in VAULT_FOLDERS:
        path = ROOT / folder
        path.mkdir(parents=True, exist_ok=True)
        ok(f"{folder}/")


# ---------------------------------------------------------------------------
# Step 2 — Python dependencies
# ---------------------------------------------------------------------------

PYTHON_DEPS = [
    "httpx", "anthropic", "watchdog", "playwright",
    "google-api-python-client", "google-auth-httplib2", "google-auth-oauthlib",
    "python-dotenv",
]

def install_python_deps(check_only: bool) -> None:
    header("Python Dependencies")
    uv = shutil.which("uv")
    pip = shutil.which("pip") or shutil.which("pip3")

    if check_only:
        for dep in PYTHON_DEPS:
            pkg = dep.split("[")[0].replace("-", "_")
            try:
                __import__(pkg.split("_")[0])
                ok(dep)
            except ImportError:
                warn(f"{dep} not installed")
        return

    installer = [uv, "add"] if uv else ([sys.executable, "-m", "pip", "install"] if pip else None)
    if not installer:
        fail("Neither uv nor pip found — install manually.")
        return

    result = subprocess.run(installer + PYTHON_DEPS, capture_output=True, text=True)
    if result.returncode == 0:
        ok(f"All Python deps installed via {'uv' if uv else 'pip'}")
    else:
        warn(f"Some Python deps may have failed:\n{result.stderr[:200]}")

    # Playwright browsers
    pw = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True,
    )
    if pw.returncode == 0:
        ok("Playwright Chromium installed")
    else:
        warn("Playwright Chromium install failed — run manually: playwright install chromium")


# ---------------------------------------------------------------------------
# Step 3 — Node.js MCP servers
# ---------------------------------------------------------------------------

MCP_SERVERS = ["email-mcp", "odoo-mcp", "facebook-mcp", "twitter-mcp"]

def install_node_deps(check_only: bool) -> None:
    header("Node.js MCP Server Dependencies")

    node = shutil.which("node")
    npm  = shutil.which("npm")

    if not node:
        fail("Node.js not found — install from nodejs.org (v18+)")
        return

    ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    ok(f"Node.js {ver} found")

    for server in MCP_SERVERS:
        path = ROOT / server
        if not path.exists():
            warn(f"{server}/ not found — skipping")
            continue

        if check_only:
            node_modules = path / "node_modules"
            if node_modules.exists():
                ok(f"{server}: dependencies installed")
            else:
                warn(f"{server}: npm install needed")
            continue

        result = subprocess.run(["npm", "install"], cwd=path, capture_output=True, text=True)
        if result.returncode == 0:
            ok(f"{server}: npm install complete")
        else:
            warn(f"{server}: npm install failed\n{result.stderr[:100]}")


# ---------------------------------------------------------------------------
# Step 4 — .env validation
# ---------------------------------------------------------------------------

REQUIRED_VARS = {
    "ANTHROPIC_API_KEY":     "Claude API (required for AI generation)",
    "CEO_EMAIL":             "CEO email for weekly briefing",
    "ODOO_URL":              "Odoo URL (http://localhost:8069)",
    "FB_PAGE_ACCESS_TOKEN":  "Facebook Page Access Token",
    "FB_PAGE_ID":            "Facebook Page numeric ID",
    "IG_ACCOUNT_ID":         "Instagram Business Account ID",
    "TWITTER_BEARER_TOKEN":  "Twitter Bearer Token (read)",
    "TWITTER_USER_ID":       "Twitter numeric user ID",
}

def validate_env() -> None:
    header("Environment Variable Validation")

    env_file = ROOT / ".env"
    if env_file.exists():
        ok(".env file found")
        # Load .env into os.environ for validation
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    else:
        warn(".env not found — copy .env.example to .env and fill in credentials")
        example = ROOT / ".env.example"
        if example.exists():
            import shutil as _sh
            _sh.copy(example, env_file)
            info(".env.example copied to .env — please edit it")

    for var, desc in REQUIRED_VARS.items():
        val = os.environ.get(var, "")
        if val and val not in ("your_app_id", "sk-ant-...", "xxxxx", ""):
            ok(f"{var} ✓")
        else:
            warn(f"{var} not set — {desc}")


# ---------------------------------------------------------------------------
# Step 5 — Docker + Odoo
# ---------------------------------------------------------------------------

def check_docker(start_odoo: bool) -> None:
    header("Docker + Odoo")

    docker = shutil.which("docker")
    if not docker:
        warn("Docker not found — install Docker Desktop from docker.com")
        return
    ok("Docker found")

    compose_file = ROOT / "odoo" / "docker-compose.yml"
    if not compose_file.exists():
        warn("odoo/docker-compose.yml not found")
        return
    ok("odoo/docker-compose.yml found")

    if start_odoo:
        info("Starting Odoo via Docker Compose…")
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True, text=True, cwd=ROOT,
        )
        if result.returncode == 0:
            ok("Odoo started. Access at http://localhost:8069")
            info("First run: create database 'odoo' with master password from odoo.conf")
        else:
            fail(f"Docker Compose failed:\n{result.stderr[:200]}")
    else:
        info("Run with --odoo-up to start Odoo, or manually:")
        info("  docker compose -f odoo/docker-compose.yml up -d")


# ---------------------------------------------------------------------------
# Startup checklist
# ---------------------------------------------------------------------------

def print_checklist() -> None:
    header("Gold Tier Startup Checklist")
    steps = [
        ("python watchers/filesystem_watcher.py",   "Bronze: File system watcher"),
        ("python watchers/gmail_watcher.py",        "Silver: Gmail watcher"),
        ("python watchers/whatsapp_watcher.py",     "Silver: WhatsApp watcher"),
        ("python watchers/linkedin_watcher.py --setup (first time)", "Silver: LinkedIn login"),
        ("python watchers/linkedin_watcher.py",     "Silver: LinkedIn watcher"),
        ("python watchers/facebook_watcher.py",     "Gold:   Facebook watcher"),
        ("python watchers/instagram_watcher.py",    "Gold:   Instagram watcher"),
        ("python watchers/twitter_watcher.py",      "Gold:   Twitter watcher"),
        ("python orchestrator.py",                  "Gold:   Main orchestrator (all skills)"),
        ("node email-mcp/index.js",                 "MCP:    Email server"),
        ("node odoo-mcp/index.js",                  "MCP:    Odoo server"),
        ("node facebook-mcp/index.js",              "MCP:    Facebook/Instagram server"),
        ("node twitter-mcp/index.js",               "MCP:    Twitter server"),
    ]
    for cmd, desc in steps:
        print(f"  □  {desc}")
        print(f"       {cmd}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Gold Tier AI Employee setup")
    p.add_argument("--check-only", action="store_true", help="Validate without installing")
    p.add_argument("--odoo-up",    action="store_true", help="Start Odoo via Docker Compose")
    args = p.parse_args()

    print("\n  Gold Tier AI Employee — Setup")
    print("  Building Autonomous FTEs in 2026")

    create_folders()
    install_python_deps(args.check_only)
    install_node_deps(args.check_only)
    validate_env()
    check_docker(args.odoo_up)
    print_checklist()

    print("\n  Setup complete. Edit .env with your credentials, then start the watchers.")
