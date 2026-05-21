"""
app.py — Gold Tier AI Employee · Hugging Face Spaces Demo

Showcases the core AI capabilities without browser automation:
  - LinkedIn Post Generator (Claude-powered)
  - Orchestrator dry-run preview
  - System architecture overview
"""

from __future__ import annotations

import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import gradio as gr
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

try:
    import anthropic
    _ANTHROPIC_OK = True
except ImportError:
    _ANTHROPIC_OK = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent

POST_FORMATS = [
    "value_tip",
    "insight",
    "case_study",
    "question",
    "behind_scenes",
    "myth_bust",
]

FORMAT_DESCRIPTIONS = {
    "value_tip":      "Actionable numbered tips — great for saves and shares",
    "insight":        "Bold hot take or contrarian industry view",
    "case_study":     "Problem → Solution → Result story with a metric",
    "question":       "Engagement driver — ask something your audience debates",
    "behind_scenes":  "Personal story about how you work or a lesson learned",
    "myth_bust":      "Debunk a common misconception, replace with the truth",
}

FORMAT_INSTRUCTIONS = {
    "value_tip":     "Write a practical, actionable tip post. Start with a bold hook. Give 3-5 numbered tips. End with a CTA.",
    "insight":       "Share a contrarian insight or industry hot take. Be specific and bold. End with a thought-provoking question.",
    "case_study":    "Tell a short client success story. Use 'Problem → Solution → Result'. Include a specific metric.",
    "question":      "Ask ONE specific question your audience genuinely debates. Share your 2-sentence take. Invite comments.",
    "behind_scenes": "Share how you work, what you believe, or a lesson learned. Make it personal. End with a CTA.",
    "myth_bust":     "Name one myth your audience believes. Debunk it in 2-3 sentences. Give the truth. End with CTA.",
}

MODEL = "claude-haiku-4-5-20251001"

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "my_verify_token")

fastapi_app = FastAPI()


@fastapi_app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return PlainTextResponse(content=challenge)

    raise HTTPException(status_code=403, detail="Verification failed")

# ---------------------------------------------------------------------------
# Template fallback posts (no API key needed)
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, str] = {
    "value_tip": """\
3 things most business owners get wrong about AI automation:

1️⃣ They think it requires a big tech team.
One person + the right tools = 80% of repetitive work automated.

2️⃣ They wait until they're "big enough."
The best time to automate is when you're small — that's when it compounds the most.

3️⃣ They automate the wrong things first.
Start with what eats the most time, not what's easiest to automate.

{value_prop}

{cta}

#AIAutomation #Productivity #BusinessGrowth #SmallBusiness #AI""",

    "insight": """\
Hot take: most businesses don't have a growth problem.

They have a follow-up problem.

Leads come in. Proposals go out. And then... silence.

Not because the lead isn't interested.
Because life gets busy and no one follows up consistently.

The businesses winning right now all have one thing in common:
Systems that follow up automatically, professionally, and at the right time.

{value_prop}

What's your current follow-up process? Drop it in the comments 👇

#Sales #BusinessGrowth #Automation #B2B #LeadGeneration""",

    "case_study": """\
A client came to us drowning in manual work:

→ 8 hours/week on data entry
→ 3 hours/week on scheduling
→ Countless hours on follow-up emails

We automated all of it in 2 weeks.

Result: 11+ hours reclaimed every week — that's 1.5 full workdays back.

They reinvested that time into sales calls.
Revenue went up 30% in 90 days.

The automation paid for itself in week one.

{cta}

#CaseStudy #ROI #Automation #BusinessGrowth #AI""",

    "question": """\
Quick question for founders and business owners:

What's the ONE task in your business that, if automated, would change everything?

For most people I talk to — it's follow-up.
For others it's reporting. Or onboarding. Or scheduling.

Whatever yours is, there's a 90% chance it can be automated this week with the right tool.

What's yours? Comment below 👇

#Automation #Productivity #BusinessOwner #AI""",

    "behind_scenes": """\
Here's how we actually start every client engagement:

We don't touch any tools for the first 48 hours.

We just talk. We ask: what does your day look like? Where does time disappear?

Most founders can't answer that question accurately until they're asked directly.

Then we audit the top 3 time drains.
Then we automate the highest-value one first.

Simple. Repeatable. Works every time.

{cta}

#BehindTheScenes #BusinessStrategy #Automation #Consulting""",

    "myth_bust": """\
Myth: You need a developer to automate your business.

Reality: 90% of small business automation requires zero code.

Tools like Make, Zapier, and AI assistants now handle what used to take months of custom development — in hours.

The bottleneck isn't technical skill.
It's knowing WHAT to automate.

That's exactly what we help with.

{cta}

#Automation #NoCode #SmallBusiness #BusinessGrowth #AI""",
}

# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

def _template_post(fmt: str, value_prop: str, cta: str) -> dict:
    template = TEMPLATES.get(fmt, TEMPLATES["value_tip"])
    content = template.format(
        value_prop=value_prop or "We help businesses scale with AI automation.",
        cta=cta or "DM me 'AUTOMATE' for a free audit.",
    )
    return {
        "content": content,
        "post_type": fmt,
        "char_count": len(content),
        "hashtags": re.findall(r'#\w+', content),
        "approval_needed": False,
        "notes": "Template post — add an Anthropic API key for AI-generated content.",
    }


def generate_post(
    api_key: str,
    company_name: str,
    target_audience: str,
    value_prop: str,
    cta: str,
    extra_context: str,
    post_format: str,
) -> tuple[str, str, str]:
    """Return (post_content, status_badge, meta_info)."""

    resolved_key = api_key.strip() or os.environ.get("ANTHROPIC_API_KEY", "")
    fmt = post_format if post_format in POST_FORMATS else random.choice(POST_FORMATS)

    if not resolved_key or not _ANTHROPIC_OK:
        result = _template_post(fmt, value_prop, cta)
        status = "📝 Template post (add Anthropic API key for AI-generated content)"
        meta = f"**Format:** {fmt}  |  **Characters:** {result['char_count']}\n\n> No API key provided — showing template fallback."
        return result["content"], status, meta

    client = anthropic.Anthropic(api_key=resolved_key)
    now = datetime.now(timezone.utc)

    business_context = f"""Company: {company_name or '[Your Company]'}
Target Audience: {target_audience or 'Business owners and founders'}
Value Proposition: {value_prop or 'We help businesses automate and scale.'}
Call-to-Action: {cta or 'DM me "AUTOMATE" for a free audit.'}
Additional Context: {extra_context or 'N/A'}"""

    system_prompt = f"""You are a LinkedIn content strategist for a business owner.
Write ONE high-quality LinkedIn post that attracts ideal clients and generates inbound leads.

BUSINESS CONTEXT:
{business_context}

POST FORMAT: {fmt}
FORMAT INSTRUCTIONS: {FORMAT_INSTRUCTIONS[fmt]}

LINKEDIN BEST PRACTICES:
- First line (hook) must stop the scroll — bold claim, surprising stat, or direct question
- Use line breaks generously — short paragraphs (1-3 lines max)
- No walls of text; white space is your friend
- Include 3-5 relevant hashtags at the end
- Ideal length: 800–1300 characters
- One clear CTA (call-to-action) at the end
- Never start with "I" — use a hook instead
- Write in first person as the business owner
- Make it feel human, not AI-generated

OUTPUT FORMAT — return ONLY this JSON (no markdown fences):
{{
  "hook": "The very first line of the post",
  "content": "Full post text with \\n for line breaks. Include hashtags at end.",
  "hashtags": ["#Tag1", "#Tag2", "#Tag3"],
  "cta": "The call-to-action line",
  "notes": "Brief note about why this post will work"
}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"Write a LinkedIn post for today ({now.strftime('%A, %B %d')}). Format: {fmt}.",
            }],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)

        data = json.loads(raw)
        content = data.get("content", "")

        price_hit = bool(re.search(r'(?:USD?|\$)\s*[0-9]|[0-9]+\s*dollars?', content, re.IGNORECASE))
        guarantee_hit = bool(re.search(r'\b(guarantee|promised|refund|money.?back|risk.?free)\b', content, re.IGNORECASE))
        approval_needed = price_hit or guarantee_hit

        status = "⚠️ Needs approval (pricing/guarantee detected)" if approval_needed else "✅ Ready to post"
        hashtags_str = "  ".join(data.get("hashtags", []))
        notes = data.get("notes", "")
        meta = (
            f"**Format:** {fmt}  |  **Characters:** {len(content)}\n\n"
            f"**Hashtags:** {hashtags_str}\n\n"
            f"**Notes:** {notes}"
        )
        return content, status, meta

    except json.JSONDecodeError:
        result = _template_post(fmt, value_prop, cta)
        return result["content"], "⚠️ Claude returned unexpected format — showing template", f"**Format:** {fmt}"
    except Exception as e:
        error_msg = str(e)[:120]
        return "", f"❌ Error: {error_msg}", f"**Format:** {fmt}"


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def get_vault_status() -> str:
    folders = {
        "Inbox": ROOT / "Inbox",
        "Needs Action": ROOT / "Needs_Action",
        "Pending Approval": ROOT / "Pending_Approval",
        "Approved": ROOT / "Approved",
        "Done": ROOT / "Done",
        "Rejected": ROOT / "Rejected",
        "Plans": ROOT / "Plans",
        "Briefings": ROOT / "Briefings",
    }

    rows = []
    for name, path in folders.items():
        if path.exists():
            count = len(list(path.glob("*.md")))
            icon = "🔴" if (name in ("Needs Action", "Pending Approval") and count > 0) else "🟢"
            rows.append(f"| {icon} **{name}** | {count} files |")
        else:
            rows.append(f"| ⚪ {name} | — |")

    env_vars = {
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "CEO_EMAIL": bool(os.environ.get("CEO_EMAIL")),
        "FB_PAGE_ACCESS_TOKEN": bool(os.environ.get("FB_PAGE_ACCESS_TOKEN")),
        "TWITTER_BEARER_TOKEN": bool(os.environ.get("TWITTER_BEARER_TOKEN")),
        "ODOO_URL": bool(os.environ.get("ODOO_URL")),
    }

    env_rows = [
        f"| {'✅' if ok else '❌'} `{var}` | {'Set' if ok else 'Not set'} |"
        for var, ok in env_vars.items()
    ]

    return f"""## Vault Folders

