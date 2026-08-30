# JobHunter — Architecture & Build Plan

> Personal project. Local only (`doc-mee/` is git-excluded).
> Written 2026-08-01. Target: working system in 4 weeks.
> Goal: ₹24–60 LPA engineering roles, sourced + referral-routed, human-approved.

---

## 0. The design brief in one line

> Do the nineteen mechanical minutes exhaustively. Stop dead at the ten seconds
> where judgement is required.

Everything below serves that. When a design decision is unclear, the tiebreaker is:
**does this let me spend my 25 daily sends better?**

---

## 1. Lessons from the MVRX portal, applied

I spent day one reading a production codebase that does almost exactly this shape of work
(scrape → score → draft → Slack → human decides). These are the things I'm copying and the
things I'm fixing.

### Copy ✅

| From the portal | Why |
|---|---|
| **Enforced one-way layering** with a lint script in pre-commit | Best part of that codebase. Makes "where does this live" unambiguous |
| **Long work never runs in an HTTP handler** | Request handlers validate + enqueue. Nothing else |
| **Human-in-the-loop as an explicit state machine** | `pending → sent_to_review → awaiting_action → done` with an *atomic claim* so double-clicks can't double-send |
| **Response caching keyed on (source + input hash) with TTL** | Their `apify_cache`. Same trick saves me real money on paid APIs |
| **Prefixed CUID2 IDs** (`job_`, `co_`, `contact_`, `draft_`) | Self-documenting in logs. Cost: nothing |

### Fix ❌

| Portal problem | My rule |
|---|---|
| `sendAnalyticsSlackMessage()` returns silently on missing config → jobs report success, nothing sends | **Fail loud, always.** Missing config throws at boot, not at call time. A stage that produces zero output records *why* |
| No tests at all — nothing tells you where it broke | **Tests from commit one.** Every stage gets a fixture-driven test. This is non-negotiable; it's the thing I criticised |
| `runClaudeAgent()` computes `costUsd`, logs it, throws it away — `tool_runs` has no cost column | **Cost is a column, not a log line.** Every LLM/API call writes tokens + cost to the DB |
| LinkedIn and Twitter duplicated ~1,400 lines; fixes don't propagate | **One implementation, sources are adapters.** Adding a job source = one adapter file, zero pipeline changes |
| Auth is an allow-list matcher → new routes unprotected by default | **Deny by default.** Localhost-bound + single API key check in middleware, public routes named explicitly |
| Third-party actor IDs hardcoded as bare strings (`Wpp1BZ6yGWjySadk3`) with no fallback | **Every external dependency behind an adapter interface** with a named, documented ID |

---

## 2. System shape

Local-first. Two processes, one SQLite file.

```
   ┌──────────────────────────────────────────────┐
   │  Next.js (localhost:3000)                    │
   │   - Review queue UI  ← where I spend 10 min  │
   │   - Job list, scores, funnel dashboard       │
   │   - API routes: validate + enqueue only      │
   └───────────────────┬──────────────────────────┘
                       │ writes jobs to queue table
                       ▼
   ┌──────────────────────────────────────────────┐
   │  SQLite  (jobhunter.db)                      │
   │   domain tables + job queue + cost ledger    │
   └───────────────────▲──────────────────────────┘
                       │ polls queue
   ┌───────────────────┴──────────────────────────┐
   │  Worker process (node)                       │
   │   - node-cron daily trigger                  │
   │   - runs pipeline stages                     │
   │   - Ollama (local) + Claude API (drafts)     │
   └──────┬────────────┬───────────┬──────────────┘
          ▼            ▼           ▼
   Job source APIs  GitHub API  Gmail API
```

**Why SQLite, not Postgres.** Single user, single machine, no concurrent writers beyond one
worker. A file I can copy, diff, and `sqlite3` into. Drizzle supports it, so the schema
knowledge transfers directly from the portal.

**Why a homegrown worker, not Trigger.dev.** Trigger.dev is cloud-hosted — it can't reach a
laptop's Ollama or a local SQLite file. A queue table plus a polling loop is ~150 lines and
fully debuggable with a breakpoint. This is the one place I deliberately don't copy the portal.

---

## 3. The pipeline

Deliberately narrowing: wide and free at the top, narrow and expensive at the bottom.

