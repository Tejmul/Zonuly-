# JobHunter — AI Job-Scraping & Referral Outreach Agent

## Context

The user is a 4th-year student targeting high-paying AI Engineer / SDE roles (₹24–60+ LPA, India + global remote). Manual job hunting misses the long tail of well-paying startups (1by0, MStack-type companies). This project builds a **multi-agent pipeline** that: scrapes jobs from many sources, scores each against the user's resume for shortlist probability, discovers contactable people (recruiters + engineers) at high-match companies, drafts personalized referral/cold emails, and tracks the whole funnel (sent → replied → positive/negative) with notifications.

**Constraints chosen by user:**
- **Free-tier only** for data APIs (no paid Apollo/SerpAPI plans)
- **Review queue** — agent drafts emails, user approves before sending (daily cap ~25/day for Gmail deliverability)
- **Web dashboard** UI
- **Local open-source LLM** on MacBook M2 Pro via Ollama

## LLM Choice (local)

> **Updated after environment check:** this Mac has **8 GB RAM**, so Qwen3-14B/8B won't fit comfortably.

- **Primary model: Qwen3-4B** via Ollama (`ollama pull qwen3:4b`, ~2.6 GB) — the best open-weight model that runs well in 8 GB RAM; good structured JSON output (scoring/classification) and solid email prose (the review queue catches any weak drafts). Model name lives in `config.yaml` — swap to `qwen3:8b`/`qwen3:14b` on a bigger machine, or a cloud API later, with one line.
- **Embeddings: `nomic-embed-text`** via Ollama — for resume↔job-description semantic matching (fast, free, local).
- All agent calls go through one thin `llm.py` client (Ollama HTTP API, JSON-mode for structured tasks) so the model can be swapped later (including to a cloud API) with one config change.

## Tech Stack

