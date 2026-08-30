# ZoNuLy — Final Architecture & Plan

> **This doc supersedes the other three in this folder.**
> `JOBHUNTER-ARCHITECTURE.md`, `JOBHUNTER-TOOLS.md` and `MULTI-AGENT-ORCHESTRATION.md`
> describe three *different* systems that disagree with each other on language, model
> strategy, orchestration shape and budget. This one reconciles them against code that
> is actually running, states which draft won each argument and why, and lists honestly
> what is still missing.
>
> **Annotations:**
> - **[BUILT]** — running now, verified against real data.
> - **[GAP]** — specified in a draft, genuinely valuable, not built yet.
> - **[DROPPED]** — in a draft, deliberately not doing it. Reason given.
> - **[OPEN]** — undecided. Not settled by fiat.

---

## 1. The brief, unchanged

> Do the nineteen mechanical minutes exhaustively. Stop dead at the ten seconds where
> judgement is required.

All three drafts agree on this and so does the code. When a decision is unclear the
tiebreaker is: **does this help spend the 25 daily sends better?**

---

## 2. Status — what is actually running

Measured on the live database, not estimated:

| | Count | Note |
|---|---|---|
| Jobs stored | **1,100** | from 11,282 scraped, after relevance + dedup |
| Sources live | **7** | greenhouse, lever, ashby, hn, remoteok, wwr, yc |
| ATS boards verified | **94** | every slug probed live, not guessed |
| Jobs scored | **102** | LLM rubric, ~18s each |
| High matches (≥65) | **26** | |
| Companies | **263** | |
| Contacts | **25** | **25 of 25 verified** — real emails from public commits |
| Drafts | 1 | draft path exercised, send path untested |