| Folder | Items |
|--------|-------|
{chr(10).join(rows)}

## Environment Variables

| Status | Variable | Value |
|--------|----------|-------|
{chr(10).join(env_rows)}

---
*Refresh to update counts.*"""


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

HEADER = """
# 🤖 Gold Tier AI Employee
### Autonomous Business Operations — Hackathon Demo

Built for the **"Building Autonomous FTEs in 2026"** hackathon.
This demo showcases the AI-powered LinkedIn post generation engine.

---
"""

ABOUT_TEXT = """
## What Is This?

The **Gold Tier AI Employee** is a fully autonomous business operations system that:

- 📧 **Watches Gmail, WhatsApp, LinkedIn, Facebook, Twitter, Instagram** for incoming messages
- 🧠 **Routes them intelligently** — safe tasks go straight to planning, sensitive ones need approval
- ✅ **Executes approved actions** — sends emails, posts content, updates CRM (Odoo)
- 📊 **Generates weekly CEO briefings** combining all activity into one summary
- 💼 **Posts to LinkedIn automatically** using AI-generated, strategically timed content

## Architecture

```
Watchers (Python)
  └── Gmail, WhatsApp, LinkedIn, Facebook, Instagram, Twitter
        │
        ▼
  Needs_Action/ (vault folder)
        │
        ▼
  Orchestrator (orchestrator.py)
   ├── SKILL-001: PlanSkill       → Plans/
   ├── SKILL-004: ApprovalSkill   → Pending_Approval/
   ├── SKILL-005: LinkedInPostSkill
   ├── SKILL-008: OdooSkill       → CRM sync
   ├── SKILL-009: CEOBriefingSkill → Briefings/
   └── SKILL-010: RalphLoop       → autonomous multi-step tasks
        │
        ▼
  MCP Servers (Node.js)
   ├── email-mcp      → Gmail API
   ├── odoo-mcp       → Odoo JSON-RPC
   ├── facebook-mcp   → Facebook/Instagram Graph API
   └── twitter-mcp    → Twitter API v2
```

## Tech Stack

