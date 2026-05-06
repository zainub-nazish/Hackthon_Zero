"""
LinkedInPostSkill — SKILL-005
Reads Business_Goals.md + Dashboard.md and uses Claude API to generate
an engaging, sales-lead-generating LinkedIn post.

Post strategy rotates across 6 formats to avoid repetition:
  1. value_tip      — actionable tip for the target audience
  2. insight        — industry observation or hot take
  3. case_study     — client win / social proof story
  4. question       — engagement driver with a specific question
  5. behind_scenes  — how we work / what we believe
  6. myth_bust      — common misconception debunked

Claude returns structured JSON so the post can be inspected/edited
before publishing. Approval flag is set when post mentions
specific pricing or makes financial promises.

Fallback: if ANTHROPIC_API_KEY not set, returns a template post
drawn from Business_Goals.md content.

Usage:
    from skills.linkedin_post_skill import LinkedInPostSkill

    skill = LinkedInPostSkill(vault_root)
    result = skill.generate()
    # result = {
    #   "content":         "Full post text with line breaks",
    #   "hashtags":        ["#AI", "#Productivity"],
    #   "post_type":       "value_tip",
    #   "hook":            "First line of the post",
    #   "cta":             "Call-to-action line",
    #   "approval_needed": False,
    #   "approval_reason": "",
    #   "char_count":      280,
    # }
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("LinkedInPostSkill")

try:
    import anthropic as _anthropic_module
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# ---------------------------------------------------------------------------
# Post format rotation
# ---------------------------------------------------------------------------
POST_FORMATS = [
    "value_tip",
    "insight",
    "case_study",
    "question",
    "behind_scenes",
    "myth_bust",
]

FORMAT_INSTRUCTIONS = {
    "value_tip":      "Write a practical, actionable tip post. Start with a bold hook. Give 3-5 numbered tips. End with a CTA.",
    "insight":        "Share a contrarian insight or hot take about the industry. Be specific and bold. End with a thought-provoking question.",
    "case_study":     "Tell a short client success story (even if hypothetical/anonymized). Use the 'Problem → Solution → Result' format. Include a specific metric.",
    "question":       "Ask a single, specific question your target audience genuinely debates. Briefly share your take (2-3 sentences). Invite comments.",
    "behind_scenes":  "Share something about how you work, what you believe, or a lesson learned. Make it personal and genuine. End with a CTA.",
    "myth_bust":      "Identify one myth your target audience believes. Explain why it's wrong in 2-3 sentences. Replace it with the truth. CTA at end.",
}

# ---------------------------------------------------------------------------
# LinkedInPostSkill
# ---------------------------------------------------------------------------

class LinkedInPostSkill:
    """
    SKILL-005 — LinkedIn post content generator powered by Claude.
    """

    MODEL      = "claude-haiku-4-5-20251001"
    MAX_TOKENS = 1024
    # LinkedIn post limit: 3000 chars; ideal engagement range: 900-1300
    IDEAL_MIN  = 800
    IDEAL_MAX  = 1300

    def __init__(self, vault_root: Path) -> None:
        self.vault_root    = Path(vault_root)
        self.logs_dir      = self.vault_root / "Logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self._goals    = self._load_file("Business_Goals.md")
        self._dashboard = self._load_file("Dashboard.md")
        self._handbook  = self._load_file("Company_Handbook.md")
        self._post_log  = self.logs_dir / "linkedin_posts.log"

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = None
        if _ANTHROPIC_AVAILABLE and api_key:
            self._client = _anthropic_module.Anthropic(api_key=api_key)
            logger.info("Claude API ready (model: %s).", self.MODEL)
        else:
            logger.warning("ANTHROPIC_API_KEY not set — using template fallback.")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate(self, force_format: str | None = None) -> dict:
        """
        Generate a LinkedIn post.

        Args:
            force_format: one of POST_FORMATS, or None to auto-rotate

        Returns dict with keys:
            content, hashtags, post_type, hook, cta,
            approval_needed, approval_reason, char_count
        """
        fmt = force_format if force_format in POST_FORMATS else self._next_format()
        logger.info("Generating '%s' post…", fmt)

        if self._client:
            result = self._claude_generate(fmt)
        else:
            result = self._template_generate(fmt)

        # Check approval requirement
        result = self._check_approval(result)

        # Log
        self._log_post(result)
        logger.info(
            "Post generated: type=%s | chars=%d | approval=%s",
            result["post_type"], result["char_count"], result["approval_needed"],
        )
        return result

    # ------------------------------------------------------------------
    # Format rotation — reads last used format from log
    # ------------------------------------------------------------------

    def _next_format(self) -> str:
        """Pick the format least recently used (simple rotation via log)."""
        if self._post_log.exists():
            try:
                lines = self._post_log.read_text(encoding="utf-8").splitlines()
                used_formats = []
                for line in reversed(lines[-20:]):
                    m = re.search(r'format=(\w+)', line)
                    if m:
                        used_formats.append(m.group(1))
                        if len(used_formats) >= len(POST_FORMATS):
                            break
                # Pick first format not in recent usage
                for fmt in POST_FORMATS:
                    if fmt not in used_formats:
                        return fmt
            except Exception:
                pass
        return random.choice(POST_FORMATS)

    # ------------------------------------------------------------------
    # Claude generation
    # ------------------------------------------------------------------

    def _claude_generate(self, fmt: str) -> dict:
        now = datetime.now(timezone.utc)

        system = f"""You are a LinkedIn content strategist for a business owner.
