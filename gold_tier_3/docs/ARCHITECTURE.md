# Gold Tier Architecture — Personal AI Employee
## "Building Autonomous FTEs in 2026"

---

## 1. System Overview

The Gold Tier AI Employee is a fully autonomous digital worker that monitors multiple communication channels, processes business documents, integrates with an ERP system (Odoo), and manages social media presence — all without human intervention except for high-value approval decisions.

```
┌─────────────────────────────────────────────────────────────────┐
│                        WATCHERS LAYER                           │
│  Gmail  WhatsApp  LinkedIn  Facebook  Instagram  Twitter  Files  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ writes to Needs_Action/
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      VAULT (Obsidian)                           │
│  Inbox/  Needs_Action/  Pending_Approval/  Done/  Briefings/    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ reads from Needs_Action/
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (Ralph Loop)                    │
│  Classify → Plan/Approve → Execute → Done                       │
└──────────┬──────────────────────────────────┬───────────────────┘
           │                                  │
           ▼                                  ▼
┌──────────────────────┐          ┌───────────────────────────────┐
│    AGENT SKILLS      │          │         MCP SERVERS           │
│  001 Plan            │          │  email-mcp    → Gmail send    │
│  002 Done            │          │  odoo-mcp     → Odoo ERP      │
│  003 Dashboard       │          │  facebook-mcp → FB + IG       │
│  004 Approval        │          │  twitter-mcp  → Twitter (X)   │
│  005 LinkedIn Post   │          └───────────────────────────────┘
│  006 Facebook Post   │
│  007 Twitter Post    │
│  008 Odoo Sync       │
│  009 CEO Briefing    │
│  010 Ralph Loop      │
└──────────────────────┘
```

---

## 2. Tier Progression

| Tier | What's Running | Integration |
|------|---------------|-------------|
| Bronze | File system watcher + vault | Local only |
| Silver | Gmail + WhatsApp + LinkedIn + email-mcp | Google + Playwright |
| Gold | + Facebook + Instagram + Twitter + Odoo ERP | Graph API + Twitter v2 + Docker |

---

## 3. Component Architecture

### 3A. Watchers (Python)
All watchers inherit from `BaseWatcher` (abstract polling loop).

| Watcher | Protocol | Dedup | Output |
|---------|----------|-------|--------|
| `filesystem_watcher.py` | File polling | FILE_ prefix exists? | FILE_*.meta.md |
| `gmail_watcher.py` | Google OAuth2 API | gmail_seen_ids.json | EMAIL_*.md |
| `whatsapp_watcher.py` | Playwright (Web) | whatsapp_seen.txt | WHATSAPP_*.md |
| `linkedin_watcher.py` | Playwright (Browser) | linkedin_seen.txt | LINKEDIN_*.md |
| `facebook_watcher.py` | Graph API v19 | facebook_seen.json | FACEBOOK_*.md |
| `instagram_watcher.py` | Graph API v19 | instagram_seen.json | INSTAGRAM_*.md |
| `twitter_watcher.py` | Twitter API v2 | twitter_seen.json + since_id | TWITTER_*.md |

**Dedup strategy:** Every watcher maintains a persistent seen-ID file. On restart, it loads the file and skips already-processed items. This makes watchers fully restart-safe.

### 3B. Orchestrator (Python)
`orchestrator.py` runs a 30-second poll cycle:

```
Cycle:
  1. Scan Needs_Action/*.md
      → SKILL-004: Detect sensitive actions → Pending_Approval/
      → SKILL-001: Safe actions → Plans/
  2. Scan Approved/*.md
      → Parse action type (email_send, odoo_sync, social_post)
      → Call appropriate MCP server
      → Move to Done/
  3. SKILL-003: Update Dashboard
  4. Ralph Loop: Execute any queued autonomous tasks
```

### 3C. MCP Servers (Node.js)
Each MCP server is a separate process communicating via JSON-RPC 2.0 over stdio.

| Server | Tools | Auth |
|--------|-------|------|
| `email-mcp` | send_email, draft_email | Google OAuth2 (token.json) |
| `odoo-mcp` | create_customer, create_invoice, get_invoices, mark_paid, create_task, run_weekly_audit | Odoo JSON-RPC (username/password) |
| `facebook-mcp` | post_to_facebook, get_page_messages, reply_to_message, post_to_instagram, get_instagram_comments, get_social_summary | Facebook Page Access Token |
| `twitter-mcp` | post_tweet, reply_to_tweet, get_mentions, get_twitter_summary | OAuth 1.0a + Bearer Token |

### 3D. Ralph Wiggum Loop (SKILL-010)
The autonomous multi-step task executor.

```
Goal → Claude decomposes into steps → Execute step 1
  Success? → Next step
  Fail?    → Claude suggests correction → Retry (max 3×)
  Still failing? → Escalate to Pending_Approval/ → Human reviews
```

Named after Ralph Wiggum (The Simpsons) — it keeps trying different things until something works, then reports success with mild confusion about what happened.