```
 [1] INGEST          thousands/day    free        ─┐
 [2] NORMALISE       dedupe, canonical            │ cheap
 [3] CHEAP FILTER    rules + embeddings           ─┘
        │  ~200 survive
 [4] DEEP SCORE      local LLM rubric             ─┐
        │  ~20 worth pursuing                      │ moderate
 [5] CONTACT FIND    GitHub, team pages           ─┘
        │  ~60 humans
 [6] EMAIL RESOLVE   verified | guessed
        │
 [7] DRAFT           hosted LLM, ~60 drafts       ─  expensive
        │
 [8] ══ REVIEW QUEUE ══  ← THE HUMAN GATE. Nothing passes unread.
        │  ≤25/day
 [9] SEND            Gmail, spaced, capped
 [10] WATCH          poll replies, classify
 [11] FOLLOW UP      exactly one, back to [8]
```

Every stage is **independently runnable** (`npm run stage:score`), **idempotent**
(re-running never duplicates), and **resumable** (crash mid-stage loses one item, not the run).
That combination is what makes it debuggable — the thing I complained the portal lacked.

### [1] Ingest — where the hidden jobs actually are

The insight that makes this work: **most startups don't build their own careers page.** They
embed an ATS, and those ATSs expose public JSON APIs. You read the same endpoint their own
website reads — no scraping, no blocking, no ToS grey area.

| Source | Endpoint shape | Notes |
|---|---|---|
| **Greenhouse** | `boards-api.greenhouse.io/v1/boards/{co}/jobs` | Biggest single win. Public, documented, free |
| **Lever** | `api.lever.co/v0/postings/{co}?mode=json` | Same deal |
| **Ashby** | public job-board API | Very common in newer startups |
| **Workable / Recruitee** | public board APIs | Long tail |
| **HN "Who is Hiring"** | HN Algolia API, monthly thread | Free-text, needs LLM parsing. High signal |
| **YC directory** | company list → their ATS boards | Great for the funded-but-unknown segment |
| **Wellfound / Instahyre / Cutshort** | India-specific | ⚠️ No clean public API. Check ToS before touching. Treat as optional |

**The bootstrapping problem:** ATS APIs are keyed by company slug, so you need a company list
first. Build it from the YC directory + funding announcements + HN threads, then probe each
company against each ATS. Store the hit in `companies.ats_provider` so you only discover once.

That company registry is the real asset here. It compounds — every week it gets better.

### [3] Cheap filter

Two passes, both nearly free:

1. **Rules** — location/remote-eligible, discipline, obvious seniority disqualifiers
   ("15+ years", "Director"), posting age.
2. **Embeddings** — one vector for my resume, one per posting (local `nomic-embed-text` via
   Ollama). Cosine similarity, keep the top N.

Deliberately **generous**. A false negative here is invisible forever — I never learn about
the job I filtered out. False positives just cost a bit of stage-4 compute. Tune loose.

### [4] Deep score — the honest number

Local LLM against a fixed rubric. Output is structured, validated with Zod:

```
{ screenOdds: 0..100, stackOverlap, seniorityFit, earlyCareerSignals,
  domainProximity, reasoning: string, gaps: string[] }
```

**Calibration rule, and this is the whole point:** the score estimates
*probability of getting a first screen* — **not** how well I match on paper. A Staff role
where I know every listed technology scores **low**, because I would not get that screen.
A founding-engineer role at a Series A with imperfect stack overlap scores **high**, because
those companies hire for trajectory.

A flattering score is worse than useless — it costs a week of applications.

**Guard against drift:** keep ~20 hand-labelled postings as a fixture set. Any prompt change
gets re-run against them. If calibration moves, I see it immediately. This is the test suite
for the part that has no obvious test.

### [5–6] Contact discovery + email resolution

Sources, best-first:

1. **Git commit authorship.** Public repos expose author emails in commit metadata. Real, and
   how git has always worked.
2. **GitHub profile** `email` field, when public.
3. **Company team / about / careers pages.**
4. **Pattern inference** — with 3+ verified addresses on a domain, infer
   `first.last@` / `first@` and apply. **Always labelled `guessed`.**

> ⚠️ **De-risk this in week 1, not week 3.** GitHub now defaults new accounts to
> `users.noreply.github.com`, so the commit-email hit rate is materially lower than it was a
> few years ago — plausibly 20–40% on active repos, and worse for companies that squash-merge.
> **The entire referral premise depends on this number.** Write a throwaway script in week 1
> against 20 real target companies and measure it. If it comes back at 5%, the strategy has to
> change (lean on team pages + pattern inference, or accept fewer/higher-quality targets) —
> and I need to know that in week 1, not after building three weeks of pipeline on top of it.

**Confidence is a first-class field**, not a note:

- `verified` — from a real commit or public profile
- `guessed` — pattern-constructed, plausible, unconfirmed

Rank sends by confidence. A bounce wastes one of 25 *and* dings sender reputation. Since
budget is available: pay for a verification API on the `guessed` tier — cheaper than a burned
send.

### [7] Draft — the anti-fabrication rule

