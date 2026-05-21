---
title: Gold Tier AI Employee
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 6.14.0
app_file: app.py
pinned: false
license: mit
---

# Gold Tier AI Employee

Autonomous business operations system built for the **"Building Autonomous FTEs in 2026"** hackathon.

## Features

- **LinkedIn Post Generator** — AI-powered posts using Claude (Haiku)
- **Vault Dashboard** — real-time folder and env-var status
- **Full orchestrator** (run locally) — watches Gmail, WhatsApp, LinkedIn, Facebook, Twitter/X, Instagram

## Quick Start (local)

```bash
git clone <repo>
cp .env.example .env   # fill in your API keys
python setup_gold.py   # install deps + MCP servers
python orchestrator.py # start autonomous loop
```

## HF Spaces

Add `ANTHROPIC_API_KEY` as a Space Secret to enable AI-generated posts.