| Layer | Tech |
|-------|------|
| AI Model | Claude (Anthropic) — Haiku for speed, Sonnet for quality |
| Orchestration | Python 3.13 + asyncio |
| Browser automation | Playwright + Chromium |
| CRM | Odoo 17 Community (Docker) |
| Social APIs | Facebook Graph API, Twitter API v2 |
| Email | Gmail OAuth2 via MCP |
| UI (this demo) | Gradio on Hugging Face Spaces |

## Running Locally

```bash
git clone <repo>
cp .env.example .env   # fill in your API keys
python setup_gold.py   # install all deps + MCP servers
python orchestrator.py # start the main loop
```
"""

with gr.Blocks(title="Gold Tier AI Employee") as demo:

    gr.Markdown(HEADER)

    with gr.Tabs():

        # ------------------------------------------------------------------
        # Tab 1: LinkedIn Post Generator
        # ------------------------------------------------------------------
        with gr.Tab("✍️ LinkedIn Post Generator"):
            gr.Markdown("### Generate AI-powered LinkedIn posts that attract your ideal clients")

            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("#### Business Details")

                    company_name = gr.Textbox(
                        label="Company Name",
                        placeholder="e.g., Acme AI Solutions",
                    )
                    target_audience = gr.Textbox(
                        label="Target Audience",
                        placeholder="e.g., SaaS founders, CTOs, Operations managers",
                    )
                    value_prop = gr.Textbox(
                        label="Value Proposition",
                        placeholder="e.g., We help SaaS startups cut cloud costs by 40%",
                    )
                    cta_input = gr.Textbox(
                        label="Call to Action",
                        placeholder="e.g., DM me 'AUTOMATE' for a free audit",
                    )
                    extra_context = gr.Textbox(
                        label="Additional Context (optional)",
                        placeholder="Recent wins, content themes, tone preference…",
                        lines=3,
                    )

                    gr.Markdown("#### Post Settings")
                    post_format = gr.Dropdown(
                        choices=POST_FORMATS,
                        value="value_tip",
                        label="Post Format",
                        info="",
                    )
                    for fmt in POST_FORMATS:
                        pass

                    api_key_input = gr.Textbox(
                        label="Anthropic API Key (optional)",
                        placeholder="sk-ant-... (or set via HF Secret ANTHROPIC_API_KEY)",
                        type="password",
                        info="Leave blank to use a template post. Set the HF Secret for persistent AI generation.",
                    )

                    generate_btn = gr.Button("Generate Post", variant="primary", size="lg")

                with gr.Column(scale=2):
                    gr.Markdown("#### Generated Post")
                    post_output = gr.Textbox(
                        label="Post Content",
                        lines=20,
                        interactive=True,
                    )
                    status_output = gr.Markdown("*Click 'Generate Post' to create content.*")
                    meta_output = gr.Markdown("")

            gr.Markdown("---")
            gr.Markdown(
                "**Post formats:** " +
                " | ".join(f"`{k}` — {v}" for k, v in FORMAT_DESCRIPTIONS.items())
            )

            generate_btn.click(
                fn=generate_post,
                inputs=[api_key_input, company_name, target_audience, value_prop, cta_input, extra_context, post_format],
                outputs=[post_output, status_output, meta_output],
            )

        # ------------------------------------------------------------------
        # Tab 2: Vault Dashboard
        # ------------------------------------------------------------------
        with gr.Tab("📊 Vault Dashboard"):
            gr.Markdown("### Current vault state — folder counts and environment status")

            refresh_btn = gr.Button("Refresh Status", variant="secondary")
            dashboard_md = gr.Markdown(get_vault_status())

            refresh_btn.click(fn=get_vault_status, outputs=dashboard_md)

            gr.Markdown("""
---
### Orchestrator Dry-Run Output

The orchestrator scans `Needs_Action/`, routes items to `Plans/` or `Pending_Approval/`,
then executes anything in `Approved/` via MCP tools.

Run locally:
```bash
python orchestrator.py --dry-run --once
```
""")

        # ------------------------------------------------------------------
        # Tab 3: About
        # ------------------------------------------------------------------
        with gr.Tab("ℹ️ About"):
            gr.Markdown(ABOUT_TEXT)

app = gr.mount_gradio_app(fastapi_app, demo, path="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
