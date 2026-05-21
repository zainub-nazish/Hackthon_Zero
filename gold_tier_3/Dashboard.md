---
title: Dashboard
subtitle: AI Employee Command Center
last_updated: 2026-04-23
tier: Bronze
status: active
---

# Dashboard — AI Employee Command Center

---

## Bank Balance

| Account | Balance | Last Updated |
|---|---|---|
| Main Operating Account | `[PLACEHOLDER]` | 2026-03-09 |
| Reserve Account | `[PLACEHOLDER]` | 2026-03-09 |

> Note: Connect to live data source to populate balances automatically.

---

## Pending Tasks

- [ ] Review items in `Inbox`
- [x] **[2026-03-09] FILE_test_invoice.pdf** — routed to `Needs_Action` by FileSystemWatcher → [[Plans/test_invoice_plan]]
- [ ] Process items in `Needs_Action`
- [ ] Follow up on `Pending_Approval` items older than 48 hours
- [ ] Check `Rejected` folder for items needing rework
- [ ] Flag any payment requests over $100 for human approval

---

## Recent Activity

| Date | Action | Status | Authorized By |
|---|---|---|---|
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19db894b91f6.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19db32a27051.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19da42f7f7e3.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19da42f6ccc6.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19da42ce7309.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19da42b4e6e3.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19da3c4d16c7.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19ced9888cfa.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19ce6042b3fa.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19ce603eaa6b.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19ce5f470453.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19ce5e355a8f.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-04-23 05:25 UTC | Approval request created for EMAIL_19ce5dea1779.md | Pending_Approval | ApprovalSkill (SKILL-004) |
| 2026-03-09 | Vault initialized | Done | User |
| 2026-03-09 | Handbook v2.0 created | Done | User |
| 2026-03-09 | Dashboard created | Done | User |
| 2026-03-09 | test_invoice.pdf detected in Inbox | Needs_Action | FileSystemWatcher |
| 2026-03-09 | test_invoice_plan.md created | In Planning | Agent |
| 2026-03-09 | FILE_test_invoice.pdf planning complete | Done | Agent |

---

## Next Actions

1. Connect bank account data source to replace `[PLACEHOLDER]` values.
2. Move all new incoming requests into `Inbox` for daily triage.
3. Review [[Company_Handbook]] rules before executing any task.
4. Log all completed work into [[Logs]] at end of day.

---

*Reference: [[Company_Handbook]] | Activity: [[Logs]] | Reports: [[Briefings]]*