**Key properties:**
- Each step is independently retried (not the whole goal)
- Exponential backoff: 2s, 4s, 8s between retries
- Full execution log in `Logs/ralph_loop.log`
- Escalation creates `APPROVAL-{date}-ralph-escalation.md`
- Claude is used for both decomposition AND self-correction

### 3E. Odoo Integration (Docker)
```
docker-compose.yml:
  odoo:17.0  (port 8069)
  postgres:15 (internal only)

Connection: JSON-RPC 2.0 at http://localhost:8069/web/dataset/call_kw
Auth: Database + username + password → returns uid
All operations: execute(model, method, args, kwargs)
```

**Models used:**
- `res.partner` — customers/vendors
- `account.move` — invoices (out_invoice) and bills (in_invoice)
- `project.task` — tasks
- `sale.order` — sale orders

---

## 4. Data Flow Example: Facebook Message → Odoo Invoice

```
1. Customer sends FB message: "I need a quote for 10 units"
2. FacebookWatcher polls Graph API → finds new message
3. Writes FACEBOOK_MSG_CustomerName_20260506.md to Needs_Action/
4. Orchestrator cycle runs:
   a. SKILL-004: Not sensitive → no approval needed
   b. SKILL-001: Creates Plans/FACEBOOK_MSG_CustomerName_plan.md
5. Human (or Ralph Loop) reviews plan, moves to Approved/
6. Orchestrator executes Approved file:
   a. Parses customer name + email from FB message
   b. Calls odoo-mcp: create_customer → Odoo customer ID
   c. Calls odoo-mcp: create_invoice → Odoo invoice ID
   d. Calls facebook-mcp: reply_to_message → "Invoice sent!"
   e. Calls email-mcp: send_email → PDF invoice to customer
7. Moves Approved file to Done/
8. Updates Dashboard.md
```

---

## 5. Agent Skills Reference

| ID | Name | Tier | Trigger |
|----|------|------|---------|
| SKILL-001 | PlanSkill | Bronze | New item in Needs_Action/ |
| SKILL-002 | DoneSkill | Bronze | Task confirmed complete |
| SKILL-003 | DashboardSkill | Bronze | After every action |
| SKILL-004 | ApprovalSkill | Bronze | Sensitive action detected |
| SKILL-005 | LinkedInPostSkill | Silver | Scheduled / on-demand |
| SKILL-006 | FacebookPostSkill | Gold | Scheduled / on-demand |
| SKILL-007 | TwitterPostSkill | Gold | Scheduled / on-demand |
| SKILL-008 | OdooSkill | Gold | Invoice/customer sync |
| SKILL-009 | CEOBriefingSkill | Gold | Weekly (Monday AM) |
| SKILL-010 | RalphLoop | Gold | Any multi-step autonomous task |

---

## 6. Error Recovery & Graceful Degradation

| Failure | Recovery |
|---------|----------|
| MCP server not found | Logs warning, skips action, continues cycle |
| API rate limit (Twitter) | Exponential backoff stored in `_backoff`, slept on next poll |
| OAuth token expired (Gmail) | Auto-refresh via `creds.refresh(Request())` |
| Odoo down | Returns "Odoo unavailable" string, CEO briefing still generates |
| Claude API unavailable | Template fallback for all AI-generated content |
| Ralph Loop step failure | Retry with Claude-generated correction → escalate after 3× |
| Watcher crash | Restart-safe (seen IDs persisted), no duplicate processing |

---

## 7. Security Design

- **No secrets in code** — all credentials in `.env` (gitignored)
- **OAuth2 tokens** — stored in `token.json` (gitignored), auto-refreshed
- **Approval gate** — payments >$100 and all external sends require human approval
- **Least privilege** — each MCP server requests minimum required API scopes
- **Audit trail** — every action logged to `Logs/` with timestamp and actor

---

## 8. Deployment Options

### Development (local)
```bash
python setup_gold.py --odoo-up
# Run each watcher in a separate terminal
python orchestrator.py
```

### Production (PM2)
```bash
pm2 start watchers/gmail_watcher.py --interpreter python --name gmail-watcher
pm2 start watchers/facebook_watcher.py --interpreter python --name fb-watcher
pm2 start watchers/twitter_watcher.py --interpreter python --name twitter-watcher
pm2 start orchestrator.py --interpreter python --name orchestrator
pm2 save && pm2 startup
```

---

## 9. Lessons Learned

1. **Dedup is critical** — without seen-ID files, every watcher restart reprocesses everything. JSON/text seen files are simpler and more reliable than database state.

2. **MCP stdio is fragile** — the JSON-RPC handshake must complete before any tool calls. Each call spawns a fresh subprocess to avoid zombie processes.

3. **Playwright sessions expire** — LinkedIn and WhatsApp require periodic re-authentication. The `--setup` flag handles this gracefully without code changes.

4. **Odoo JSON-RPC is simple but picky** — authentication returns a uid (integer). Every subsequent call must include database + uid + password. The `execute()` abstraction hides this complexity.

