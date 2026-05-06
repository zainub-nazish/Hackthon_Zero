# Plan — test_invoice.pdf Processing

> Created: 2026-03-09 | Status: In Planning | Owner: Unassigned

---

## Summary

A PDF file `test_invoice.pdf` was detected in `Inbox` by the FileSystemWatcher and automatically routed to `Needs_Action` as `FILE_test_invoice.pdf`. This plan tracks review, approval, and archival.

---

## Checklist

### 1. Intake & Triage
- [x] File detected in `Inbox` by FileSystemWatcher
- [x] File copied to `Needs_Action` as `FILE_test_invoice.pdf`
- [x] Metadata file `FILE_test_invoice.meta.md` created
- [ ] Assign owner/reviewer for this invoice

### 2. Review
- [ ] Open `FILE_test_invoice.pdf` and verify contents
- [ ] Confirm invoice number, vendor, and amount
- [ ] Cross-check against purchase orders or contracts
- [ ] Flag any discrepancies or missing fields

### 3. Approval
- [ ] Move file to `Pending_Approval` once review is complete
- [ ] Notify approver via written comment in `Pending_Approval` note
- [ ] Wait for approval decision (SLA: 48 hours)

### 4. Post-Approval
- [ ] If **Approved**: move to `Approved/`, then process payment
- [ ] If **Rejected**: move to `Rejected/`, note reason, restart from `Needs_Action`

### 5. Archival
- [ ] Move final file to `Done/`
- [ ] Append entry to `Logs/` (date, file name, outcome, owner)
- [ ] Update `Dashboard.md` status for this task

---

## Metadata

| Field          | Value                        |
|----------------|------------------------------|
| Source File    | `test_invoice.pdf`           |
| Action File    | `FILE_test_invoice.pdf`      |
| Detected At    | 2026-03-09 23:20:00 UTC      |
| Route          | Inbox → Needs_Action → ...   |
| Related Folder | `Needs_Action/`              |

---

## Risks

1. **Unassigned owner** — invoice may sit past 24h SLA without a named reviewer.
2. **Missing context** — test file has 0 bytes; real invoice validation requires file content.
3. **Approval delay** — if approver is unavailable, escalate via `Briefings/`.

---

*Reference: [[Company_Handbook]] — Folder Lifecycle Rules*
