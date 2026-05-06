---
title: Agent Skills
version: 1.0
last_updated: 2026-03-09
tier: Bronze
status: active
---

# Agent Skills

All skills available to the Bronze Tier AI Employee. Each skill has a defined trigger, process, and output.

---

## Skill 001 — Read Needs_Action and Create Plan

**Skill ID:** SKILL-001
**Description:** Reads all items in the `Needs_Action` folder and generates a structured `Plan.md` file in the `Plans` folder based on what needs to be done.

**When to Use:**
- At the start of each work session.
- When new items have been moved into `Needs_Action`.
- When the current plan is stale or missing.

**Step-by-Step Process:**

1. Open the `Needs_Action` folder and list all files.
2. For each file, extract: task title, owner, due date (if present), and priority.
3. Sort tasks by priority: High → Medium → Low.
4. Create or overwrite `Plans/Plan.md` with the structured task list.
5. Add a timestamp to the plan header.
6. Update `Dashboard.md` to reflect that the plan was refreshed (see Skill 003).
7. Log the action in `Logs` with format: `[DATE] SKILL-001 executed — Plan.md updated.`

---

## Skill 002 — Move Completed Tasks to Done

**Skill ID:** SKILL-002
**Description:** Moves task files from `Approved` (or `Needs_Action`) into the `Done` folder once a task is confirmed complete.

**When to Use:**
- After a task has been approved and fully executed.
- When a user explicitly marks a task as complete.
- During end-of-day cleanup.

**Step-by-Step Process:**

1. Identify the task file to be closed (confirm it is in `Approved` or `Needs_Action`).
2. Verify the task is actually complete — do not move if work is still pending.
3. Add a completion note to the bottom of the task file:
   > Completed: [DATE] | Authorized by: [NAME]
4. Move the file from its current folder to `Done/`.
5. Update `Dashboard.md` Recent Activity table (see Skill 003).
6. Log the action in `Logs` with format: `[DATE] SKILL-002 — [filename] moved to Done.`

---

## Skill 003 — Update Dashboard After Every Action

**Skill ID:** SKILL-003
**Description:** Keeps `Dashboard.md` current by updating the Recent Activity table and Pending Tasks checklist after any significant action is taken.

**When to Use:**
- After every skill execution (001, 002, 004).
- After any file is created, moved, or modified.
- At the start and end of each work session.

**Step-by-Step Process:**

1. Open `Dashboard.md`.
2. Add a new row to the **Recent Activity** table:

   | [DATE] | [Action taken] | [Status] | [Authorized by] |

3. Review the **Pending Tasks** checklist — check off any completed items.
4. Review the **Next Actions** list — update or add items based on current state.
5. Save `Dashboard.md`.
6. Log the dashboard update in `Logs` with format: `[DATE] SKILL-003 — Dashboard.md updated.`

> Note: This skill runs automatically as a final step of every other skill.

---

## Skill 004 — Create Approval Request for Sensitive Actions

**Skill ID:** SKILL-004
**Description:** Generates a structured approval request and places it in `Pending_Approval` when a sensitive action is detected (e.g., payments over $100, data deletion, external sharing).

**When to Use:**
- Any payment or expense over $100.
- Any action involving deletion of files or records.
- Any action that shares internal data externally.
- Any action outside the normal task lifecycle.

**Step-by-Step Process:**

1. Stop all execution immediately — do not proceed with the sensitive action.
2. Create a new file in `Pending_Approval/` named: `APPROVAL-[DATE]-[short-description].md`
3. Populate the file using this format:

   ```
   APPROVAL REQUEST
   Date: [DATE]
   Requested by: AI Employee (Bronze Tier)
   Action: [describe the action clearly]
   Amount (if payment): $[X]
   Reason: [why this action is needed]
   Risk level: [Low / Medium / High]
   Awaiting approval from: [NAME or ROLE]
   ```

4. Flag the request in `Dashboard.md` Pending Tasks checklist.
5. Update `Dashboard.md` Recent Activity table (Skill 003).
6. Log in `Logs`: `[DATE] SKILL-004 — Approval request created: [filename].`
7. Do not retry the action until explicit human approval is received and documented.

---

*Bronze Tier — Agent Skills v1.0 | See [[Company_Handbook]] for Rules of Engagement.*
