"""
Obsidian Vault Setup Script
Run this from your Obsidian vault root directory:
    python setup_vault.py

Creates all 9 folders and 2 markdown files automatically.
"""

import os
from pathlib import Path

VAULT_ROOT = Path(__file__).parent

FOLDERS = [
    "Inbox",
    "Needs_Action",
    "Done",
    "Pending_Approval",
    "Approved",
    "Rejected",
    "Plans",
    "Logs",
    "Briefings",
]

COMPANY_HANDBOOK = """\
# Company Handbook
> Last Updated: 2026-03-09 | Version: 1.0

---

## Table of Contents
1. [Mission](#mission)
2. [Core Values](#core-values)
3. [Folder Lifecycle](#folder-lifecycle)
4. [Communication Guidelines](#communication-guidelines)

---

## Mission

We exist to move work forward — clearly, quickly, and without noise.

Our mission is to build a disciplined, transparent, and high-trust workplace where every task has an owner, every decision has a record, and nothing falls through the cracks.

> "Clarity is kindness. A clear task is a done task."

---

## Core Values

### 1. Ownership
Every item in the system belongs to exactly one person at any given time. If it's in your name, it's your responsibility — no exceptions.

### 2. Transparency
Work is visible by default. Status updates are not meetings — they are written records in the appropriate folder.

### 3. Precision
Vague is expensive. Every task description must include: **What**, **Why**, **Who**, and **When**.

### 4. Speed with Quality
Move fast. But a task that reaches `Done` must actually be done — not just forwarded or forgotten.

### 5. Trust the System
The folder workflow exists so nothing requires memory. Trust the process; update the folders.

---

## Folder Lifecycle

The following describes how work moves through the system. Each folder represents a single state.

```
[Inbox] → [Needs_Action] → [Pending_Approval] → [Approved] → [Done]
                        ↘ [Rejected]
```

### Stage Descriptions

| Folder | State | Owner Responsibility |
|---|---|---|
| `Inbox` | New / Unsorted | Review within 24 hours |
| `Needs_Action` | Assigned, awaiting work | Start or delegate within 1 business day |
| `Pending_Approval` | Work complete, needs sign-off | Notify approver immediately |
| `Approved` | Signed off, ready to archive | Move to `Done` or deploy |
| `Done` | Closed | No further action needed |
| `Rejected` | Returned for revision | Review feedback, restart from `Needs_Action` |
| `Plans` | Strategic documents | Living documents; version-controlled |
| `Logs` | Activity records | Append-only; never delete entries |
| `Briefings` | Summaries / Status reports | Shared with stakeholders |

### Lifecycle Rules

- **Inbox is not a storage room.** Items stay there max 24 hours.
- **Rejected items must carry a reason.** No silent rejections.
- **Done is final.** If a task needs revision, reopen it as a new `Inbox` item.
- **Logs are immutable.** Append new entries; do not edit old ones.

---

## Communication Guidelines

### Written-First Culture
All decisions, task updates, and approvals happen in writing — in the relevant folder notes, not in chat or memory.

### Response SLAs

| Channel | Expected Response Time |
|---|---|
| `Inbox` items | 24 hours |
| `Needs_Action` tasks | 1 business day to acknowledge |
| `Pending_Approval` requests | 48 hours to approve or reject |
| `Briefings` | Read within 24 hours of distribution |

### Escalation Path
1. Comment in the relevant note with `@name` mention.
2. If no response in SLA window → escalate to `Briefings` with status flag.
3. If still unresolved → escalate to leadership via a new `Inbox` item tagged `ESCALATION`.

### Language Standards
- Use **imperative verbs** for task titles: *"Review proposal"*, *"Approve budget"*, *"Fix login bug"*
- Use **ISO dates** (`YYYY-MM-DD`) everywhere — no ambiguous formats.
- No passive voice in status updates. Bad: *"It was reviewed."* Good: *"Dana reviewed and approved on 2026-03-09."*

---

*This handbook is a living document. Propose changes via a new `Inbox` item tagged `HANDBOOK-UPDATE`.*
"""

DASHBOARD = """\
# Command Center
> Updated: 2026-03-09 | Refresh this view each morning.

---

## High Priority

- [ ] Review all items in `Inbox` (SLA: today)
- [ ] Clear `Needs_Action` — assign or start every item
- [ ] Follow up on anything in `Pending_Approval` older than 48 hours
- [ ] Check `Rejected` items — confirm feedback has been acted on
- [ ] Log today's activity in [[Logs]]
- [ ] Read any new [[Briefings]]

---

## System Status

| Folder | Status | Notes |
|---|---|---|
| `Inbox` | 🟡 Active | Triage daily — clear within 24h |
| `Needs_Action` | 🔵 In Progress | Assign owner per item |
| `Pending_Approval` | 🟠 Waiting | Ping approvers if >48h |
| `Approved` | 🟢 Ready | Move to Done or deploy |
| `Done` | ✅ Closed | Archive only |
| `Rejected` | 🔴 Needs Rework | Check feedback, reroute to Needs_Action |
| `Plans` | 📄 Reference | Strategic docs — version-controlled |
| `Logs` | 📋 Append-Only | Never edit past entries |
| `Briefings` | 📢 Shared | Read within 24h of issue |

---

## Quick Links

- [[Company_Handbook]] — Roles, values, lifecycle rules, communication SLAs
- [[Logs]] — Activity log (append-only)
- [[Plans]] — Strategic planning documents
- [[Briefings]] — Status reports and stakeholder summaries

---

## Folder Lifecycle (At a Glance)

```
Inbox → Needs_Action → Pending_Approval → Approved → Done
                    ↘ Rejected → (revise) → Needs_Action
```

---

## Today's Log Entry

> Copy this block into [[Logs]] at end of day.

```
## Log Entry — 2026-03-09

### Completed
-

### In Progress
-

### Blocked
-

### Notes
-
```

---

*Reference: [[Company_Handbook]] | Logs: [[Logs]] | Reports: [[Briefings]]*
"""

FILES = {
    "Company_Handbook.md": COMPANY_HANDBOOK,
    "Dashboard.md": DASHBOARD,
}


def create_folders():
    for folder in FOLDERS:
        path = VAULT_ROOT / folder
        path.mkdir(exist_ok=True)
        # Add a .gitkeep so the folder is tracked if using git
        gitkeep = path / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()
        print(f"  [+] Folder: {folder}/")


def create_files():
    for filename, content in FILES.items():
        path = VAULT_ROOT / filename
        if path.exists():
            print(f"  [~] Skipped (already exists): {filename}")
        else:
            path.write_text(content, encoding="utf-8")
            print(f"  [+] File:   {filename}")


def main():
    print(f"\nObsidian Vault Setup")
    print(f"Vault root: {VAULT_ROOT}\n")

    print("Creating folders...")
    create_folders()

    print("\nCreating markdown files...")
    create_files()

    print("\nDone. Open your vault in Obsidian and you're ready to go.")


if __name__ == "__main__":
    main()