Your job: write ONE high-quality LinkedIn post that attracts ideal clients and generates inbound leads.

BUSINESS CONTEXT:
{self._goals[:2500]}

CURRENT DASHBOARD / RECENT ACTIVITY:
{self._dashboard[:800]}

COMMUNICATION RULES (Company Handbook):
{self._handbook[:600]}

POST FORMAT THIS TIME: {fmt}
FORMAT INSTRUCTIONS: {FORMAT_INSTRUCTIONS[fmt]}

LINKEDIN POST BEST PRACTICES:
- First line (hook) must stop the scroll — bold claim, surprising stat, or direct question
- Use line breaks generously — short paragraphs (1-3 lines max)
- No walls of text; white space is your friend
- Include 3-5 relevant hashtags at the end
- Ideal length: {self.IDEAL_MIN}–{self.IDEAL_MAX} characters
- One clear CTA (call-to-action) at the end
- Never start with "I" — use a hook instead
- Write in first person as the business owner
- Make it feel human, not AI-generated

OUTPUT FORMAT — return ONLY this JSON (no markdown fences):
{{
  "hook": "The very first line of the post (make it scroll-stopping)",
  "content": "Full post text with \\n for line breaks. Include hashtags at end.",
  "hashtags": ["#Tag1", "#Tag2", "#Tag3"],
  "cta": "The call-to-action line",
  "post_type": "{fmt}",
  "notes": "Any brief note about why this post will work"
}}"""

        user = f"""Write a LinkedIn post for today ({now.strftime('%A, %B %d')}).
Format: {fmt}
Make it genuinely helpful and sales-lead-generating."""

        try:
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)

            data = json.loads(raw)
            content = data.get("content", "")
            return {
                "content":         content,
                "hashtags":        data.get("hashtags", []),
                "post_type":       fmt,
                "hook":            data.get("hook", content.split("\n")[0]),
                "cta":             data.get("cta", ""),
                "notes":           data.get("notes", ""),
                "approval_needed": False,
                "approval_reason": "",
                "char_count":      len(content),
            }

        except json.JSONDecodeError as e:
            logger.warning("Claude returned invalid JSON: %s — using fallback.", e)
            return self._template_generate(fmt)
        except Exception as e:
            logger.error("Claude API error: %s — using fallback.", e)
            return self._template_generate(fmt)

    # ------------------------------------------------------------------
    # Template fallback
    # ------------------------------------------------------------------

    def _template_generate(self, fmt: str) -> str:
        """Generate a template-based post when Claude is unavailable."""
        now = datetime.now(timezone.utc)

        # Pull snippets from Business_Goals.md
        pitch = self._extract_field(self._goals, "One-line pitch", "We help businesses grow with AI.")
        audience = self._extract_field(self._goals, "Role/Title", "business owners and founders")
        cta_text = self._extract_first_cta(self._goals)

        templates = {
            "value_tip": f"""\
3 things most {audience} get wrong about automation:

1. They think it requires a big team to implement.
It doesn't. One person with the right tools can automate 80% of repetitive work.

2. They wait until they're "big enough."
The best time to automate is when you're small — that's when it compounds the most.

3. They automate the wrong things first.
Start with what eats the most time, not what's easiest.

{pitch}

{cta_text}