- **Python 3.12 + uv** (package mgmt), **SQLite + SQLModel** (SQLAlchemy ORM)
  - *Why SQLite over Postgres:* it's a full relational DB (FKs, joins, indexes) and this is a single-user, single-machine tool with a few thousand rows — Postgres pays off with concurrent writers/multi-user/huge data, none of which apply, and a Postgres server would eat RAM we need for Ollama. Because we use SQLModel/SQLAlchemy, migrating to Postgres later = changing one connection string, zero code changes.
  - *Why not Prisma:* Prisma is TypeScript-native; the data layer lives in the Python pipeline (user's choice: Python pipeline + Next.js UI), and the dashboard reads everything through the FastAPI REST API, never the DB directly — so a TS ORM has no place to plug in.
- **Scraping:** `httpx` for APIs/JSON endpoints, **Playwright** for JS-heavy boards
- **Backend API:** **FastAPI + uvicorn** — exposes jobs/contacts/emails/replies + actions (approve, send, rescore) as REST endpoints consumed by the dashboard
- **Dashboard:** **Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui** — polished multi-section dashboard: Overview (funnel metrics), Leads, Job detail, Contacts, Review Queue, Sent Tracker, Replies, Settings
- **Email:** **Gmail API** (OAuth, free) — send from user's account, poll for replies via thread IDs
- **Scheduling:** APScheduler (daily scrape + hourly reply-poll while the API server runs)
- **Notifications:** macOS native notifications (`osascript`) + a "New" section in the dashboard; optional free Telegram bot later

## Data Sources (all free)

**Tier 1 — structured/free APIs (reliable, no scraping fragility):**
- **Greenhouse / Lever / Ashby public job-board JSON APIs** — thousands of startups (incl. most YC/funded startups) expose jobs at `boards-api.greenhouse.io/v1/boards/{co}/jobs`, `api.lever.co/v0/postings/{co}`, Ashby's public API. We maintain a growing `companies.yaml` seed list (curated: well-funded AI startups, YC companies, known high-payers) and auto-discover more from job aggregators.
- **Hacker News "Who is Hiring"** monthly threads (Algolia API) — goldmine for high-paying remote roles
- **RemoteOK API** + **WeWorkRemotely RSS** — remote global roles with salary tags
- **YC Work at a Startup** (public JSON endpoints)

**Tier 2 — Playwright scrapers (India high-CTC boards):**
- **Wellfound (AngelList)**, **Cutshort**, **Instahyre** — these display salary ranges, critical for the ₹24–60 LPA filter

**Explicitly out (and why):** logged-in LinkedIn automation — near-certain account ban and blocks the referral strategy itself. LinkedIn job data comes indirectly (public guest job pages only, best-effort), and people-finding uses the sources below instead.

## Contact Discovery (free-tier strategy)

For each high-match company, find up to ~20 relevant people (AI engineers, SWEs, recruiters):
1. **GitHub org mining** (free API): list org members/top contributors → many engineers expose real emails in commit metadata (`.patch` files) or profiles. Best free source of *verified* engineer emails.
2. **Company website scrape:** team/about pages, careers page recruiter emails
3. **Hunter.io free tier** (25 searches/mo) — spend only on the top-scored companies to learn the company's email pattern (`first.last@co.com`)
4. **Pattern guessing + verification:** generate candidate emails from known names + learned/company-common patterns, verify via MX lookup + SMTP RCPT check (no email actually sent)
5. Each contact stored with `source` + `confidence` (verified / pattern-guessed / scraped) — the dashboard shows confidence so the user prioritizes verified ones

## Pipeline (agents)

```
[Scraper fleet] → normalize/dedup → [Salary extractor (LLM)] → jobs DB
      ↓
[Match scorer]: embeddings prefilter → Qwen3 rubric scoring vs resume
   → shortlist_probability (0–100) + reasons + skill gaps
      ↓ (score ≥ threshold → notify user)
[Contact finder]: GitHub/site/Hunter/pattern per company → contacts DB
      ↓
[Email drafter]: researches the person (GitHub repos, company product)
   → personalized referral-ask draft ("Hey Suresh, saw your work on X…")
   → REVIEW QUEUE in dashboard (edit/approve/reject)
      ↓ approve
[Sender]: Gmail API, max 25/day, staggered; logs thread ID
      ↓
[Reply tracker]: polls Gmail threads → Qwen3 classifies reply
   → POSITIVE / NEGATIVE / CLOSED / NEUTRAL → notification + funnel board
      ↓
[Follow-up]: one polite follow-up auto-drafted after 5 days of silence (also review-queued)
```

## Project Structure

```
Job-Scrapy/
├── pyproject.toml
├── config.yaml              # thresholds, caps, model name, salary range
├── companies.yaml           # seed list of target companies (curated + auto-grown)
├── profile/
│   └── resume.pdf|md        # user drops resume here; parsed into profile.json
├── jobhunter/
│   ├── db.py                # SQLModel models: Company, Job, Contact, Email, Reply
│   ├── llm.py               # Ollama client (chat + JSON mode + embeddings)
│   ├── scrapers/            # one module per source, common Job schema
│   │   ├── greenhouse.py, lever.py, ashby.py
│   │   ├── hn_hiring.py, remoteok.py, wwr.py, yc.py
│   │   └── wellfound.py, cutshort.py, instahyre.py   (Playwright)
│   ├── matcher.py           # embeddings prefilter + LLM rubric scoring
│   ├── contacts/
│   │   ├── github_miner.py, site_scraper.py, hunter.py, patterns.py, verify.py
│   ├── outreach/
│   │   ├── researcher.py    # per-person context gathering
│   │   ├── drafter.py       # email generation (templates + LLM personalization)
│   │   ├── sender.py        # Gmail API send w/ caps
│   │   └── tracker.py       # reply polling + classification
│   ├── notify.py            # macOS notifications
│   ├── scheduler.py         # APScheduler jobs
│   └── api.py               # FastAPI: REST endpoints for the dashboard + action routes
├── dashboard/               # Next.js 15 + TypeScript + Tailwind + shadcn/ui
│   ├── app/
│   │   ├── page.tsx         # Overview: funnel metrics, new high-matches, recent replies
│   │   ├── leads/           # Leads table (sort/filter by score, salary, source) + job detail
│   │   ├── contacts/        # Contacts per company w/ confidence badges
│   │   ├── queue/           # Review Queue: edit/approve/reject drafts
│   │   ├── tracker/         # Sent Tracker matrix: company × contacted × when × status
│   │   ├── replies/         # Replies: Positive | Negative/Closed | Neutral
│   │   └── settings/        # config editing (thresholds, caps, identity)
│   ├── components/          # shared UI (tables, badges, cards, charts)
│   └── lib/api.ts           # typed client for the FastAPI backend
└── scripts/
    └── run.py               # CLI entry: scrape / score / find-contacts / serve (API + scheduler)
```

## Build Phases

**Phase 1 — Foundation + Job Ingestion**
1. Scaffold project (uv, SQLModel schema, config, Ollama client with model auto-detect 14B/8B)
2. Resume ingestion: parse PDF/MD → structured `profile.json` (skills, projects, experience) via LLM
3. Tier-1 scrapers (Greenhouse, Lever, Ashby, HN, RemoteOK, WWR, YC) + seed `companies.yaml` (~100 curated companies: funded AI startups, YC, known Indian high-payers)
4. Normalizer + dedup + LLM salary extraction (handles "₹25-40 LPA", "$120k", "competitive")

**Phase 2 — Matching + Dashboard v1**
5. Matcher: embed resume + JDs, cosine prefilter, then Qwen3 rubric scoring (skills overlap, YOE fit, fresher-friendliness, salary fit) → probability + reasons + gaps
6. FastAPI backend (`jobhunter/api.py`) + Next.js dashboard scaffold: Overview + Leads table (sortable by score/salary), job detail view, "New high-match" section + macOS notification

**Phase 3 — Contact Discovery**
7. GitHub miner, site scraper, Hunter free-tier integration, pattern guess + SMTP verify
8. Contacts tab in dashboard with confidence badges

**Phase 4 — Outreach Engine**
9. Person researcher + email drafter (referral-ask template, warm tone, references the person's actual work + user's matching projects)
10. Review Queue tab: edit/approve/reject drafts
11. Gmail OAuth + sender with 25/day cap + stagger; Sent Tracker tab (the "matrix": company × contacted? × when × status)

**Phase 5 — Reply Loop + Automation**
12. Reply tracker: Gmail thread polling → LLM classification → Replies tab split into Positive / Negative-Closed / Neutral + notifications
13. Follow-up drafter (5-day silence → queued follow-up)
14. Scheduler wiring: daily scrape+score, hourly reply poll
15. Playwright scrapers for Wellfound/Cutshort/Instahyre (last — most fragile part, core loop works without them)

## Guardrails (protect the user's accounts & reputation)

- Gmail: hard cap 25 emails/day, randomized send times, plain-text, one follow-up max — avoids spam flagging
- Scrapers: rate-limited, cached, polite headers; no logged-in LinkedIn automation
- SMTP verification does RCPT-check only, never sends
- Every outbound email passes human review (chosen mode)

## Verification

- `python scripts/run.py scrape` → jobs appear in DB from ≥5 sources; spot-check salary extraction
- `python scripts/run.py score` → scores + reasons on real jobs; sanity-check top-10 against resume manually
- Contact discovery on 3 known companies → verify at least GitHub-sourced emails are real
- End-to-end dry run: draft → review queue → approve → send to user's own second email → reply to it → confirm classification + notification fires
- Backend: `python scripts/run.py serve` → FastAPI on :8000, `/docs` shows all endpoints
- Dashboard: `cd dashboard && npm run dev` → all sections functional against the live API