Input: the person's public work (repos, bio) + my real background + the posting.
Output: 120–150 words, plain text, one specific concrete hook.

**Hard constraint, enforced in code and not just the prompt:**

> Never invent a project, a metric, a mutual connection, or a shared experience.
> If public material is too thin to say something specific, say something *generic and true*.

A generic honest email is recoverable. A fabricated flattering one is not — and the recipient
notices immediately, because it's their own work being described wrongly.

**Enforcement, not just instruction:** post-generation validator checks that every proper noun
and every number in the draft appears in the source material passed in. Anything unmatched →
flag the draft in the review UI. Prompts drift; validators don't.

This is the one stage where I'd use a **hosted model (Claude)** rather than local. It's ~60
drafts/day, quality is the entire product, and a locally-run 8B model writes noticeably
stiffer prose. Everything upstream stays local.

> Honest trade-off against my own spec: this means draft-stage data (my background + their
> public bio) leaves the laptop. Scoring, resume, and the full job corpus stay local. I think
> that's the right split — but it *is* a deviation from "nothing leaves the machine," so it's
> a conscious choice, not an oversight.

### [8] Review queue — the only screen that matters

The one place a human is required, so it gets the design effort:

- Draft, recipient, their public work, the job, the score, and **why** the score
- Confidence badge (`verified` / `guessed`) prominent
- Inline edit — most drafts need one line changed, not a rewrite
- Approve / Reject / Edit+Approve, keyboard-driven (`j` `k` `a` `r`)
- **Remaining daily budget visible and depleting, on every screen**

Target: 10 minutes/day. If it takes 30, the tool has failed regardless of pipeline quality.

### [9] Send — the constraint everything bends around

```
hard cap        25/day, enforced in the DB, not just the UI
spacing         randomised 4–12 min between sends
window          09:30–18:00 IST, weekdays only
format          plain text. no HTML, no tracking pixel, no link shortener
transport       Gmail API (OAuth) — needed for threading + reply reads
opt-out         one plain line: "happy to drop it if this isn't welcome"
```

Not arbitrary. A personal Gmail sending 200 lookalike messages in an hour gets flagged, and
**the account that gets flagged is the same account interviews arrive at.** The cap protects
the asset.

**Implementation detail that matters:** the budget ledger is a table with a unique constraint
on `(date, slot)`. Not a counter that a retry can double-decrement. The portal's engagement
bot got this right with its atomic status claim — same idea, same reason.

### [10–11] Replies and follow-up

Poll Gmail threads → classify into `positive` / `negative` / `role_closed` / `unclear`.
`unclear` routes to me; I don't want an LLM deciding what a hedged reply meant.

Silent for 5 days → draft **exactly one** follow-up → **back into the review queue**.
Never two. A second follow-up converts almost nothing and costs the relationship.

---

## 4. Schema sketch

```
companies          id, name, domain, ats_provider, ats_slug, funding_stage,
                   github_org, discovered_at

jobs               id, company_id, source, source_job_id, title, description,
                   location, remote, posted_at, url, raw_json
                   UNIQUE(source, source_job_id)          ← dedupe

job_scores         id, job_id, screen_odds, stack_overlap, seniority_fit,
                   early_career_signals, domain_proximity, reasoning, gaps,
                   model, rubric_version, scored_at
                                                          ← rubric_version = recalibration

contacts           id, company_id, name, github_login, role, seniority,
                   public_work_summary

contact_emails     id, contact_id, email, confidence('verified'|'guessed'),
                   source, verified_at
                   UNIQUE(contact_id, email)

drafts             id, contact_email_id, job_id, subject, body,
                   status('pending'|'approved'|'rejected'|'sent'),
                   validator_flags, generated_at, reviewed_at

sends              id, draft_id, gmail_thread_id, sent_at, send_date, slot
                   UNIQUE(send_date, slot)                ← the 25/day ledger

replies            id, send_id, received_at, body,
                   classification, needs_human

followups          id, send_id, draft_id, scheduled_for, sent  ← max 1 per send

api_costs          id, stage, provider, model, tokens_in, tokens_out,
                   cost_usd, run_id, created_at           ← the portal's missing column

job_queue          id, stage, payload, status, attempts, last_error,
                   created_at, started_at, finished_at
```

`api_costs` exists from day one specifically because the portal doesn't have it, and the
result is nobody there can answer "which stage costs the most."

---

## 5. Layering (the rule I'm copying)

```
lib/  ──▶  pipeline/  ──▶  app/api/  ──▶  app/ + components/
```