#Automation #Productivity #BusinessGrowth #SmallBusiness #AI""",

            "insight": f"""\
Hot take: most businesses don't have a growth problem.

They have a follow-up problem.

Leads come in. Proposals go out. And then... silence.

Not because the lead isn't interested — but because life gets busy and no one follows up consistently.

The businesses winning right now have one thing in common:
Systems that follow up automatically, professionally, and at the right time.

{pitch}

What's your current follow-up process? Drop it in the comments.

#Sales #BusinessGrowth #Automation #B2B""",

            "case_study": f"""\
A client came to us drowning in manual work.

8 hours/week just on data entry.
3 hours/week on scheduling.
Countless hours on follow-up emails.

We automated all of it in 2 weeks.

Result: They reclaimed 11+ hours every week — that's nearly 1.5 full workdays back.

They reinvested that time into sales calls. Revenue went up 30% in 90 days.

The automation paid for itself in week 1.

{cta_text}

#CaseStudy #Automation #ROI #BusinessGrowth""",

            "question": f"""\
Quick question for {audience}:

What's the ONE task in your business that, if automated, would change everything?

For most people I talk to, it's follow-up.

For others it's reporting. Or onboarding. Or scheduling.

Whatever yours is — there's a 90% chance it can be automated this week.

What's yours? Comment below.

#Automation #Productivity #BusinessOwner""",

            "behind_scenes": f"""\
Here's how we actually start every client engagement:

Step 1: We don't touch any tools for the first 48 hours.

We just talk. We ask: what does your day look like? Where does time disappear?

Most founders can't answer that question accurately until they're asked directly.

Step 2: We audit the top 3 time drains.

Step 3: We automate the highest-value one first.

Simple. Repeatable. It works every time.

{cta_text}

#BehindTheScenes #BusinessStrategy #Automation""",

            "myth_bust": f"""\
Myth: You need a developer to automate your business.

Reality: 90% of small business automation requires zero code.

Tools like Make, Zapier, and AI assistants now handle what used to take months of custom development — in hours.

The bottleneck isn't technical skill. It's knowing WHAT to automate.

That's exactly what we help with.

{cta_text}

#Automation #NoCode #SmallBusiness #BusinessGrowth""",
        }

        content = templates.get(fmt, templates["value_tip"])
        return {
            "content":         content,
            "hashtags":        re.findall(r'#\w+', content),
            "post_type":       fmt,
            "hook":            content.split("\n")[0],
            "cta":             cta_text,
            "notes":           "Template fallback — set ANTHROPIC_API_KEY for AI-generated posts.",
            "approval_needed": False,
            "approval_reason": "",
            "char_count":      len(content),
        }

    # ------------------------------------------------------------------
    # Approval check
    # ------------------------------------------------------------------

    _PRICE_RE = re.compile(
        r'(?:USD?|\$)\s*[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?'
        r'|[0-9]+\s*(?:dollars?|USD)',
        re.IGNORECASE,
    )
    _GUARANTEE_RE = re.compile(
        r'\b(guarantee|guaranteed|promise|refund|money.?back|risk.?free)\b',
        re.IGNORECASE,
    )

    def _check_approval(self, result: dict) -> dict:
        """Flag post for approval if it contains pricing or guarantees."""
        content = result.get("content", "")

        if self._PRICE_RE.search(content):
            result["approval_needed"] = True
            result["approval_reason"] = "Post contains specific pricing — requires human review before publishing."
        elif self._GUARANTEE_RE.search(content):
            result["approval_needed"] = True
            result["approval_reason"] = "Post contains guarantee/refund claim — requires human review."

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_file(self, filename: str) -> str:
        path = self.vault_root / filename
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Could not read %s", filename)
            return ""

    def _extract_field(self, text: str, field: str, default: str) -> str:
        m = re.search(rf'\*\*{re.escape(field)}[:\*].*?\*\*\s*(.+)', text)
        if m:
            return m.group(1).strip().strip('[]')
        # Try plain text variant
        m2 = re.search(rf'{re.escape(field)}[:\s]+(.+)', text, re.IGNORECASE)
        if m2:
            v = m2.group(1).strip().strip('[]')
            if v and '[' not in v:
                return v
        return default

    def _extract_first_cta(self, text: str) -> str:
        m = re.search(r'CTA \d[^\n]*\n[>\s]*(.+)', text)
        if m:
            v = m.group(1).strip().strip('"[]')
            if v and '[' not in v:
                return v
        return "Follow me for daily tips. DM 'AUTOMATE' to chat."

    def _log_post(self, result: dict) -> None:
        now = datetime.now(timezone.utc)
        try:
            with self._post_log.open("a", encoding="utf-8") as f:
                f.write(
                    f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] "
                    f"format={result['post_type']} | "
                    f"chars={result['char_count']} | "
                    f"approval={result['approval_needed']}\n"
                )
        except OSError:
            pass