5. **Twitter rate limits are real** — the free tier allows 500k tweets/month read. A 90-second poll interval with `since_id` pagination stays safely within limits.

6. **Facebook + Instagram share one app** — one Facebook App covers both platforms. The Instagram account must be connected to the Facebook Page in Business Settings.

7. **The Ralph Loop needs a real executor** — the current implementation has a dry-run executor for safety. In production, wire it to the orchestrator's skill dispatch map.

8. **CEO briefing is the forcing function** — building the weekly briefing forced integration of all data sources (Odoo, social media, vault logs) into a single coherent picture.

---

---

## 10. OdooAccountingSkill — XML-RPC Design (Odoo 19+)

### Why XML-RPC over MCP subprocess?

The previous `odoo_skill.py` spawned a Node.js subprocess for every Odoo call.
`OdooAccountingSkill` (`skills/odoo_accounting_skill.py`) connects directly via
Python's stdlib `xmlrpc.client` — zero extra processes, lower latency, and full
type safety.

```
Python skill
  └── xmlrpc.client.ServerProxy
        ├── /xmlrpc/2/common  → authenticate() → uid (int)
        └── /xmlrpc/2/object  → execute_kw(db, uid, password, model, method, args, kwargs)
                                  ├── account.move   (invoices / bills)
                                  ├── res.partner    (customers / vendors)
                                  ├── project.task   (tasks)
                                  └── sale.order     (sale orders)
```

### Authentication flow

```python
uid = common.authenticate(db, username, password, {})
# uid is cached; every subsequent call uses it as the session token.
models.execute_kw(db, uid, password, "account.move", "search_read", [domain], {fields})
```

Odoo 19 does not break this API — the XML-RPC 2.0 endpoints are stable across
all Odoo versions from 8 to 19.

### Error recovery layers

| Layer | Mechanism |
|-------|-----------|
| `authenticate()` | Retries 3× with exponential backoff on network errors; auth faults fail fast |
| `_execute_kw()` | Raises exception; all callers wrap with `_handle_error()` → `OdooResult(False)` |
| `OdooResult` | Uniform return type — callers never need bare `try/except` |
| Audit log | Every call writes to `Logs/odoo_accounting_skill.log` with timestamp |

---

## 11. AutonomousLoop — Step Engine Design

`skills/autonomous_loop.py` implements the Gold Tier's fully autonomous
scenario engine. Unlike the original `ralph_loop.py` (generic goal decomposer),
`AutonomousLoop` ships with **hard-coded, production-tested scenarios** where
each step is a named Python method — traceable, testable, and independently
retried.

### Scenario: `weekly_sales_social_post`

```
┌───────────────────────────────────────────────────────┐
│              AutonomousLoop (run_id = timestamp)       │
│                                                        │
│  Step 1  odoo_authenticate   → OdooAccountingSkill    │
│  Step 2  odoo_weekly_audit   → account.move (7 days)  │
│  Step 3  generate_summary    → Claude sonnet-4-6       │
│  Step 4  craft_social_post   → Claude sonnet-4-6       │
│  Step 5  post_to_twitter     → twitter-mcp (stdio)     │
│  Step 6  post_to_facebook    → facebook-mcp (stdio)    │
│  Step 7  update_dashboard    → Dashboard.md            │
│                                                        │
│  On any step failure (3× retries exhausted):           │
│    → Pending_Approval/APPROVAL-<ts>-autonomous-<step> │
│    → Remaining steps continue (non-blocking)           │
│                                                        │
│  Final output:                                         │
│    → Briefings/AUTONOMOUS_<run_id>.md                 │
└───────────────────────────────────────────────────────┘
```

### Retry + backoff contract

```
attempt 1  → immediate
attempt 2  → sleep 2s
attempt 3  → sleep 4s
exhausted  → StepResult(success=False) → _escalate()
```

### Graceful degradation matrix

| Failure | Behaviour |
|---------|-----------|
| Odoo unreachable | Auth step fails → audit step skipped (context missing) → summary uses "N/A" template |
| Claude unavailable | `_template_summary()` + `_template_post()` substituted automatically |
| twitter-mcp missing | MCP call returns `success=False` → step escalated → Facebook step still runs |
| facebook-mcp missing | Same as Twitter — independent step |
| Dashboard.md missing | `_append_dashboard()` silently skips (no crash) |
| Report write fails | Logged; main result dict still returned to caller |

### Context dict (shared between steps)

```python
ctx = {
    "odoo_uid":       int,         # set by step 1
    "audit":          dict,        # set by step 2 (OdooResult.data)
    "summary":        str,         # set by step 3
    "social_post":    str,         # set by step 4
    "twitter_result": dict,        # set by step 5
    "facebook_result": dict,       # set by step 6
}
```

Steps read only what they need; missing keys trigger graceful fallback.

---

*Architecture Document — Gold Tier AI Employee | Building Autonomous FTEs in 2026*