**Working end to end:** resume parse → scrape → normalise → salary extract → embed →
score → contact discovery → draft. **Untested:** approve → send → reply → follow-up
(needs Gmail OAuth credentials, which don't exist yet).

---

## 3. The nine decisions that settle the drafts

### D1 — Python, not TypeScript

`JOBHUNTER-ARCHITECTURE.md` and `JOBHUNTER-TOOLS.md` specify Next.js + Drizzle + a Node
worker, reasoning that the stack knowledge transfers from the MVRX portal.
`MULTI-AGENT-ORCHESTRATION.md` specifies Python.

**Python wins, and it's built.** The reason isn't preference — it's that the whole
value of this system sits in the scraping, PDF, and email ecosystem, and that ecosystem
is in Python. The frontend is still Next.js; it just talks to a Python API over REST
instead of owning the data layer.

**Consequence:** the layering lint from the portal (`lint-architecture.sh`) doesn't port
directly. The equivalent rule still holds and is currently maintained by convention, not
enforcement — see [GAP-6].

### D2 — Local model, and the size the machine can actually hold

Every draft assumes **qwen2.5:14b** and ~16 GB RAM. **This machine has 8 GB.** A 14B
model does not fit alongside an embedder.

**Built and measured: `qwen3:4b` + `nomic-embed-text`.** Roughly 18s per rubric score,
~1.2s per batch of 12 embeddings, both models resident at ~4.2 GB.

The scores it produces are **correctly calibrated** on real postings — verified by hand:

| Score | Role | Why the number is right |
|---|---|---|
| 75 | Software Engineer, Early Career (AI) @ Notion | explicitly early-career, stack overlap |
| 65 | Applied ML Engineer @ Deepgram | good fit, no speech-domain experience |
| 35 | Senior ML Engineer, NLP @ Observe.AI | 3+ yrs required vs 1 |
| 15 | Senior ML & AI Solutions @ Databricks | 8+ yrs required |

That was the open question in `MULTI-AGENT-ORCHESTRATION.md §20 Q1` — *"is a 14B local
model good enough for calibrated scoring?"* The answer, at 4B: **yes for ranking.**
Calibration against real screen outcomes is still unmeasured.

**Two non-obvious constraints discovered while building, both now encoded:**
- Ollama reloads the model whenever `num_ctx` changes, which costs *minutes* on 8 GB.
  Every call site therefore shares one context size and varies only `num_predict`.
- `keep_alive: 30m` is required, or a mid-run eviction stalls a scoring pass.

### D3 — No hosted model. The drafts contradict each other; local wins

`JOBHUNTER-TOOLS.md` budgets ~₹800/mo for **Claude Sonnet** on drafting, arguing local
8B prose is "noticeably stiffer". `MULTI-AGENT-ORCHESTRATION.md §16` says the opposite,
in bold: *"There is no LLM API key, and that is the point."*

**Resolved in favour of local**, on three grounds:
1. It's the constraint originally chosen for this project (free-tier, local).
2. The review queue catches weak prose. A stiff draft you edit is not a failure mode —
   an unreviewed one would be.
3. `llm.py` is a single thin client. Swapping to a hosted model is one config line if
   draft quality turns out to be the bottleneck.

**This is the seam to pull first if reply rates are bad.** Not before.

### D4 — The orchestrator is deterministic code, and there are no supervisor agents

`MULTI-AGENT-ORCHESTRATION.md` designs 5 LLM-backed supervisors over 18 workers. Its own
§20 Q4 then asks whether supervisors should be LLM-backed *at all*.

**Answer from the build: no.** Every "supervisor" decision in that design — which
sources to run, how many jobs to score, which companies to hunt, how many drafts to
write against remaining budget — is a policy expressible in about ten lines of Python
with a config value. Wrapping it in a model call would add latency, non-determinism and
a token bill in exchange for nothing.

**What survives from that design, and matters:**
- The conductor/state-machine idea → `scheduler.py` + per-item commits
- Narrow, single-purpose workers → each scraper and contact source is exactly that
- Typed contracts between stages → `RawJob`, `Salary`, `Score` dataclasses
- Depth cap of 2 → there is no nesting at all
- One dead source never kills a run → every scraper is individually try/except'd, and
  `ScrapeStats.errors` records which failed

**What's dropped:** the envelope protocol, capability narrowing between agent tiers, and
the run tree. They solve a problem — auditing untrusted delegation — that a pipeline of
plain function calls doesn't have. **[DROPPED]**

### D5 — The GitHub email spike came back good, with a sharp caveat

`JOBHUNTER-ARCHITECTURE.md` flagged this as the 🔴 risk that "kills the premise" and
demanded it be measured in week 1. **Measured:**

| Company | Contacts | With real email |
|---|---|---|
| Supabase | 12 | **12** |
| Affirm | 20 | **20** |
| GitLab | 5 | **5** |
| Observe.AI | 0 | 0 — no GitHub org found |

**Not 20–40% as feared. Effectively 100% — but only for companies with public repos,
and 0% for those without.** The distribution is bimodal, exactly as
`MULTI-AGENT-ORCHESTRATION.md` failure mode #7 predicted.

**Why the drafts got the number wrong:** they assumed mining a *person's* public events.
GitHub removed commit detail from `PushEvent` payloads, so that approach yields nothing —
it was tried first and returned 0/4 on active accounts. The **repo commits endpoint**
still carries `commit.author.email` in full. One call returns ~100 commits covering dozens
of engineers, so a whole company costs ~10–16 API calls instead of 60+.

**Implication for targeting:** infra, devtools and AI-infra companies are cheap to
contact. Consumer and enterprise companies with no public code need the team-page path,
and if that fails they should be **skipped, not guessed at**.

### D6 — Free tier only. No paid email finders, no verification credits

`JOBHUNTER-TOOLS.md` budgets ₹3,300 month one and ₹5,000/mo after, mostly Findymail +
MillionVerifier.

**Not spending it.** The waterfall is built so paid tiers *can* slot in, but the free
tiers are doing the work: GitHub commits are the highest-confidence source and they're
free, and Hunter's free tier (25/mo) is reserved for learning a company's *email pattern*
rather than individual lookups — one call generalising to every name at that company.

**Revisit only if** the verified-contact rate drops below roughly 20% across a realistic
target set. It's currently far above that for the companies worth contacting.

### D7 — SMTP RCPT probing is off. `JOBHUNTER-TOOLS.md` was right

That doc says, of DIY MX + SMTP probing: *"⚠️ Unreliable, and probing can get your IP
blocked. **Don't**"*.

It was built with the probe **on** by default. **That was wrong and is now corrected** —
`contacts.smtp_verify: false`. The reasons are worth recording because they're not
obvious:
- Residential ISPs block outbound port 25, so the probe usually just times out.
- Google Workspace and Microsoft 365 accept **every** recipient at the edge and bounce
  later, so a `250` proves nothing for the majority of targets.
- Repeated probing risks the IP being listed.

**MX lookup still runs** — it's a real check and costs nothing. Anything not confirmed
stays labelled `pattern-guessed`, and the UI says so.

### D8 — Three confidence tiers, never collapsed

The drafts disagree: 2 tiers (`verified`/`guessed`) vs 3 (`verified`/`derived`/`guessed`).

**Built with three,** named for what the user actually needs to distinguish:

| Tier | Means | Source |
|---|---|---|
| `verified` | came from a real commit or a public profile field | GitHub |
| `pattern-guessed` | built from a learned pattern, MX-checked, nothing stronger | pattern inference |
| `scraped` | found on a page, unconfirmed | team/about page |

Shown as a badge everywhere a contact appears, and used to sort the review queue.
**Never defaulted** — every insert states it.

### D9 — SQLite, one file, no vector extension

All drafts agree on SQLite. Two specify `sqlite-vec`.

**Not using it.** At 1,100 postings, cosine similarity in plain Python over cached
vectors takes under a second. `sqlite-vec` is an extension to install, load and keep
compatible for no measurable gain at this scale. The resume vector is cached in a
key/value row and invalidated by content hash when the resume changes.

Revisit past ~50k postings. **[DROPPED for now]**

---

## 4. System shape

Two processes, one SQLite file, everything on the laptop.

```
   ┌────────────────────────────────────────────────────────┐
   │  Next.js 16 dashboard  (localhost:3000)                │
   │   Overview · Leads · Contacts · Queue                  │
   │   Tracker · Replies · Settings                         │
   │   — reads/writes ONLY through the REST API             │
   └───────────────────────┬────────────────────────────────┘
                           │ HTTP
   ┌───────────────────────▼────────────────────────────────┐
   │  FastAPI  (127.0.0.1:8000)      jobhunter/api.py       │
   │   · read endpoints: jobs, contacts, emails, tracker    │
   │   · action endpoints: dispatch to a background thread, │
   │     return a task_id. Never run a stage inline.        │
   │   · APScheduler lives in this process                  │
   │       daily 08:00  → scrape → salary → embed → score   │
   │       hourly       → poll replies → queue follow-ups   │
   └───────┬───────────────────────────────┬────────────────┘
           │                               │
   ┌───────▼─────────────┐     ┌───────────▼────────────────┐
   │  SQLite             │     │  Ollama (localhost:11434)  │
   │  jobhunter.db       │     │   qwen3:4b                 │
   │  6 tables + kv      │     │   nomic-embed-text         │
   └─────────────────────┘     └────────────────────────────┘
           │
   ┌───────▼──────────────────────────────────────┐
   │  external, read-only, allowlisted by module  │
   │   ATS APIs · HN Algolia · RemoteOK · WWR     │
   │   YC directory · GitHub API · Gmail API      │
   └──────────────────────────────────────────────┘
```

**The API never runs long work in a request handler.** Scrape, score, contact discovery
and send all dispatch to a thread and return a `task_id`; the dashboard polls
`/api/tasks/{id}`. This is the one pattern copied wholesale from the portal and it's the
reason the UI never blocks on a 20-second model call.

---

## 5. The pipeline

Narrowing by design: wide and free at the top, narrow and expensive at the bottom.
Real numbers from the last full run.

```
 [1] SCRAPE          11,282 postings     free, parallel     pipeline.scrape()
        │            7 sources, each independently fault-isolated
        ▼
 [2] FILTER + DEDUP   1,651 relevant  →  1,100 stored       normalize.py
        │            title/location rules, then company+title fingerprint
        │            across sources (551 duplicates collapsed)
        ▼
 [3] SALARY           regex first, LLM only on the residue  normalize.parse_salary
        │            handles $185,000-$260,000 · ₹25-40 LPA · 30,00,000 INR
        │            · £90k · 1.2 Cr · monthly stipends → all to INR LPA
        ▼
 [4] EMBED            1,100 vectors, ~2 min total           matcher.prefilter()
        │            cosine vs resume; keep top 30% by percentile, not a
        │            fixed threshold — thresholds drift, percentiles don't
        ▼            ~330 survive
 [5] SCORE            rubric, ~18s each                     matcher.score_pending()
        │            → screen odds 0-100 + reasons + gaps + 4-part breakdown
        │            then deterministic hard rules override the model:
        │              senior title      → cap 35
        │              below salary floor → cap 40
        │              thin description   → cap 60
        ▼            ≥65 → high_match → notify
 [6] CONTACTS         per high-match company                contacts/
        │            GitHub commits → site scrape → learn pattern
        │            → Hunter (only if no pattern yet) → MX check
        ▼            each row carries source + confidence
 [7] RESEARCH         their repos + bio → one honest hook   outreach/researcher.py
        │            hook is null if the material is too thin. Never invented.
        ▼
 [8] DRAFT            90-130 words, plain text              outreach/drafter.py
        ▼
 ╔══════════════════════════════════════════════════════════════════╗
 ║ [9] REVIEW QUEUE — the only human gate, the only path to send    ║
 ║     edit · approve · reject       budget visible, depleting      ║
 ╚══════════════════════════════════════════════════════════════════╝
        ▼            ≤25/day
 [10] SEND           Gmail API, 10:00-19:00, 45-210s stagger  outreach/sender.py
        ▼
 [11] TRACK          poll threads → classify                 outreach/tracker.py
        │            positive | negative | closed | neutral
        │            ambiguous → neutral → human reads it
        ▼
 [12] FOLLOW UP      5 days silent → exactly one → back to [9]
```

Every stage is independently runnable from the CLI, idempotent, and commits per item so
a crash loses one item rather than the run.

---

## 6. Data model

Six tables plus a key/value row for runtime state. All in `jobhunter/db.py`.

```
Company    id, name(unique), website, domain, github_org,
           ats, ats_slug, email_pattern, contacts_found_at

Job        id, company_id, company_name, title, location, remote,
           url(unique)          ← dedup key within a source
           fingerprint(indexed) ← dedup key ACROSS sources
           source, description, posted_at, scraped_at,
           salary_min_lpa, salary_max_lpa, salary_raw, currency,
           salary_extracted,
           match_score, match_reasons, skill_gaps, embed_sim, scored_at,
           status, notified

Contact    id, company_id, name, role, email(indexed),
           github, linkedin, source,
           confidence          ← verified | pattern-guessed | scraped
           is_recruiter, research_notes, researched_at

Email      id, contact_id, company_id, job_id, to_email,
           subject, body, kind, parent_email_id,
           status              ← draft|approved|rejected|sent|replied|failed
           error, gmail_thread_id, gmail_message_id,
           created_at, approved_at, sent_at, followup_sent

Reply      id, email_id, gmail_message_id(unique), from_addr, body,
           sentiment, sentiment_reason, received_at, notified

Setting    key, value          ← resume vector cache, Hunter monthly counter
```

**Conventions that matter:**
- `Job.url` unique **and** `Job.fingerprint` indexed — the same role posted to both its
  ATS and an aggregator collapses to one row, keeping the richest description.
- Re-scraping never clobbers scoring work; it refreshes volatile fields only.
- `Email.followup_sent` is set when a follow-up is *queued*, not when sent — so a second
  one can't be created even if the first is never approved.

**Deltas the drafts want and this doesn't have yet:** see [GAP-1] and [GAP-4].

---

## 7. The three guarantees, and where each lives in code

Everything else is convenience. These three are the product.

| Guarantee | Enforced at | Currently |
|---|---|---|
| **Nothing sends without a human** | `sender.send_email()` refuses any email whose status isn't `approved`; approval is only settable from the API's approve route | **[BUILT]** — and no scheduled job calls send. The scheduler drafts and polls; it never sends. |
| **Nothing is invented** | drafter + researcher prompts require a null hook rather than a fabricated one; `_clean_body` strips model sign-offs | **[BUILT] at prompt level only** — see [GAP-2] |
| **25/day, irreversibly spent** | `sender.sent_today()` counts sent rows since local midnight; `remaining_today()` gates every send | **[BUILT], but a count not a ledger** — see [GAP-1] |

---

## 8. Module layout

```
jobhunter/
  __init__.py      config loader
  db.py            SQLModel models, session, kv helpers
  llm.py           Ollama client — chat, JSON mode w/ retry, embeddings
                   the ONLY place a model is called from
  resume.py        PDF/MD → profile.json (+ pulls hyperlinks from PDF annots)
  normalize.py     relevance rules, dedup fingerprint, salary → INR LPA,
                   mojibake repair
  pipeline.py      scrape orchestration, company sync, persist, salary backfill
  matcher.py       resume vector cache, percentile prefilter, rubric scoring
  notify.py        macOS notifications
  scheduler.py     APScheduler: daily cycle + hourly reply poll
  api.py           FastAPI: reads, actions, background task registry

  scrapers/        base.py (RawJob + async HTTP) · discover.py (ATS probe)
                   greenhouse · lever · ashby        ← ATS JSON APIs
                   hn_hiring · remoteok · wwr · yc   ← aggregators
                   (wellfound · cutshort · instahyre  ← Playwright, [GAP-5])

  contacts/        github_miner · site_scraper · patterns · hunter · verify
                   __init__.py orchestrates the waterfall

  outreach/        researcher · drafter · gmail · sender · tracker

dashboard/         Next.js 16 · 7 sections · talks only to the REST API
scripts/run.py     CLI: doctor profile scrape score find-contacts draft
                        gmail-auth send poll daily discover serve
companies.yaml     94 live-verified ATS boards
config.yaml        every threshold, cap and toggle
```

**The layering rule** (from the portal, still holds):
`db/llm/normalize` ← `scrapers/contacts/outreach` ← `pipeline/matcher` ← `api` ← `dashboard`.
Nothing imports upward. Not lint-enforced yet — [GAP-6].

---

## 9. What was dropped from the drafts, and why

| Dropped | From | Why |
|---|---|---|
| LLM supervisor agents | orchestration | Every decision is a 10-line policy. Model calls would add latency and non-determinism for nothing. |
| Envelope protocol, capability narrowing, run tree | orchestration | Solves untrusted delegation. Plain function calls don't delegate. |
| Temporal / node-cron worker process | both | APScheduler inside the API process is enough for one machine. |
| `sqlite-vec` | orchestration | Plain cosine is sub-second at this scale. |
| Postgres, RLS, LiteLLM, Nango | orchestration | Single user, single machine, one OAuth integration. |
| Hosted Claude for drafts | tools | See D3. Seam kept, not used. |
| Paid finders + verification credits | tools | See D6. Free tiers are carrying it. |
| SMTP RCPT probe | — | See D7. That draft was right; the build was wrong. |
| Bi-temporal claims, cost ledger as $ | orchestration | Local model costs ₹0. Wall-clock is the real budget. |
| Drizzle / TypeScript data layer | architecture | See D1. |

---

## 10. Known gaps, ordered by what they'd actually buy

**[GAP-1] Send budget should be a ledger, not a count.**
`sent_today()` counts `Email.status == 'sent'` rows since midnight. That's *nearly* right,
but the decrement isn't in the same transaction as the Gmail call — a crash between send
and DB write loses a send from the count. Both `JOBHUNTER-ARCHITECTURE.md` and
`MULTI-AGENT-ORCHESTRATION.md` specify a `send_budget(date, cap, used)` row locked and
decremented inside the send transaction. **They're right. Do this before the first real
send.** Small change, and the failure it prevents is one that damages the Gmail account.

**[GAP-2] Anti-fabrication is a prompt, not a check.**
`MULTI-AGENT-ORCHESTRATION.md §13` specifies evidence spans plus a deterministic auditor
that verifies every proper noun and number in a draft appears in the source material, and
**strips** what doesn't rather than rewriting it. Currently only the prompt forbids
invention. A local 4B model *will* eventually invent a repo name. The full span machinery
is heavy, but the cheap 80% is: extract proper nouns and numbers from the draft, check
each against the researcher's input, flag mismatches in the review UI. **Highest-value
correctness gap.**

**[GAP-3] Warmth tiers — the single best idea in the drafts, and it's not built.**
`JOBHUNTER-TOOLS.md §3.1` ranks contacts by relationship strength: alumni > shared OSS >
same city > same stack > content > cold > recruiter, and sorts the review queue by
**warmth rather than job score**. That doc is right that this is probably worth more than
any other single feature — a message to a fellow Newton School alum converts at a different
rate to a cold one. Costs a `warmth_tier` + `warmth_evidence` column and a ranking
function. The manual-LinkedIn-alumni CSV path in §3.4 is the safe way to feed tier 1.

**[GAP-4] `guessed` send cap and draft expiry.**
`GUESSED_SEND_CAP=5` (at most 5 of 25 to unverified addresses) and 7-day draft expiry,
both from the orchestration doc. Both are one column and one check. Currently a stale
draft about a filled role could go out and make the sender look inattentive.

**[GAP-5] Playwright scrapers — Wellfound, Cutshort, Instahyre.**
Registered and toggled off. These carry the Indian salary data the JSON boards don't,
which is what the ₹24–60 LPA filter actually needs. `JOBHUNTER-TOOLS.md §1 Tier 3` warns
their ToS may forbid automation and suggests **browsing them by hand and pasting company
names into the registry** instead. That's the cheaper and safer path — five minutes a
week, no ToS exposure, and the ATS scrapers pick the companies up.

**[GAP-6] No tests, and no layering lint.**
`JOBHUNTER-ARCHITECTURE.md` calls tests "non-negotiable, from commit one" and names it as
the thing it criticised the portal for. There are none. The highest-value ones are narrow:
salary parsing against a fixture table (that logic is subtle and already caught two bugs
during the build), scraper parsing against recorded JSON fixtures, and the ~20 hand-labelled
scoring fixtures that guard calibration when the rubric prompt changes.

**[GAP-7] Calibration is unmeasured.**
Scores rank correctly by inspection. Whether "75" means 75% is unknown and will stay
unknown until there are real outcomes. Needs an `outcomes` table and the discipline to
record what actually happened. Until then the UI should say the number is a ranking, not
a probability.

---

## 11. Build order from here

| # | Do | Why this order |
|---|---|---|
| **1** | Gmail OAuth credentials + end-to-end dry run to a second inbox | The only untested path. Everything downstream is theory until one email sends, gets replied to, and classifies correctly. |
| **2** | [GAP-1] send budget ledger | Must exist before the first *real* send, not after. |
| **3** | [GAP-4] guessed cap + draft expiry | Two small checks, both protect the account. |
| **4** | [GAP-2] fabrication check on drafts | Before volume. One invented claim is worse than fifty generic emails. |
| **5** | [GAP-6] salary + scoring fixtures | Cheapest insurance on the two subtlest pieces of logic. |
| **6** | [GAP-3] warmth tiers + alumni CSV | The biggest conversion lever. Deliberately after correctness. |
| **7** | [GAP-7] outcomes table + calibration | Only meaningful once there's a month of real replies. |
| — | [GAP-5] Playwright scrapers | Last, or never — prefer the manual-registry route. |

**Cut list if time runs short**, in order: Playwright scrapers → reply classification
(read the inbox yourself) → follow-ups (send by hand) → the funnel dashboard.
**Never cut:** the review gate, the send cap, the confidence labels.

---

## 12. Failure modes, ordered by likelihood

| # | Failure | Signal | Mitigation |
|---|---|---|---|
| 1 | **A source breaks silently** — board changes shape, scraper returns 0, nothing errors | one source's count drops to 0 while others are normal | `ScrapeStats.per_source` is recorded every run. **A source returning 0 twice running should be reported as a failure, not a quiet day.** Not yet alarmed — worth adding. |
| 2 | **The human stops reviewing** | queue depth grows, approvals → 0 | Drafts should expire at 7 days [GAP-4]. A backlog of unread drafts is pure waste. |
| 3 | **Local model degrades on long runs** | a scoring pass suddenly takes minutes per job | Caused by Ollama evicting/reloading under 8 GB pressure. Fixed by fixed `num_ctx` + `keep_alive`, but re-check if a third model is ever added. |
| 4 | **Bounces damage the sending account** | bounce rate on `pattern-guessed` | [GAP-4] caps guessed sends at 5/day. Verified-first ordering already implemented. |
| 5 | **Drafts read as templates** | reply rate flat and low | No voice check built. The review queue is the current defence — if you find yourself approving without editing, that's the signal. |
| 6 | **GitHub rate limit** — 60/hr unauthenticated | contact discovery stalls after ~3 companies | **A personal access token raises this to 5,000/hr.** Single highest-leverage config change available; currently unset. |
| 7 | **Commit mining yields nothing** for companies without public code | verified rate 0 for a company | Expected, not a bug (see D5). Site scrape is the fallback; if both fail, **skip the company rather than guess**. |

---

## 13. Non-goals — hard, enforced

| Never | Enforced by |
|---|---|
| **No logged-in LinkedIn automation** | LinkedIn is in no scraper module. A ban destroys the exact asset — being referable. |
| **No auto-apply** | There is no application-submission code path. |
| **No send without a human** | `send_email()` rejects anything not `approved`; no scheduled job calls it. |
| **No invented experience, connection or number** | Prompt-level now, [GAP-2] to make it mechanical. |
| **Max one follow-up per thread** | `Email.followup_sent`, set at queue time. |
| **No data leaves the laptop** | Local model, local SQLite, no LLM API key. Only Gmail and public read-only APIs are contacted. |
| **No contact list building** | One person, one role, one ask. No export path exists. |

On git-mined emails, plainly: commit author emails are public by design and OSS
maintainers expect contact. What keeps it acceptable is **volume and intent** — one
specific message about a real role is within norms; a hundred templated ones is not,
wherever the address came from. **The 25/day cap is what keeps this on the right side of
that line**, which is the second reason it belongs in a ledger rather than a config file.

India's DPDP Act applies to storing personal data. Personal job-hunting use is fine.
**If this ever becomes a product for other people, that changes completely** — revisit
before sharing it with anyone.

---

## 14. Still open

1. **Does 4B stay good enough as volume grows?** Ranking is right today. If reply rates
   are poor and drafts read stiff, the swap order is: better local model on a bigger
   machine → hosted model for drafting only (D3's seam). **[OPEN]**
2. **Does review actually take ten minutes?** Unmeasured — there's only been one draft.
   If it takes forty, the system has failed at its only human step. Measure before
   scaling to 25/day. **[OPEN]**
3. **Warmth vs score as the primary sort.** `JOBHUNTER-TOOLS.md` argues warmth. Untested
   because warmth isn't built. **[OPEN]**
4. **Percentile prefilter at 70 — right number?** Keeps the top 30% (~330 of 1,100).
   Chosen from the observed similarity distribution, not from outcomes. **[OPEN]**

---

## Appendix — one line

> Job hunting is mostly search, filtering and follow-up, which are machine work, plus
> judgement and voice, which are not. ZoNuLy does the machine work exhaustively and stops
> dead at the point where you're needed.

The architecture above is that sentence made structural: a deterministic pipeline that
narrows 11,000 postings to a handful of honest recommendations and real human contacts,
then spends a scarce, visible budget of 25 irreversible actions a day — every one of
which passes through you.
