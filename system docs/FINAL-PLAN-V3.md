# ZoNuLy — Final Plan v3: built from gtm-arch, zon-arch and CHOKEPOINTS

> **This replaces FINAL-PLAN-V2.md and, on model strategy and orchestration, FINAL-PLAN.md.**
> Written 2026-08-31 after reading `gtm-arch.md`, `zon-arch.md`, `CHOKEPOINTS.md` and
> `MULTI-AGENT-ORCHESTRATION.md` in full. It keeps what the running code already proves
> (ATS scraping, GitHub commit mining, the review-queue gate, the knowledge graph) and rebuilds
> everything else on the patterns those documents describe.
>
> **Ollama is out.** It has wrecked the machine every time. There is no local model anywhere in
> this plan; every model call goes through OpenRouter behind a cost ledger and a budget gate.
>
> **Nothing here is built until you approve the step by number (§14).**

---

## 1. What changes, in one table

| Old plan (v1/v2) | v3 | Comes from |
|---|---|---|
| qwen3:4b + nomic-embed on Ollama; "local-first" as a guarantee | **OpenRouter only**, one key, three model *aliases* (`cheap`, `writer`, `judge`); the client never retries; a cost row per call; a daily/monthly budget gate; no key → the stage does not run | gtm-arch §4.4, §17; CHOKEPOINTS §4.3 |
| Embedding prefilter (needs a local embedder) | **Model-free lexical fit** (rare-term-weighted vocabulary overlap, resume vs JD), then a `cheap` triage call, then the `judge` rubric — a cost gradient with no model at the wide end | CHOKEPOINTS §9.1.5 `fit.py`; MULTI-AGENT §6 D2 |
| APScheduler inside the API process | **launchd hourly tick**, `fcntl`-locked, spending exactly this hour's rate and money budget; fires on wake; a killed tick loses one item | CHOKEPOINTS §9.1.8, §15 |
| Scrapers write the registry | **Staging → audit → promote.** No scraper writes `companies.*`; `promote --apply` refuses on a failing audit and restores the backup | CHOKEPOINTS §9, §9.1.10 |
| One `httpx` client per scraper | **One politeness core** (`fetch.py`): robots-checked, per-host rate, disk cache by URL hash, real User-Agent, 20 s / 2 MB bounds. Nothing else may call the network | CHOKEPOINTS §9.1.1 |
| Plain function calls; no run history | **Durable run ledger**: every agent invocation is an `agent_run` row with phases, status, tokens, cost, error; resumable; `parent_run_id` for the tree | gtm-arch §10 "agent run ledger"; MULTI-AGENT §9 |
| Drafts land directly in the queue | **Every agent write is a proposal.** `draft_proposals`, `fact_proposals` (a contact's role, email, seniority), each with confidence and evidence; thresholds promote facts (≥ 0.85 auto, 0.70–0.85 review band, < 0.70 review-with-reason, **never auto-reject**); drafts are always HITL | gtm-arch §2 #3, §12 |
| Anti-fabrication is a prompt | **Faithfulness gate + publish gate**: every specific claim in a draft carries an evidence span that must literally exist in a fetched artifact; every proper noun and number must match a fact or is stripped | gtm-arch §12, `faithfulness.py`; CHOKEPOINTS §12.3 `publish_gate.py`; MULTI-AGENT §13 |
| Scraped text pasted into prompts | **Trust boundary**: every fetched result, success and error, is wrapped `<INGESTED_UNTRUSTED_CONTENT>` and every system prompt says it is data, not instructions | gtm-arch §9.6 |
| Dashboard only | **Telegram as a review surface** — one bot, inline Approve / Edit / Reject / Skip buttons, atomic status claim so a double tap cannot double-send; same for calendar conflicts | zon-arch §1, §16.2 (Slack cards + atomic claim), swapped to Telegram because it is free and two people |
| GitHub-only people discovery | **Three channels** for people: GitHub commits (free, verified), Apify no-cookies employee harvest (pinned actor, cached, budget-gated), and a Brave-Search + `cheap`-model research rig that returns only URL-cited facts | gtm-arch §9.2–9.4; CHOKEPOINTS §9.4 |
| No calendar | **Calendar sync** with `syncToken`, 410 → full resync ±7 days, a notifier that fires once per event via `notified_at` | zon-arch §16.8, §19 |
| Prompts hand-rolled | **Agent runtime** on `pydantic-ai` (the library gtm-os uses): typed input, typed output, a narrow tool surface per role, `enforce_capability` as the first line of every tool, a budget triple (max tool calls, max tokens, deadline) enforced by the runtime | gtm-arch §4.2, §10; MULTI-AGENT §7 |
| Costs logged | **Costs are rows**: `agent_run_costs` (model calls) and `apify_run_log` (scrapes) with vendor, model, tokens, INR; budgets read them before every call | gtm-arch §9.4; zon-arch §2.2 (the missing column) |
| Config file constants | **`budgets.py`** — every timeout, threshold, cap in one file, pinned by a test so a silent retune is impossible; **`permissions.yaml`** — every grant | gtm-arch §10, §17; your permission requirement |

**Unchanged because the code proves it:** ATS JSON scrapers and the 94-board registry; HN / RemoteOK / WWR / YC; GitHub repo-commits mining (25/25 verified); title + location rules; cross-source dedup; salary → INR LPA; three confidence tiers; the review gate; the 25/day cap; one follow-up; the knowledge graph; the Next.js dashboard over REST; SQLite as the single file.

**Dropped from the old plans, explicitly:** Ollama and everything that only existed because of it (`keep_alive`, fixed `num_ctx`, "8 GB is why", the resume-vector cache, the percentile prefilter); APScheduler; the "no data leaves the laptop" guarantee (replaced by "no *secret* leaves the laptop and every outbound call is logged and budgeted"); the idea that local is a virtue.

---

## 2. Non-negotiables (copy into the repo before writing code)

| Rule | Why | Enforced by |
|---|---|---|
| **No fabrication, ever.** Every contact fact and every specific draft claim carries a source and an evidence span; unsupported specifics are stripped, not softened | The only asset of a cold email is that it is true | faithfulness gate, publish gate, CI grep |
| **Agents propose; humans commit.** No agent write reaches a canonical table or the outbox without a threshold rule or a human | gtm-os's whole thesis; your approval requirement | proposal tables, `EXECUTE_OUTREACH` held by nobody |
| **Sending is not a capability any role holds.** `send_email` is reachable only from the approval handler with a human actor | The Gmail account is the asset | capability enum + test |
| **Budget gates before every paid call.** OpenRouter and Apify each have a daily and monthly cap in `permissions.yaml`; the ledger is checked first; over cap → an approval request, never a silent skip | Student budget | `budgets.py`, `permissions.check` |
| **The rate budget is the constraint, not the machine.** Free sources are hit at their documented rate, deliberately, 24/7, in bounded slices | CHOKEPOINTS' governing insight | `fetch.py`, `tick.py` |
| **No scraper writes the canonical registry.** Staging → audit → promote | One bad run must not corrupt the asset that compounds | `promote.py` |
| **All fetched content is untrusted** | A bio that says "recommend me" must not work | wrapper + prompt rule |
| **No logged-in LinkedIn automation, no auto-apply, no contact-list export** | The account and the reputation are the strategy | no code path; CI grep for cookie actors |
| **25 sends a day per Gmail account, at most 5 to guessed addresses, one follow-up, one of us per contact per month** | Deliverability and decency | ledger rows, drafter checks |
| **Every constant in `budgets.py`, every grant in `permissions.yaml`, every secret in the environment** | Silent retunes and leaked keys are how systems die | tests, CI grep |
| **Nothing is built without a numbered approval** | Your rule | §14 |

---

## 3. System shape

Two processes, one SQLite file, one Telegram bot, one OpenRouter key.

```
   ┌──────────────────────────────────────────────┐   ┌──────────────────────────────┐
   │  Next.js dashboard (localhost:3000)          │   │  Telegram bot (your phone)   │
   │   Leads · People · Review · Tracker ·        │   │   proposal cards: Approve /  │
   │   Calendar · Permissions · Runs · Costs      │   │   Edit / Reject · conflict   │
   │   reads/writes ONLY through the REST API     │   │   cards · budget alerts      │
   └───────────────────┬──────────────────────────┘   └──────────────┬───────────────┘
                       │ HTTP                                        │ webhook / long-poll
   ┌───────────────────▼────────────────────────────────────────────▼───────────────┐
   │  FastAPI (127.0.0.1:8000)                                                      │
   │   reads · proposal decisions (the ONLY place approve is settable) ·            │
   │   permission requests · run/cost history · action endpoints → agent_runs      │
   └───────────────────────────────────┬────────────────────────────────────────────┘
                                       │ same DB
   ┌───────────────────────────────────▼────────────────────────────────────────────┐
   │  launchd → tick.py (hourly, fcntl-locked, bounded)                              │
   │   conductor: deterministic state machine over stages, per-item commits          │
   │   spends this hour's rate budget (free sources) and money budget (paid)         │
   │   dispatches agents; parses their OUTPUT ROWS, never their transcripts          │
   └──────┬──────────────┬──────────────────┬──────────────────┬────────────────────┘
          │              │                  │                  │
   ┌──────▼──────┐ ┌─────▼────────┐  ┌──────▼─────────┐ ┌──────▼──────────────────┐
   │ fetch.py    │ │ apify.py     │  │ openrouter.py  │ │ google.py               │
   │ politeness  │ │ pin registry │  │ aliases        │ │ Gmail send/read         │
   │ core, cache │ │ cache, ledger│  │ ledger, budget │ │ Calendar syncToken      │
   │ robots, UA  │ │ ?maxCharge   │  │ num_retries=0  │ │ OAuth, own accounts     │
   └──────┬──────┘ └─────┬────────┘  └──────┬─────────┘ └──────┬──────────────────┘
          ▼              ▼                  ▼                  ▼
     ATS · HN · YC   harvestapi      deepseek / kimi /    gmail.googleapis.com
     RSS · GitHub    no-cookies      gpt-nano / sonnet    calendar.googleapis.com
     company sites   actors          via openrouter.ai
```

Four adapters are the **only** modules allowed to touch the network. A CI grep enforces it
(the CHOKEPOINTS rule: "nothing else in the harvest is allowed to call urllib directly").

---

## 4. Tool and vendor inventory

### 4.1 Runtime

| Tool | Job | Status |
|---|---|---|
| Python 3.12, `uv` | the pipeline | [BUILT] |
| SQLite + FTS5 (SQLModel) | every table, the knowledge graph, ledgers | [BUILT] |
| **`pydantic-ai-slim[openai]`** | the agent loop: typed I/O, tools, validation retries | [GAP] |
| `pydantic` | every envelope, proposal and agent output is a validated model | [BUILT] |
| FastAPI + uvicorn | API, proposal decisions | [BUILT] |
| Next.js 16 | dashboard | [BUILT] |
| `launchd` | hourly tick, fires on wake | [GAP] |
| `python-telegram-bot` (or raw Bot API via the politeness core) | review cards, notifications | [GAP] |
| NetworkX | graph analysis | [BUILT] |

### 4.2 Models — all via OpenRouter, addressed by alias

| Alias | Candidate models (verify ids on openrouter.ai/models) | Used for | Order of magnitude |
|---|---|---|---|
| `cheap` | `openai/gpt-5-nano` (400k ctx), `deepseek/deepseek-v4-flash`, `z-ai/glm-4.7-flash` | JD triage, salary extraction, role classification, reply classification, schedule extraction, fact extraction from pages, HN thread parsing | ₹0.02–0.10 per call |
| `judge` | a mid-tier reasoning model (`deepseek/deepseek-v4`, `moonshotai/kimi-k2.x`) | the fit rubric on survivors, the approval assistant, the faithfulness support check | ₹0.20–0.60 per call |
| `writer` | `anthropic/claude-sonnet-4.x` or `moonshotai/kimi-k2.x` | drafts, follow-ups, reschedule replies | ₹0.50–1.50 per draft |

Rules from gtm-arch §4.4 and CHOKEPOINTS §4.3, all adopted: **`num_retries: 0`** in the client
(the conductor owns retry); aliases at call sites, model ids only in `config.yaml`; **strip
`<think>…</think>`** and discard content that opens with an unclosed `<think>`; **budget
`max_tokens` for hidden reasoning** on reasoning models; inject `today_iso` into every prompt;
a 429 from a global rate limit is retryable by the conductor, a budget-exceeded is not.

Estimated spend at full volume (both candidates), *to be verified against the first week's ledger*:

| Stage | Volume/day | Alias | ₹/month |
|---|---|---|---|
| Triage (after the lexical gate) | ~150 | cheap | 100–300 |
| Rubric on survivors | ~40 | judge | 250–700 |
| Role classification residue, replies, schedules | ~60 | cheap | 50–150 |
| Drafts + follow-ups | ~50 | writer | 700–2,000 |
| Approval assistant | ~50 | judge | 300–800 |
| **Total** | | | **₹1,400–4,000** |

That is above MOTIV's ₹1,000–2,500 target at the top end. The levers, in order: route drafts to
`judge`-tier instead of Sonnet (halves the biggest line); triage fewer jobs (the lexical gate is
free, tighten it); review-assist only drafts the validator flagged. The ledger will tell us which
to pull; the caps in `permissions.yaml` stop it exceeding what you set regardless.

### 4.3 Data sources

| Source | Channel | Keyless | Rate / cost | Status |
|---|---|---|---|---|
| Greenhouse / Lever / Ashby board APIs | A | yes | polite | [BUILT] |
| HN Algolia (Who is Hiring) | A | yes | polite; parsed by `cheap` | [BUILT] |
| RemoteOK, WeWorkRemotely, YC | A | yes | polite | [BUILT] |
| Funding-round RSS (TechCrunch, EU-Startups, Sifted, YourStory) | A | yes | polite | [GAP] |
| GitHub REST (org, repos, commits, users) | A | token (free) | 5,000/hr | [BUILT] |
| Company sites (team/about/careers) | A | yes | robots + per-host rate | [BUILT] |
| DNS MX | A | yes | — | [BUILT] |
| **Brave Search API** | C | key, free tier | ~2,000 queries/month free; company and person evidence gathering | [GAP] |
| **Apify** `harvestapi~linkedin-company-employees` | B | key | ≈ $0.15 per 50; cap $0.50/day | [GAP] |
| Apify `harvestapi~linkedin-profile-scraper` | B | key | ≈ $0.004 | [GAP] |
| Apify `harvestapi~linkedin-company-search` | B | key | free tier | [GAP] |
| Hunter.io | A | key, free | 25/month | [BUILT] |
| Gmail API, Google Calendar API | — | OAuth, own accounts | free | [BUILT partial] / [GAP] |
| Telegram Bot API | — | bot token, free | — | [GAP] |

### 4.4 Free APIs on the bench — available when a step needs them, added only with a §14 line

| API | Free | Would be used for | Add at step |
|---|---|---|---|
| Wikimedia REST + DBpedia SPARQL (CHOKEPOINTS §4.2) | keyless; 500/hr and Crawl-delay 10, honoured | company facts in bulk — HQ country, founded, headcount, ownership — to grade "funded startup, US/UK/DE" without a paid firmographics vendor | 7 (registry audit) |
| UK Companies House API | free key | is this UK company real, incorporated when, who are the officers (founders → referral targets) | 8 |
| OpenCorporates | free tier | the same for Germany and the EU | 8 |
| Product Hunt API | free key | recently launched startups → another feed into the registry | 7 |
| GitHub GraphQL | same free token | cheaper org/contributor sweeps than REST when volume grows | 8 |
| Google Programmable Search | 100/day free | fallback if Brave's free tier is exhausted | 8 |

Anything else you can get for free goes on this bench first; a bench entry is not a grant.

**Not used, with no code path:** Ollama or any local model; cookie-based LinkedIn actors;
Phantombuster and kin; auto-apply; paid email finders; Postgres, Temporal, LiteLLM proxy, Nango,
Trigger.dev, Slack. (LiteLLM's *idea* — aliases, per-key budgets — is kept in ~150 lines of
`openrouter.py`; the proxy server itself needs 1.5 GB and a daemon.)

---

## 5. Data model

Kept: `company`, `job`, `contact`, `email`, `reply`, `setting`, `kg_*`. New, grouped the way
gtm-arch groups them.

```
Candidates      candidate(id, name, profile_path, gmail_token_path, timezone, daily_send_cap,
                          guessed_send_cap, telegram_chat_id, active)
                job_score(candidate_id, job_id, fit_lexical, triage, score, breakdown json,
                          reasons, gaps, feasibility, rubric_version, model_alias, scored_at)

Immutable       artifact(id, kind, source_url, content, content_hash unique, fetched_at, source_tier)
                   kind: posting | team_page | repo | profile | search_result | reply
                   -- every fetched document, append-only. Evidence spans point here.

People          contact + role_class, seniority, linkedin_url (canonical /in/<slug>),
                          warmth_tier, warmth_evidence, discovered_via (github|site|apify|manual)
                fact_proposal(id, subject_table, subject_id, predicate, value, confidence,
                              evidence_artifact_id, evidence_span, extractor, status,
                              decided_at, decided_by)
                   -- a contact's role, seniority, email, employer are facts; promoted by
                      threshold (≥0.85) or by you; never auto-rejected

Outbound        draft_proposal(id, candidate_id, contact_id, job_id, subject, body,
                               claims json [{sentence_idx, artifact_id, start, end}],
                               review_flags json, validator_status, status, expires_at,
                               decided_at, decided_by, edited_body)
                   -- replaces email.status='draft'; email rows are created only on approval
                send_budget(candidate_id, date, cap, used, guessed_used)
                thread(candidate_id, gmail_thread_id, contact_id, last_activity_at,
                       followup_count CHECK (followup_count <= 1))
                event(id, candidate_id, thread_id, company_id, kind, starts_at, ends_at, tz,
                      link, status, google_event_id, notified_at)
                calendar_sync_state(candidate_id, sync_token, last_synced_at, last_error)

Runs + money    agent_run(id, parent_run_id, role, input json, status, phase_events json,
                          tokens_in, tokens_out, cost_inr, wall_ms, error, started_at, ended_at)
                agent_run_cost(run_id, vendor, model_alias, model_id, tokens_in, tokens_out, cost_inr)
                apify_run_log(id, actor_id, version, input_hash, items, cost_usd, cached, at)
                fetch_cache(url_hash, url, fetched_at, status, path)         -- disk-backed
                source_health(source, last_ok_at, last_count, consecutive_failures, backoff_until)
                harvest_state(node, last_swept_at, sweeps, failures, found, staged)

Permissions     approval_request(id, tier, action, provider, cost_estimate, reason, payload,
                                 requested_at, status, decided_at, decided_by, standing)
                action_log(id, at, tier, action, provider, cost_inr, candidate_id,
                           ref_table, ref_id, outcome)
```

Conventions: `content_hash` is the idempotency key everywhere; `contact.confidence` and
`fact_proposal.confidence` have no default; `draft_proposal.expires_at` = 7 days; every id is
prefixed in logs (`run_`, `dp_`, `fp_`, `ev_`) the zon-arch way so a log line is self-describing.

---

## 6. Scraping — three channels, one staging area, one gate

```
   CHANNEL A  keyless, rate-budgeted        CHANNEL B  Apify no-cookies       CHANNEL C  Brave + cheap model
   ATS · HN · RSS · YC · GitHub · sites     employees · profiles · slug       company/person evidence, URL-cited
              │                                      │                                  │
              └──────────────────────────────────────┼──────────────────────────────────┘
                                                     ▼
                                       data/staging/<tag>.staging.jsonl        never companies.* / contact
                                                     │
                                            promote.py  (preview by default)
                                                     │
                                            audit.py PASS?  ── no ──► restore backup, abort
                                                     │ yes
                                                     ▼
                                        company / job / contact / fact_proposal
```

**A — the politeness core** (`fetch.py`, verbatim from CHOKEPOINTS §9.1.1): robots-checked only
when a real `robots.txt` exists; per-host minimum delay with documented overrides (GitHub with
token 0.5 s; Algolia 1 s; company sites 1.5 s); disk cache by URL hash under `data/fetch_cache/`;
a real User-Agent naming the project and a contact address; 20 s timeout, 2 MB cap. **Every
scraper, the researcher and the Telegram client go through it.** A CI grep fails on any other
`httpx.` call outside `fetch.py`, `apify.py`, `openrouter.py`, `google.py`.

**A — the tick** (`tick.py`, CHOKEPOINTS §9.1.8): launchd fires it hourly; it takes an `fcntl`
lock; reads the hour's remaining request budget per host and the day's remaining money budget
from the ledgers; runs the most-stale work first (never-swept boards, then longest-stale, then
unscored jobs, then companies awaiting people, then drafts owed); appends to staging; updates
`source_health` with backoff for a source that failed twice; exits within minutes. A source at 0
for two consecutive sweeps is a **failure in the morning report**, not a quiet day.

**A — funding feeds → registry**: RSS → `cheap` extracts company names and stage → `discover`
probes Greenhouse/Lever/Ashby → staged with `source_url` → promoted through the audit (dead
website, duplicate domain root, missing ATS, boilerplate description).

**B — Apify** (`apify.py`, gtm-arch §9.1–9.4 + zon-arch §13.1): a `PINNED_ACTORS` dict of
`(actor_id in ~ form, version, output_model, estimated_cost_usd)`; the synchronous
`run-sync-get-dataset-items` endpoint; cache key `(actor, version, sha256(sorted input))`, TTL 30
days; **budget pre-flight** against `apify_run_log` for today; `?maxCharge=` sent as the platform
ceiling; a response that fails the Pydantic `output_model` is **non-retryable** (bump the pin);
token as `Authorization: Bearer` only. Called only for companies that scored ≥ 65 for someone
and have no GitHub org. Rows enter as `fact_proposal`s with confidence from the evidence tier.

**C — research rig** (`research.py`, CHOKEPOINTS §9.4 `research_brave.py` + gtm-arch
`web_search`/`web_fetch`): per person or company, 3–6 short noun-phrase queries built only from
known fields → Brave → dedupe URLs → fetch top pages through the politeness core (SSRF-guarded:
resolve once, reject private ranges, no redirects) → the corpus goes to `cheap` with the
CHOKEPOINTS system prompt (*"you work ONLY from the source excerpts provided… every figure you
cite must be traceable to one of the provided URLs"*) → `{observations[], facts[]}` where every
item carries `{artifact_id, start, end}`. **An observation without a span is dropped before the
drafter ever sees it.** Source quality is classified separately (content farm vs primary), the
CHOKEPOINTS §9.4 lesson.

**Name cleaning and dedup** (CHOKEPOINTS §9.6): the website/domain root is the identity key for
companies, the canonical `/in/<slug>` for people; dedup on normalised name **and** domain root;
**review the drop list**, not just the keep list.

---

## 7. The agent runtime

An agent is five things (gtm-arch §10): a role and system prompt; a typed input; a narrow tool
surface; a bounded loop; a typed output validated before anything is written. Implemented on
`pydantic-ai` against the OpenRouter OpenAI-compatible endpoint.

```python
# capabilities.py — narrow grants, one enum, the dangerous one held by nobody
class Capability(StrEnum):
    READ_DB, READ_ARTIFACTS, WEB_FETCH, WEB_SEARCH, PROPOSE_FACT, PROPOSE_DRAFT, LLM
    EXECUTE_OUTREACH   # reserved. No role holds it. A test asserts that.

ROLE_CAPABILITIES = {
    "triage":     {READ_DB, LLM},
    "judge":      {READ_DB, READ_ARTIFACTS, LLM},
    "role_class": {READ_DB, LLM, PROPOSE_FACT},
    "researcher": {READ_ARTIFACTS, WEB_SEARCH, WEB_FETCH, LLM, PROPOSE_FACT},
    "drafter":    {READ_DB, READ_ARTIFACTS, LLM, PROPOSE_DRAFT},
    "reviewer":   {READ_ARTIFACTS, LLM},
    "reply":      {READ_ARTIFACTS, LLM},
    "scheduler":  {READ_ARTIFACTS, LLM},
}

def enforce_capability(role, tool_name):   # first line of every tool; unknown tool -> ValueError
```

```python
# budgets.py — one source of truth, pinned by tests
BudgetSpec(max_tool_calls, max_input_tokens, wall_clock_s)   # frozen
FIRST_RUN / RERUN profiles per role (a cold company costs more than a re-check)
AUTO_APPROVE_THRESHOLD = 0.85     # facts only
HITL_ROUTE_THRESHOLD   = 0.70     # there is deliberately no AUTO_REJECT; a test asserts it
DRAFT_EXPIRY_DAYS = 7, FOLLOWUP_AFTER_DAYS = 5, DAILY_SEND_CAP = 25, GUESSED_SEND_CAP = 5
```

**Conductor rules** (MULTI-AGENT §4, §7): depth ≤ 2 (conductor → agent → tools; no agent calls
an agent); every run is an `agent_run` row with `phase_events`; the conductor **parses output
rows, never transcripts** (CHOKEPOINTS §9.5 — the rule that makes fan-outs survivable); a
worker that trips its budget returns `partial`; two backward edges only — drafter → triage on a
contradiction, outcomes → rubric as a *proposal*.

### The roster

| Role | Alias | Input → output | Writes |
|---|---|---|---|
| **Lexical fit** (no model) | — | resume terms vs JD terms, rarity-weighted, stemmed, stop-listed → `fit_lexical` 0–1 | `job_score.fit_lexical` |
| **Triage** | cheap | JD → `{worth_scoring: bool, why, region, remote_ok, sponsorship_stated}` | `job_score.triage` |
| **Salary** | cheap | residue after regex → INR LPA | `job` |
| **Judge** | judge | resume + JD → score, 5 dimensions incl. **location feasibility**, reasons, gaps; hard rules override (senior → 35, below floor → 40, thin JD → 60, US on-site no sponsorship → 45) | `job_score` |
| **Role classifier** | rules then cheap | headline/bio → `role_class`, `seniority`, confidence | `fact_proposal` |
| **Researcher** | cheap | Brave + fetched pages + repos → cited observations only | `artifact`, `fact_proposal` |
| **Drafter** | writer | observations + candidate profile + job → subject, body, **claims with spans** | `draft_proposal` |
| **Reviewer** (approval assistant) | judge | draft + its artifacts → span-existence check (deterministic), span-support check (model), humanisation lint (AI-tell vocabulary, no em dashes, one ask, 90–130 words), `review_flags` | `draft_proposal.review_flags`; **never** status |
| **Reply** | cheap | inbound message → positive / negative / closed / neutral; unclear → neutral | `reply` |
| **Scheduler** | cheap | positive reply → `{intent, proposed_times[], tz, link, deadline, needs_action}` | `event` (proposed) |
| **Follow-up** | writer | silent thread → 40–60 words | `draft_proposal` (kind=followup) |
| **Calibration** (monthly) | judge | `job_score` vs outcomes → rubric change *proposal* | a note for you, never the rubric |

No role holds `EXECUTE_OUTREACH`. No role can change `permissions.yaml` or `budgets.py`.

---

## 8. Proposals, HITL and the review surfaces

```
agent emits a fact / draft
        │
        ▼
fact_proposal | draft_proposal            status = pending
        │
        ├── fact, confidence ≥ 0.85 ────────────► approved, canonical write, same transaction
        ├── fact, 0.70 ≤ c < 0.85 ──────────────► review band (dashboard "People" tab)
        ├── fact, c < 0.70 ─────────────────────► review with reason (never dropped)
        └── draft, any ─────────────────────────► faithfulness gate → reviewer flags → REVIEW
                                                        │
                    ┌───────────────────────────────────┴────────────────────────────────┐
                    ▼                                                                    ▼
        Dashboard /review                                                   Telegram card
        draft · recipient · their evidence · the job · flags · budget      subject, first lines, flags,
        approve / edit+approve / reject · j k a r                           budget left, [Approve][Edit][Reject][Skip]
                    │                                                                    │
                    └──────────────────────────► approval handler ◄──────────────────────┘
                                          the ONLY caller of send_email
                                          atomic claim pending→approved (double tap safe)
                                          email row created, thread row created
                                                       │
                                                       ▼
                                          send_approved(): inside one transaction —
                                          lock send_budget row, check cap + guessed cap,
                                          check expiry, decrement, Gmail send, record
```

- **Faithfulness gate** (gtm-arch `faithfulness.py`, MULTI-AGENT §13): pass 1, deterministic —
  does `artifact[id][start:end]` exist and is the artifact one this run fetched; pass 2, `judge`
  — does that text support the sentence. Fail → the sentence is **stripped**, not rewritten. A
  draft left with no specific content is labelled `generic` and shown as such.
- **Publish gate** (CHOKEPOINTS §12.3): every proper noun and number in the body must appear in a
  cited span or a candidate-profile field, or the draft is blocked with the offending token named.
- **Telegram** (zon-arch §16.2 translated): a card per proposal to the candidate's `chat_id`;
  button callbacks verified by the bot token; the handler does an atomic `pending → processing`
  claim before acting; **Edit** opens a reply prompt whose text becomes `edited_body`; the card
  is repainted with the decision. Budget alerts at 80% of any cap (the gtm-arch Slack-alert
  pattern). Nothing is sent from Telegram — it only records the decision the API then acts on.
- **Draft expiry**: 7 days, then deleted, never sent.

---

## 9. The pipeline, stage by stage, with the cost gradient

```
 [1] SCRAPE        A: ATS·HN·RSS·YC·GitHub·sites  B: Apify   C: Brave    → staging     ₹0 / budgeted
 [2] PROMOTE       audit PASS → company · job · artifact                               ₹0
 [3] LEXICAL FIT   resume terms vs JD terms, no model; keep top 40%                     ₹0
 [4] TRIAGE        cheap: worth scoring? region? remote? sponsorship?                   ₹0.05
 [5] JUDGE         judge: score + 5 dims + reasons + gaps; hard rules      ≥ 65 → high  ₹0.40
 [6] PEOPLE        GitHub commits → site → Apify (if no org) → pattern → MX             ₹0–0.20/company
 [7] ROLES         rules → cheap residue → fact_proposals → threshold promotion         ₹0.02
 [8] RESEARCH      Brave + pages + repos → cited observations, or none                 ₹0.10
 [9] DRAFT         writer: 90–130 words, claims with spans                              ₹1.00
[10] GATE          faithfulness (span exists · span supports) → publish gate → reviewer ₹0.40
 ╔══════════════════════════════════════════════════════════════════════════════════════╗
 ║[11] REVIEW       dashboard or Telegram · approve / edit / reject · budget visible      ║
 ╚══════════════════════════════════════════════════════════════════════════════════════╝
[12] SEND          ledger row locked in the send transaction · ≤25 · ≤5 guessed · 10–19h
[13] TRACK         Gmail threads → reply agent → positive | negative | closed | neutral
[14] SCHEDULE      scheduler agent → event(proposed) → calendar conflict check
                     free → Google Calendar event + Telegram notify
                     clash → reschedule draft_proposal → [11]
[15] FOLLOW UP     5 days silent → one follow-up → [11]   (thread.followup_count ≤ 1)
[16] LEARN         monthly: outcomes vs scores → calibration proposal; funnel by role/stage/framing
```

Every stage is a `tick` work type, independently runnable from the CLI, idempotent (content
hashes), and commits per item.

---

## 10. Operations

- **`launchd`** plists: `tick` hourly; `poll-replies` every 30 min in the send window; `morning-report`
  at 08:00. Each script takes an `fcntl` lock. A run missed while asleep fires on wake.
- **Morning report** (Telegram + `knowledge/REPORT-<date>.md`): sources run and any at 0 twice;
  jobs scored and high matches; people found by channel; drafts awaiting you; sends left; replies
  by class; events today; **money spent yesterday by vendor and alias, against caps**.
- **Kill-hardened generators** (CHOKEPOINTS §13.1): every multi-item stage appends and `fsync`s
  per item and skips ids already present on restart, so a relaunch never re-spends a paid call.
- **Freshness watch** (CHOKEPOINTS §15): weekly re-check of companies with no new postings in 60
  days and contacts whose profile URL 404s (Apify's cheap status-only actor or a plain HEAD).
- **Knowledge graph**: `agent_run`, `draft_proposal`, `event` and the cost ledgers sync into the
  data layer; `kg note` remains the session memory; BRIEF.md regenerates with the morning report.

---

## 11. Permission and guardrail system

Unchanged from what you asked for and v2 §13, now with the vendors it actually gates:

| Tier | What | Rule |
|---|---|---|
| 0 | local read/compute (DB, lexical fit, graph) | always |
| 1 | free external reads (A-channel hosts, Brave free tier, Telegram) | within the per-host rate in `permissions.yaml`; logged |
| 2 | spend — **OpenRouter per alias**, Apify, Hunter | provider `enabled: true` by you, under daily and monthly caps; over cap → `approval_request`, notify, skip; a cap edit is the approval act |
| 3 | world writes — send, calendar create, reschedule | per-item human approval; sends can never become standing |
| 4 | forbidden — LinkedIn login, auto-apply, bulk delete, contact export, **any local model runtime** | no code path; CI grep |

```yaml
# permissions.yaml (proposed)
providers:
  openrouter: {enabled: false, daily_inr_cap: 100, monthly_inr_cap: 2500,
               aliases: {cheap: "openai/gpt-5-nano", judge: "deepseek/deepseek-v4", writer: "moonshotai/kimi-k2.6"}}
  apify:      {enabled: false, daily_usd_cap: 0.50, monthly_usd_cap: 12}
  brave:      {enabled: false, monthly_query_cap: 1800}
  hunter:     {enabled: true,  monthly_cap: 25}
sources:      {greenhouse: {enabled: true, min_delay_s: 1.0}, github: {enabled: true, token_env: GITHUB_TOKEN}, ...}
actions:      {send_email: per_item, calendar_create: per_item, reschedule_email: per_item}
candidates:   {tejmul: {daily_send_cap: 25, guessed_send_cap: 5}, teammate: {...}}
```

CI guardrails, each a grep or a test (gtm-arch §16 style): no `ollama` import anywhere; no
network call outside the four adapters; no untimed wait; Apify token as Bearer only; no
`AUTO_REJECT` symbol; `EXECUTE_OUTREACH` held by no role; every registered tool has a capability
entry; every constant in `budgets.py` pinned.

---

## 12. Acceptance checks per step

| Step | The check |
|---|---|
| 0 | A Hunter call over cap creates an `approval_request`; `send_email` on a pending draft is refused and logged; `permissions grant` executes it exactly once |
| 1 | `openrouter.py` returns a typed answer for each alias; a second identical call in the same day shows in the ledger with cost; over-cap returns `BudgetExceeded`, not a retry; Ollama code and config are gone and `grep -ri ollama` returns 0 |
| 2 | The same 10 jobs scored by v1 re-scored: lexical gate → triage → judge; before/after table; a US on-site no-sponsorship JD is capped at 45 |
| 3 | One email sent to a second inbox, replied to, classified, threaded |
| 4 | A crash injected between Gmail send and DB write cannot lose a decrement; a 6th guessed send is refused; an 8-day-old draft is gone |
| 5 | A draft with an invented repo name is stripped to generic and labelled; a claim whose span is not in the artifact is rejected; reviewer flags appear on every draft |
| 6 | A Telegram Approve on a card sends nothing itself; the API records the decision; a double tap yields one send |
| 7 | `tick --status` shows the queue; two ticks cannot both take the lock; `discover` stages, `--apply` audits and refuses on failure; a source at 0 twice appears in the morning report |
| 8 | First Apify company costs ≤ $0.20 and the second identical call is a cache hit; a Brave research run yields only URL-cited observations |
| 9 | Both candidates score the same job differently; a second draft to the same contact within 30 days is refused |
| 10 | A test reply with a Meet link becomes a calendar event and one Telegram notification; a clash becomes a queued reschedule draft |
| 11 | The queue sorts alumni first |
| 12 | `pytest` green; every CI grep passes |

---

## 13. Mistakes already paid for in the three codebases — do not repeat

| Lesson | Here |
|---|---|
| Running a scraper at 4× the documented rate with no 429s in sight | per-host rates set from documentation in `permissions.yaml` |
| A 14-result cap silently kept 227 of 2,055 companies | never cap a long-tail capture; check the source's own count |
| A prefix-match dedup dropped 275 valid rows | exact + substring on normalised names and domain roots; review the drop list |
| `max_tokens` 8–16k on a reasoning model returned empty with `finish_reason: length` | budget ~40k for reasoning aliases; strip `<think>`; discard unclosed |
| Re-authenticating mid-fan-out froze 23 agents silently | detect stalls by output-file mtime; never re-auth during a run |
| 17.6% of gathered sources were content farms and the verify pass could not tell | classify source quality separately from support |
| A source YAML edited without rebuilding → weeks of drift | generated files are obviously generated; drift check in CI (BRIEF.md already is) |
| Apify ids in slash form 404; retrying a bad shape burns money | `~` form; shape mismatch non-retryable |
| LiteLLM retrying inside Temporal → double retry, burned budget | `num_retries: 0`; the conductor retries |
| RLS without the role split never fired | no multi-tenancy here; `candidate_id` everywhere, tested |
| Adding an agent role in code but not in the DB CHECK → silent failure | role allowlist in one place, mirrored by a test |
| Allow-list auth left six routes open | API is localhost-bound; deny-by-default if ever exposed |
| Slack send returned silently when the token was missing → "success" | every notifier raises on missing config; `doctor` fails loud |
| Two orchestrators running the same jobs drifted | one: `tick.py`. APScheduler removed in step 7, not left running |
| Secrets in a table in plaintext | environment only; files hold env var names |
| All crons disabled at once for cost, then forgotten | per-provider caps; a disabled source shows in `doctor` and the morning report |
| Cost computed, logged, thrown away — no cost column | `agent_run_cost` and `apify_run_log` from the first call |

---

## 14. Build order — for your approval, by number

Rules: one step at a time; each step names its files, tools, keys, cost and check; I stop after
each with a `kg note`; no new tool or key without its line in §4; nothing that spends until you
have set `enabled: true` yourself.

| # | Step | Files | Needs | Cost |
|---|---|---|---|---|
| **0** | **Permission gate + ledgers** — `permissions.yaml`, `permissions.py`, `budgets.py`, `approval_request`, `action_log`, `agent_run`, `agent_run_cost`, `apify_run_log`; CLI `permissions pending/grant/deny`; dashboard Permissions + Runs + Costs tabs; wrap Hunter and `send_email` | `jobhunter/{permissions,budgets}.py`, `db.py`, `api.py`, `scripts/run.py`, `dashboard/app/{permissions,runs}` | none | ₹0 |
| **1** | **Model layer** — `openrouter.py` (aliases, `num_retries=0`, think-stripping, cost row, budget gate), `pydantic-ai` runtime, `capabilities.py`, `enforce_capability`; **remove Ollama** (`llm.py`, config, `doctor`, `matcher` embed path) | `jobhunter/{openrouter,agents/runtime,capabilities}.py`, delete `llm.py` | your OpenRouter key in env; `uv add pydantic-ai-slim` | ₹0 until enabled |
| **2** | **Scoring** — lexical fit (no model), triage agent, judge agent with the feasibility dimension and hard rules; `job_score` per candidate; rescore | `jobhunter/{fit,agents/triage,agents/judge}.py`, `matcher.py` → removed | step 1 | ~₹200 for the rescore |
| **3** | Gmail OAuth + end-to-end dry run | `secrets/` (yours) | Google Cloud OAuth client | ₹0 |
| **4** | Send ledger in the send transaction, guessed cap, draft expiry, `thread` with `followup_count ≤ 1` | `outreach/sender.py`, `db.py` | none | ₹0 |
| **5** | **Proposals + gates** — `artifact`, `fact_proposal`, `draft_proposal`, thresholds, faithfulness gate, publish gate, reviewer agent, review flags in the queue | `jobhunter/{proposals,faithfulness,agents/reviewer}.py`, `outreach/drafter.py`, queue UI | step 1 | ~₹0.40/draft |
| **6** | **Telegram review surface** — bot, cards, atomic claim, Edit flow, budget alerts, morning report | `jobhunter/telegram.py`, `api.py` | your bot token | ₹0 |
| **7** | **Scraping engine** — `fetch.py` politeness core, `tick.py` + launchd plists, `source_health`, staging/audit/promote, funding RSS, freshness alarm; remove APScheduler | `jobhunter/{fetch,tick,promote,audit}.py`, `scrapers/*` refactor, `launchd/*.plist` | GitHub token (free) | ₹0 |
| **8** | **People** — `apify.py` pin registry + cache + budget, employee harvest, role classifier agent, referral-ability ranking, Brave research rig with cited observations | `contacts/{apify,linkedin_public,roles}.py`, `jobhunter/research.py` | Apify key, Brave key (both yours) | ≤ ₹1,000/mo + ₹0 |
| **9** | **Two candidates** — `candidate`, per-candidate budgets/Gmail/Telegram, cross-candidate cooldown, dashboard switcher | `db.py`, `outreach/*`, dashboard | teammate's resume, Gmail, chat id | ₹0 |
| **10** | **Replies → calendar** — scheduler agent, `event`, `calendar_sync_state`, syncToken/410 flow, conflict → reschedule proposal, notifier | `jobhunter/{google,calendar}.py`, `agents/scheduler.py` | Calendar scope on the OAuth | ₹0 |
| **11** | Warmth tiers + manual alumni CSV | `contacts/warmth.py`, queue ordering | none | ₹0 |
| **12** | Tests + CI guardrails (the greps in §11), scoring fixtures, calibration proposal | `tests/`, `.github/workflows/ci.yml` | none | ₹0 |

Step 0 gates everything. Steps 1–2 remove Ollama and make the machine safe to run on. Steps 8's
paid parts run only after you flip `enabled: true`.

---

## Appendix — one line

> Two students, one laptop with no model on it, one OpenRouter key behind a ledger, three
> scraping channels behind one gate, agents that can only propose, and a phone that says
> Approve — 25 true emails a day each to engineers at funded startups that pay in dollars.