- `lib/` — db, schema, adapters (sources, github, gmail, llm), pure scoring logic. **Imports nothing above it.**
- `pipeline/` — the 11 stages. Imports `lib/`. **Never imports `app/`.**
- `app/api/` — validate + enqueue. Never runs a stage inline.
- `app/` + `components/` — UI. Talks to API routes only.

Enforced by a `lint-architecture.sh` copied from the portal and wired into pre-commit.
Plus the portal's other pre-commit rule: **no `console.log` in `pipeline/`** — structured
logger only, because that's what makes a failed overnight run diagnosable.

**Adapter interface** so sources aren't duplicated the way LinkedIn/Twitter were:

```ts
interface JobSource {
  id: string;
  fetchJobs(since: Date): Promise<RawPosting[]>;
  normalise(raw: RawPosting): NormalisedJob;
}
```

Adding Ashby = one file in `lib/sources/`, registered in an array. Zero pipeline changes.
This is the direct fix for the portal's 1,400 duplicated lines.

---

## 6. Four-week plan

Part-time, alongside coursework. Scoped to be finishable, not impressive.

### Week 1 — Ingest + the risk spike
- [ ] **Day 1: the GitHub email hit-rate spike.** 20 target companies, measure it. Everything
      downstream depends on this number
- [ ] Next.js + Drizzle + SQLite skeleton, layering lint in pre-commit
- [ ] Company registry + ATS probe
- [ ] Greenhouse + Lever adapters
- [ ] Normalise + dedupe
- [ ] **Deliverable: a table with 500+ real jobs I'd never have seen**

### Week 2 — Scoring
- [ ] Ollama wired, embeddings filter
- [ ] Rubric prompt + Zod-validated structured output
- [ ] 20 hand-labelled fixtures + calibration test
- [ ] Job list UI, sortable by score, with reasoning visible
- [ ] `api_costs` recording from the first LLM call
- [ ] **Deliverable: open a page, see 20 jobs worth my time, ranked honestly**

### Week 3 — Contacts + drafts
- [ ] GitHub commit-email extraction, profile fallback
- [ ] Team-page parse + pattern inference, confidence labelling
- [ ] Draft generation (Claude) + **fabrication validator**
- [ ] Review queue UI, keyboard-driven
- [ ] **Deliverable: 20 drafts I'd actually be willing to send**

### Week 4 — Send + watch
- [ ] Gmail OAuth, send with spacing + window
- [ ] Budget ledger with the unique constraint
- [ ] Reply polling + classification
- [ ] Single follow-up scheduler
- [ ] Funnel dashboard
- [ ] **Deliverable: end-to-end, running daily, unattended overnight**

### Cut list, in order, if behind
1. Funnel dashboard → read the SQLite directly
2. Follow-ups → do them by hand
3. Reply classification → read the inbox myself
4. HN + YC sources → Greenhouse + Lever alone is enough volume
5. Pattern inference → `verified` contacts only, fewer but better

**Never cut:** the review gate, the fabrication validator, the 25/day ledger, the tests.
Those are the things that make it safe to run unattended.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **GitHub email hit rate too low** | 🔴 kills the premise | Spike it day 1. Fall back to team pages + inference |
| Scoring is flattering, not calibrated | 🔴 wastes weeks | Fixture set + `rubric_version`. Re-test on every prompt change |
| Gmail flags the account | 🔴 loses the interview inbox | 25/day, spacing, plain text, no pixels, real opt-out |
| Drafts read as templated | 🟠 zero replies | Specific hook required; validator flags thin drafts for manual attention |
| ATS APIs change shape | 🟠 silent breakage | Adapters + contract tests on stored fixtures |
| Scope creep past 4 weeks | 🟠 nothing ships | The cut list above, honoured |
| Cost runs away | 🟡 | `api_costs` from day 1 + a hard monthly ceiling in config |

**On the people side:** these are public addresses, but a job-referral ask is not what someone
publishing commits was expecting. That's fine — it's normal professional outreach — but it
earns an obligation: be short, be specific, make the opt-out real and honour it instantly. One
follow-up maximum, permanent suppression on any negative reply.

Worth a note that India's DPDP Act applies to storing personal data. Personal job-hunting use
is fine. **If this ever becomes a product, that changes completely** — revisit before sharing
it with anyone.

---

## 8. Why this architecture, in one paragraph

The pipeline narrows because compute should be spent where decisions are irreversible. The
human gate sits at the last reversible moment. Every stage is independently runnable because
the thing I criticised in the portal was that a bug could be anywhere. Failures are loud
because the portal's worst bug was one that reported success. Cost is a column because theirs
isn't and nobody there can answer the cost question. And the 25/day ceiling isn't a limitation
I'm working around — it's the constraint that makes every upstream decision meaningful.
