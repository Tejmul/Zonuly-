# JobHunter — Multi-Agent Orchestration Architecture

> **STATUS: this is a design document, not a description of running code.**
> Nothing here has been built yet. It describes the intended architecture of
> **JobHunter**, a local-first, single-user pipeline that finds engineering roles,
> scores them honestly against one person's resume, finds real humans to ask for a
> referral, drafts the ask, and **stops** at a human approval gate.
>
> Structural patterns are borrowed deliberately from `gtm-os` (the agentic GTM
> operating system in this repository) — the proposal/HITL write path, evidence-bound
> generation, the durable run ledger, capability-gated tools. Those patterns were read
> out of the **code** (`services/agents/src/gtm_agents/capabilities.py`, `budgets.py`,
> `faithfulness.py`, `tools/`), not only the prose docs — where the two disagree, §6 and
> §15 follow the code and say so. What is **not** borrowed
> is everything that exists because gtm-os is a multi-tenant cloud SaaS: Postgres RLS,
> Temporal Cloud, LiteLLM routing, Nango. JobHunter runs on one laptop for one person.
> Section 15 states each divergence and why.
>
> **Reading the annotations:**
> - **[DECISION]** — a settled architectural choice with a stated reason.
> - **[TARGET]** — an intended number (throughput, cost, latency). Illustrative until measured.
> - **[OPEN]** — genuinely undecided. Do not treat as settled.

---

## TABLE OF CONTENTS

1. [The 60-second version](#1-the-60-second-version)
2. [Glossary — 14 words you must know](#2-glossary--14-words-you-must-know)
3. [Why a hierarchy at all](#3-why-a-hierarchy-at-all)
4. [The hierarchy — four tiers](#4-the-hierarchy--four-tiers)
5. [The agent roster — every agent, its contract](#5-the-agent-roster--every-agent-its-contract)
6. [Architecture — the 8 decisions that define this system](#6-architecture--the-8-decisions-that-define-this-system)
7. [The delegation protocol](#7-the-delegation-protocol)
8. [Escalation, failure and partial results](#8-escalation-failure-and-partial-results)
9. [The data model](#9-the-data-model)
10. [Data flow diagram](#10-data-flow-diagram)
11. [The daily cycle, hour by hour](#11-the-daily-cycle-hour-by-hour)
12. [Budget as a first-class resource](#12-budget-as-a-first-class-resource)
13. [The evidence system — how "don't lie" is enforced mechanically](#13-the-evidence-system--how-dont-lie-is-enforced-mechanically)
14. [Tech stack](#14-tech-stack)
15. [What we take from gtm-os and what we drop](#15-what-we-take-from-gtm-os-and-what-we-drop)
16. [Configuration and secrets](#16-configuration-and-secrets)
17. [Failure modes — what breaks first](#17-failure-modes--what-breaks-first)
18. [Explicit non-goals and hard limits](#18-explicit-non-goals-and-hard-limits)
19. [Build order](#19-build-order)
20. [Open questions](#20-open-questions)

---

## 1. The 60-second version

**JobHunter is a funnel with a human valve at the end of it.**

Every night it pulls thousands of job postings from the places startups actually post
(the ATS APIs behind their own careers pages, the monthly HN hiring thread, remote
feeds, the YC directory), throws away the obvious no's with cheap rules, reads the
survivors with a local LLM against a scoring rubric, finds real engineers at the good
companies, resolves their real email addresses from public git history, drafts one
honest referral ask per person, and **queues all of it for a human**.

Nothing is sent without a person reading it and pressing approve. The ceiling is
**25 emails a day**, and that single constraint is what gives the architecture its
shape: because sends are scarce and irreversible, every upstream decision is a
resource-allocation decision.

**Four sentences to remember:**

1. **The orchestrator is code, not a model.** The top of the hierarchy is a
   deterministic, resumable state machine. Agents live *underneath* it. [DECISION]
2. **The funnel is a cost gradient.** Each tier down is roughly 10× more expensive per
   item and processes roughly 10× fewer items. Cheap filters run first, always.
3. **Nothing an agent writes is trusted.** Drafts land in a review queue; a
   deterministic evidence checker runs before a human ever sees them.
4. **`send_email` is not a capability any agent holds.** It is reachable only from the
   approval path. This is enforced in the tool layer, not requested in a prompt.

### Shape of the system

```
┌──────────────────────────────────────────────────────────────────┐
│                    CONDUCTOR  (deterministic)                    │
│         cron → daily cycle state machine → run ledger            │
└───┬──────────┬───────────┬────────────┬───────────┬──────────────┘
    │          │           │            │           │
┌───▼────┐┌────▼────┐┌─────▼─────┐┌─────▼─────┐┌────▼──────┐
│ SCOUT  ││ TRIAGE  ││  CONTACT  ││ OUTREACH  ││ FEEDBACK  │   Tier 1
│  sup.  ││  sup.   ││   sup.    ││   sup.    ││   sup.    │   supervisors
└───┬────┘└────┬────┘└─────┬─────┘└─────┬─────┘└────┬──────┘
    │          │           │            │           │
  workers    workers     workers      workers     workers        Tier 2
    │          │           │            │           │
    └──────────┴─────┬─────┴────────────┴───────────┘
                     │
        ┌────────────▼────────────┐   ┌──────────────────┐
        │  SQLite + sqlite-vec    │   │  Ollama (local)  │        Tier 3
        │  artifacts / runs / …   │   │  llm + embed     │        tools
        └─────────────────────────┘   └──────────────────┘
                     │
        ┌────────────▼─────────────────────────────────┐
        │  REVIEW QUEUE  →  human  →  gmail send (≤25) │
        └──────────────────────────────────────────────┘
```

### Scale, per day [TARGET]

| Stage | Items in | Items out | Cost per item | Who does it |
|---|---|---|---|---|
| Source | — | ~3,000 postings | ~0 (HTTP) | Scout workers |
| Rule gate | 3,000 | ~800 | ~0 (regex/SQL) | deterministic |
| Embedding gate | 800 | ~120 | ~1 ms local | local embed |
| Fit judge | 120 | ~40 scored | ~8 s local LLM | Fit Judge |
| Contact hunt | ~15 companies | ~45 contacts | ~20 s | Contact workers |
| Draft | ~30 contacts | ~30 drafts | ~15 s local LLM | Drafter |
| **Human review** | 30 | ≤25 approved | **~10 s each** | **you** |
| Send | ≤25 | ≤25 | — | approval path only |

Total wall clock for an unattended nightly run: **~45–70 minutes** on an M-series
laptop [TARGET]. Total marginal cash cost: **₹0** — local model, free APIs.

---

## 2. Glossary — 14 words you must know

| Term | Meaning |
|---|---|
| **Conductor** | The top-level deterministic state machine. Owns the daily cycle, the run ledger, and budget allocation. **Not an agent** — it contains no LLM call. |
| **Supervisor** | A Tier-1 agent that owns one stage of the funnel. Decides fan-out, allocates its stage's budget, aggregates worker results, degrades gracefully on partial failure. |
| **Worker** | A Tier-2 agent. Narrow, stateless, one job, small tool surface. Never calls another agent. |
| **Artifact** | One fetched document, stored immutably: a posting body, a team page, a README, a bio, a reply email. Has `content`, `content_hash`, `fetched_at`, `source_url`, `embedding`. The **episodes** analogue from gtm-os. |
| **Evidence span** | `(artifact_id, start_char, end_char)` — a pointer to the exact text a generated claim rests on. Every specific statement in a draft carries one. |
| **Faithfulness gate** | A deterministic pre-review check: any sentence in a draft asserting a specific fact must carry an evidence span whose text actually supports it. Unsupported specifics are **stripped**, not rewritten. |
| **Screen odds** | The scorer's output: estimated probability of getting a first-round screen. Calibrated to be pessimistic. A number plus reasons plus gaps. |
| **Confidence label** | On a contact's email: `verified` (came from a real commit or public profile), `derived` (built from a pattern confirmed by ≥2 verified examples at that company), `guessed` (constructed, nothing confirms it). Never collapsed, never hidden in the UI. |
| **Send budget** | The 25/day ledger. A row in the database, decremented transactionally inside the send. Not a config constant. |
| **Review queue** | The single human gate. Drafts sit here until approved, edited-and-approved, or rejected. The **only** path to `send_email`. |
| **Run** | One agent invocation, recorded in the `runs` ledger: agent, parent, input, status, per-step log, tokens, wall clock, cost. Resumable. |
| **Envelope** | The typed request/response contract between a supervisor and a worker. Carries budget, capabilities, deadline, and parent run id. |
| **Circuit breaker** | Per-source failure counter. Three consecutive failures on a source disables it for the rest of the cycle and records why. One dead source never kills a run. |
| **Egress allowlist** | The hard-coded list of hosts the fetch tool may reach. Anything else is refused. This is what "your data doesn't leave the laptop" actually means in code. |

---

## 3. Why a hierarchy at all

The honest question is: why not one agent with fifteen tools and a long prompt?

Because the four problems in the funnel fail differently, cost differently, and need
different amounts of trust. Flattening them into one loop means the cheapest failure
and the most expensive failure share a blast radius.

| Reason | What flat costs you |
|---|---|
| **Cost gradient** | A single agent decides for itself when to stop being cheap. It won't. It will read all 3,000 postings with the LLM because that's the easy path, and the nightly run becomes an eight-hour run. Tiering makes "cheap first" structural instead of a request. |
| **Blast radius** | A scraper returning garbage should degrade *sourcing*. In a flat loop it poisons the context that also writes the emails. |
| **Context budget** | 3,000 postings do not fit in a context window, and shouldn't. Each tier hands down a *smaller, typed* payload. The Drafter sees one contact and one role, not the day. |
| **Auditability** | "Why did this email get written?" must resolve to a chain of run ids. One flat run gives you one opaque transcript. |
| **Resumability** | The laptop closes at 3am. Tiering gives natural checkpoints — sourcing done, triage done — so the morning resume replays minutes, not the whole night. |
| **Model tiering** | Scoring wants a 14B model with a rubric. Reply classification wants a 3B model and 200ms. Drafting wants the best local model available. One agent means one model for all three. |
| **Trust asymmetry** | The Drafter touches text a human will send under their own name. The Board Scout touches JSON. These deserve different guardrails, and guardrails attach to agents. |

**The counter-argument, stated fairly:** hierarchy costs you cross-stage insight. A flat
agent might notice while drafting that a role's requirements contradict the score, and
revise. JobHunter handles that with an explicit backward edge — the Drafter can raise a
`contradiction` escalation that returns the role to Triage for re-scoring — rather than
by dissolving the tiers. [DECISION]

---

## 4. The hierarchy — four tiers

```
TIER 0   CONDUCTOR                      deterministic Python. No LLM.
         │                              Owns: cycle state, budget, run ledger, resume.
         │
TIER 1   SUPERVISORS (5)                LLM-backed, but thin. Plan + allocate + aggregate.
         │                              Own: fan-out width, stage budget, partial-failure policy.
         │                              May call workers. May NOT call tools that write.
         │
TIER 2   WORKERS (18)                   Narrow, stateless, one job each.
         │                              Own: nothing. Receive an envelope, return a result.
         │                              May call tools. May NOT call other agents.
         │
TIER 3   TOOLS                          Deterministic functions. No model.
                                        Capability-gated. Every call is logged.
```

### The rules that make the tiers mean something

| Rule | Enforced by |
|---|---|
| A worker may never invoke another agent. | The agent registry: worker envelopes are issued without a `spawn` capability. |
| A supervisor may never call a mutating tool directly. | Capability set: supervisors hold `spawn` + `read`, never `write`. |
| The conductor contains no LLM call. | Code review + a lint rule banning `llm.*` imports in `conductor/`. |
| Every agent call is bounded. | The envelope carries `max_tool_calls`, `max_tokens`, `deadline_s`. The runtime trips them, not the prompt. |
| Depth is capped at 2. | Conductor → Supervisor → Worker. There is no Tier-3 agent. A worker needing a sub-worker is a design error to be fixed by splitting the stage. [DECISION] |

**Why cap depth at 2:** unbounded delegation is where multi-agent systems become
untraceable and expensive. Two levels is enough to express every stage in this funnel,
and it makes the run tree readable in a single screen.

---

## 5. The agent roster — every agent, its contract

### Tier 1 — Supervisors

| Supervisor | Owns | Decides | Fan-out |
|---|---|---|---|
| **Scout** | Discovery | Which sources to run tonight, which to skip (circuit breaker), how to dedupe across sources | 8 workers, parallel |
| **Triage** | Filtering + scoring | How deep to score (how many survive to the LLM), when to stop early because the day's shortlist is full | 3 workers, sequential gates |
| **Contact** | Finding humans | Which companies get a contact hunt (only the top-scoring), which method to try per company, when to give up | 5 workers, parallel per company |
| **Outreach** | Drafting | Which contacts get a draft given the remaining send budget, draft ordering, when to skip a contact for weak evidence | 4 workers, sequential per contact |
| **Feedback** | The loop closing | Which threads are stale, which need the single follow-up, when to trigger recalibration | 3 workers |

A supervisor's prompt is short and structural. It does not know how to parse a job
board or write an email — it knows how many workers to run, what to do when three of
them fail, and what a good aggregate looks like. **[DECISION]** Keeping supervisors
thin is what stops the hierarchy from having two layers that both try to do the work.

### Tier 2 — Workers

#### Sourcing (under Scout)

| Worker | Kind | Input | Output | Notes |
|---|---|---|---|---|
| **ATS Scout** | deterministic | board slug list | raw postings | One implementation, many tenants of it: Greenhouse / Lever / Ashby / Workable all expose a public JSON board endpoint. This is the highest-yield source and it needs no LLM. |
| **HN Thread Parser** | LLM (small) | monthly "Who is hiring" thread HTML | structured postings | The one source that genuinely needs a model — freeform comments, no schema. |
| **Remote Feed Scout** | deterministic | RemoteOK / WeWorkRemotely feeds | raw postings | |
| **YC Directory Scout** | deterministic | YC company + jobs directory | raw postings + funding stage | Funding stage feeds the scorer: Series A founding-engineer roles score differently. |
| **Company Resolver** | LLM (small) + rules | posting cluster | canonical `company_id` | Same company appears as "Acme", "Acme Inc.", "acme.com". Rules first (domain match); model only for the residue. |

#### Triage (under Triage)

| Worker | Kind | Input | Output | Notes |
|---|---|---|---|---|
| **Rule Gate** | deterministic | ~3,000 postings | ~800 | Discipline, seniority keywords, geography, posting age, duplicate hash. Pure SQL. Runs in seconds. |
| **Embedding Gate** | local embeddings | ~800 | ~120 | Cosine similarity of posting text vs a resume-derived profile vector. Top-K, not a threshold — thresholds drift, K is stable. |
| **Fit Judge** | LLM (mid) | one posting + resume | `screen_odds`, `reasons[]`, `gaps[]`, `rubric_version` | The expensive, careful read. See below. |
| **Calibration Auditor** | LLM (mid), weekly | scored roles + actual outcomes | rubric adjustment proposal | Runs against `outcomes`. Its output is a **proposal a human accepts** — the rubric is never silently rewritten. |

**The Fit Judge is the heart of the system and deserves its own note.** It scores
against a fixed written rubric, not vibes: stack overlap (how much of the required
stack the candidate has actually shipped), the years-of-experience barrier (is it a
real gate or boilerplate), early-career signal (does the posting welcome it), domain
proximity, and company stage. It emits **calibrated-pessimistic** odds: a Staff role at
a large company scores low even on perfect stack overlap, because that screen will not
happen. A founding-engineer role at a Series A scores high on imperfect overlap,
because those companies hire trajectory. **The score's job is to stop you spending a
week on the wrong ten applications**, so a flattering score is a bug, not a kindness.

#### Contact (under Contact)

| Worker | Kind | Input | Output | Notes |
|---|---|---|---|---|
| **Commit Miner** | deterministic | company GitHub org | `verified` emails | The best free source. Public commits carry author emails by design — this is how git works and how OSS maintainers expect contact. Highest-confidence tier. |
| **Page Reader** | LLM (small) | team/about/careers HTML | names + roles | Extraction only. Never invents a name. |
| **Pattern Inferencer** | deterministic | ≥2 verified emails at a company | pattern + `derived` emails | `first.last@`, `flast@`, `first@`. Requires **two** confirming examples before it will apply a pattern. One example is a coincidence. |
| **Deliverability Checker** | deterministic | candidate email | pass/fail + reason | MX record check, syntax, disposable-domain list, role-account filter (`info@`, `careers@` are rejected — they're a black hole). |
| **Contact Ranker** | rules | all candidates for a company | ordered list | Sorts by confidence tier first, then role relevance (an engineer on the team you'd join beats a recruiter), then seniority (mid-level engineers reply more than VPs). |

#### Outreach (under Outreach)

| Worker | Kind | Input | Output | Notes |
|---|---|---|---|---|
| **Persona Reader** | LLM (small) | target's public repos + bio | 3–5 specific, cited observations | Each observation carries an evidence span or it is discarded. |
| **Drafter** | LLM (best local) | persona notes + resume + role | subject + body + evidence spans | Must cite. See §13. |
| **Faithfulness Auditor** | deterministic + LLM | draft + its spans | pass / stripped draft / reject | The gate. Deterministic span-existence check first; model check for *support* second. |
| **Voice Checker** | LLM (small) | draft + corpus of previously approved drafts | similarity score + flagged lines | Learns the user's voice from what they actually approved. Cold-start: no corpus, no check, flag as unchecked. |

#### Feedback (under Feedback)

| Worker | Kind | Input | Output | Notes |
|---|---|---|---|---|
| **Reply Classifier** | LLM (small) | reply email | `yes` / `no` / `role_gone` / `unclear` | Cheapest agent in the system. `unclear` is a legitimate answer and routes to the human — a forced guess here is worse than an admission. |
| **Follow-up Drafter** | LLM (mid) | silent thread ≥5 days | one follow-up draft | **One. Ever.** Enforced by a `followup_count` column with a CHECK constraint, not by a prompt. |
| **Funnel Analyst** | LLM (mid), weekly | the whole funnel | rollup: reply rate by role type, by framing, by confidence tier | This is the thing that makes job hunting adjustable instead of hopeful. |

---

## 6. Architecture — the 8 decisions that define this system

### Decision 1 — The orchestrator is deterministic code, not an agent

The conductor is a state machine over the cycle stages, persisted after every
transition. It contains **zero** LLM calls.

**Why:** a non-deterministic top level means the nightly run isn't reproducible, isn't
resumable at a known point, and can't be reasoned about when it costs 90 minutes
instead of 45. gtm-os reaches the same conclusion with Temporal workflows: the
*orchestration* is durable code, the *judgement* is in activities beneath it.
JobHunter keeps the pattern and drops the infrastructure (§15).

```python
STAGES = ["source", "triage", "contact", "draft", "audit", "queue", "feedback"]
# Each transition is a committed row in cycle_state. Crash → resume at last committed.
```

### Decision 2 — The funnel is a cost gradient, enforced structurally

Cheap filters run first and the ordering is not a prompt instruction, it is the shape
of the pipeline. No LLM sees a posting that a regex could have rejected.

**Why:** this is the difference between a 45-minute nightly run and one that never
finishes. It also makes the system's cost predictable: LLM calls per night are bounded
by the *gate widths*, which are configuration, not model behaviour.

### Decision 3 — The 25/day send budget is a ledgered resource, not a constant

`send_budget(date, cap, used)` is a table. The `send_email` tool decrements it **inside
the same transaction as the send**. A decrement that would exceed the cap aborts the
send. Every screen displays remaining budget.

**Why:** the cap protects the Gmail account you need for the actual interviews. A
personal account sending 200 lookalike messages in an hour gets flagged, and losing it
destroys the whole strategy. A number in a config file gets edited at 1am; a
transactional ledger doesn't. See §12.

### Decision 4 — HITL is the architecture, and `send` is a named capability nobody holds

No agent — not the Drafter, not the Outreach Supervisor, not the Conductor — holds a
capability that sends mail. `send_email` is reachable only from the approval handler,
which requires an `approvals` row with `decision='approved'` and a human actor.

**Why, and the precise shape, from the reference implementation:** gtm-os's
`services/agents/src/gtm_agents/capabilities.py` defines `EXECUTE_OUTREACH` as a real
enum member with the comment *"Reserved — no role holds this in v1. Guarded here so
future outreach execution lands as an explicit grant, not a silent capability
broadening."* Exactly one role has since been granted it (`email-composer`) — **and it
still cannot send**: it composes and *proposes* through the connector-action framework
with `hitl=required`, so the proposal lands in `/review`.

That is a sharper pattern than simply omitting the capability, and JobHunter copies it:
name the dangerous capability, grant it to nobody, and make any future grant a visible
one-line diff rather than an absence nobody notices changing.

### Decision 4b — Nothing is silently auto-rejected

Low-confidence items route to the human. They are not dropped.

**Why:** gtm-os's `budgets.py` is explicit about this — there are two thresholds
(auto-approve at 0.85, HITL-route at 0.70) and **no auto-reject constant**, with a
pytest gate (`test_no_auto_reject_threshold_exists`) that fails loudly if one is
reintroduced. The stated reason: *"Re-introducing an auto-reject knob would silently
drop proposals the reviewer was supposed to see."*

For JobHunter this matters most at the Fit Judge. A low `screen_odds` **ranks a role
last; it does not delete it.** The user may know something the rubric doesn't. The only
things ever deleted are expired drafts (§9) and postings the deterministic Rule Gate
rejected on hard facts (wrong continent, wrong discipline) — never on a model's
judgement. [DECISION]

### Decision 5 — Evidence-bound generation

Every specific claim in a draft carries `(artifact_id, start_char, end_char)`. A
deterministic checker verifies the span exists and a model verifies it *supports* the
claim. Unsupported specifics are **stripped**, leaving honest-generic text.

**Why:** a generic honest email is recoverable; a flattering fabricated one is not, and
the recipient will notice. Mechanically this is gtm-os's faithfulness gate — reject any
claim whose evidence span isn't literally present in its cited source. Full mechanism
in §13.

### Decision 6 — Confidence is a column, never collapsed

`verified` / `derived` / `guessed` travels with every contact from extraction through
the UI to the send decision, and constrains it: **at most 5 of the day's 25 sends may
go to `guessed` addresses.** [TARGET]

**Why:** bounces are the main way this system damages the account it depends on. And
the user's scarcest resource is 25 sends — spending them on addresses that won't arrive
is the single most expensive mistake available.

### Decision 7 — Local-first, with an egress allowlist

The model runs on the laptop (Ollama). Storage is a local SQLite file. Network egress
is restricted to a hard-coded allowlist: the job board APIs, GitHub, company domains
resolved from postings, and the Gmail API. The fetch tool refuses everything else, and
refuses private/link-local addresses (SSRF guard, same as gtm-os's `web_fetch`).

**Why:** the resume, the targets, and the drafts are the user's job search. "It doesn't
send your data anywhere" has to be a code path, not a promise.

### Decision 8 — Immutable artifacts, re-derivable everything else

Fetched documents are append-only with a `content_hash`. Scores, contacts, and drafts
are **derived** and carry the `rubric_version` / `prompt_version` that produced them.
Improving the rubric means re-deriving, not migrating.

**Why:** the rubric *will* be wrong at first, and calibration is the whole point of the
Calibration Auditor. If scores aren't cheaply re-derivable, calibration never happens.
This is gtm-os's append-only episode layer, minus the bi-temporal machinery, which
solves a problem (auditing what the system believed on a past date, for a customer)
JobHunter doesn't have. [DECISION]

---

## 7. The delegation protocol

Every supervisor→worker call is a typed envelope. This is the contract that makes the
hierarchy inspectable.

```jsonc
// REQUEST
{
  "task_id":       "t_01H…",
  "parent_run_id": "r_01H…",          // links the run tree
  "agent":         "fit_judge",
  "input":         { "posting_id": 4471 },   // validated against the agent's input schema
  "budget": {
    "max_tokens":     8000,
    "max_tool_calls": 6,
    "deadline_s":     45
  },
  "capabilities":  ["read_artifacts", "llm"],   // NOT a superset of the parent's
  "prompt_version": "fit_judge@v3",
  "rubric_version": "rubric@2026-08-01"
}
```

```jsonc
// RESPONSE
{
  "task_id": "t_01H…",
  "status":  "ok",            // ok | partial | failed | escalated
  "output":  { "screen_odds": 0.34, "reasons": [...], "gaps": [...] },
  "evidence": [ {"artifact_id": 9912, "start": 1204, "end": 1361} ],
  "cost":    { "tokens_in": 5210, "tokens_out": 380, "wall_ms": 8140 },
  "escalation": null          // or { "kind": "contradiction", "detail": "…" }
}
```

**Four properties this buys:**

1. **Budgets are runtime-enforced.** A worker that exceeds `max_tool_calls` is
   terminated by the runtime and returns `partial`. The prompt is not asked to behave.
2. **Capabilities are narrowed on the way down, never widened.** A worker cannot be
   granted something its supervisor doesn't hold. Checked at envelope construction.
3. **Every run is a node in a tree.** `parent_run_id` makes "why did this email exist?"
   a single recursive query.
4. **Versions travel with results.** A score carries the rubric that produced it, so
   re-derivation is well-defined.

### Three details lifted directly from the reference implementation

**1. The budget triple is exactly gtm-os's `BudgetSpec`.** That codebase settled on
`(max_tool_calls, max_input_tokens, wall_clock_seconds)` as a frozen dataclass, enforced
at three layers simultaneously: the agent-loop usage limits, the workflow timeout, and a
pre-call check. JobHunter uses the same triple for the same reason — any one layer alone
has a hole. Note gtm-os's budgets are also `frozen=True` specifically so a downstream
activity cannot mutate a profile at runtime; the envelope here is likewise immutable
once constructed. [DECISION]

**2. Adopt the `first_run` / `rerun` split.** gtm-os gives each role two budget profiles
because first-time deep research legitimately costs far more than a re-check. JobHunter
has the same asymmetry, most sharply in the Contact stage: the first time a company is
seen, the Commit Miner does a shallow clone and a full history scan; on the next
sighting it only needs the delta.

```python
CONTACT_BUDGET = AgentBudgetProfile(
    first_run=BudgetSpec(max_tool_calls=20, max_input_tokens=40_000, wall_clock_s=180),
    rerun    =BudgetSpec(max_tool_calls=4,  max_input_tokens=8_000,  wall_clock_s=30),
)
```

**3. An unregistered tool is a hard error, not a skipped check.** gtm-os's
`enforce_capability` raises `ValueError` on an unknown tool name, commented as *"defense
against typoed activity names silently bypassing the check."* This is the failure mode
that quietly disables a security control: a renamed tool falls out of the capability map
and every call sails through. JobHunter's tool registry raises on unknown names for the
same reason, and a test asserts every registered tool has a capability entry.

**And one deliberate divergence.** gtm-os notes that its *orchestrator* code
(`commit_dual_sink`, `gather_context`, `verify_citations`) intentionally bypasses the
capability check, because those are deterministic pipeline stages rather than
model-callable tools. That is the same line JobHunter draws at Tier 0 — but here it is
drawn *structurally* (the conductor is a separate module with no LLM import, lint-enforced)
rather than as a documented exemption inside a shared checker.

---

## 8. Escalation, failure and partial results

**The governing rule: one dead source never kills a night.** [DECISION]

```
worker fails
   │
   ├─ transient (timeout, 5xx, rate limit)
   │     └─► retry with exponential backoff, max 3
   │            └─► still failing → mark source degraded, return `partial`
   │
   ├─ structural (schema changed, selector gone, 404)
   │     └─► no retry. Circuit-break the source for this cycle.
   │            Record `source_health` row. Continue the stage without it.
   │
   └─ semantic (worker returns low-confidence / contradictory output)
         └─► escalate to supervisor
                ├─ supervisor retries with a different worker/method
                │     (e.g. Commit Miner found nothing → try Page Reader)
                └─ exhausted → mark the item `needs_human`, continue the cycle
```

**Backward edges.** Two are allowed, and only two:

| Edge | Trigger | Effect |
|---|---|---|
| Drafter → Triage | The Drafter reads the posting closely and finds it contradicts the score (e.g. a hard visa requirement the scorer missed) | Role is re-scored; the draft is abandoned, not sent |
| Feedback → Triage | Outcomes disagree with predictions at a statistically visible rate | Calibration Auditor proposes a rubric change (human accepts) |

Anything else is a forward-only pipeline. Cycles beyond these two are a design error.

**Degradation ladder, stated plainly.** The morning report always says what was
missing: *"Ran 7 of 8 sources — Ashby circuit-broke after 3 schema errors at 02:14.
120 postings scored (target 120). 4 companies yielded no verified contact."* A silent
partial run is worse than a loud one, because it looks like a quiet day.

---

## 9. The data model

SQLite. One file. WAL mode. `sqlite-vec` for embeddings.

### Immutable layer

| Table | Contents |
|---|---|
| `artifacts` | Every fetched document. `content`, `content_hash` (unique — dedupe), `source_url`, `fetched_at`, `kind` (`posting`/`team_page`/`repo`/`bio`/`reply`), `embedding`. **Append-only. Never rewritten.** |
| `postings_raw` | The raw payload as the source returned it, with `source_id` and `fetched_at`. Kept so a parser bug is fixable without re-fetching. |

### Canonical layer

| Table | Contents |
|---|---|
| `companies` | `id`, `name`, `domain`, `github_org`, `stage`, `email_pattern`, `pattern_confidence` |
| `roles` | `id`, `company_id`, `title`, `posting_artifact_id`, `posted_at`, `location`, `seniority`, `status` |
| `people` | `id`, `company_id`, `name`, `github_login`, `title` |
| `contacts` | `id`, `person_id`, `email`, **`confidence`** (`verified`/`derived`/`guessed`), `method`, `evidence_artifact_id`, `mx_ok` |

### Derived layer (re-computable)

| Table | Contents |
|---|---|
| `scores` | `role_id`, `screen_odds`, `reasons` JSON, `gaps` JSON, `rubric_version`, `model`, `computed_at`. Multiple rows per role across rubric versions — the newest wins in reads. |
| `drafts` | `contact_id`, `role_id`, `subject`, `body`, `evidence_spans` JSON, `voice_score`, `audit_status`, `status`, `expires_at` |

### Human + outbound layer

| Table | Contents |
|---|---|
| `approvals` | `draft_id`, `decision` (`approved`/`edited`/`rejected`), `edited_body`, `decided_at`. The gtm-os `review_decisions` analogue. |
| `send_budget` | `date` (PK), `cap`, `used`, `guessed_used`. The scarcity ledger. |
| `sends` | `draft_id`, `gmail_message_id`, `thread_id`, `sent_at` |
| `threads` | `thread_id`, `contact_id`, `last_activity_at`, `followup_count` — `CHECK (followup_count <= 1)` |
| `replies` | `thread_id`, `artifact_id`, `class`, `classified_at` |
| `outcomes` | `role_id`, `predicted_odds`, `actual` (`screen`/`no_reply`/`rejected`) — the calibration fuel |

### Operational layer

| Table | Contents |
|---|---|
| `runs` | `id`, `parent_run_id`, `agent`, `input` JSON, `status`, `steps` JSON, `tokens_in/out`, `wall_ms`, `error`. Every agent invocation. |
| `cycle_state` | The conductor's state machine: `cycle_date`, `stage`, `started_at`, `committed_at` |
| `source_health` | `source_id`, `consecutive_failures`, `last_ok_at`, `last_count`. Drives the circuit breaker **and** the freshness alarm. |
| `tool_calls` | Every tool invocation with args hash + result hash. The audit trail. |

**Conventions worth stating:**

- `content_hash` is the idempotency key everywhere. Re-running a night is free and safe.
- `drafts.expires_at` is 7 days. A stale draft referencing a filled role makes the
  sender look inattentive — worse than not sending. Expired drafts are deleted, not sent.
- `contacts.confidence` has no default. Every insert must state it.

---

## 10. Data flow diagram

```
  ATS APIs · HN thread · remote feeds · YC directory
        │  Scout Supervisor → 5 workers, parallel, circuit-broken per source
        ▼
  postings_raw + artifacts        (immutable, content-hashed, never edited)
        │  Company Resolver → canonical companies / roles
        ▼
  ~3,000 roles
        │  ── Rule Gate (SQL, ~0 cost) ─────────────► ~800
        │  ── Embedding Gate (local, top-K) ────────► ~120
        │  ── Fit Judge (local LLM + rubric) ───────► ~40 scored
        ▼
  scores          (screen_odds + reasons + gaps + rubric_version)
        │  Contact Supervisor picks the top ~15 companies
        ▼
  Commit Miner ──► verified emails      (public git history)
  Page Reader  ──► names + roles        (company's own pages)
  Pattern Inf. ──► derived emails       (needs ≥2 verified examples)
        │  Deliverability Checker → Contact Ranker
        ▼
  contacts        (each carrying verified | derived | guessed)
        │  Outreach Supervisor allocates against remaining send budget
        ▼
  Persona Reader ──► cited observations
  Drafter        ──► subject + body + EVIDENCE SPANS
  Faithfulness Auditor ──► pass | strip unsupported specifics | reject
  Voice Checker  ──► similarity vs previously approved drafts
        ▼
  ╔═══════════════════════════════════════════════════════════╗
  ║  REVIEW QUEUE   —  the only human gate, the only send path ║
  ║  approve / edit+approve / reject          budget: 25 → 0   ║
  ╚═══════════════════════════════════════════════════════════╝
        │  approval handler (the ONLY holder of send_email)
        ▼
  Gmail send  ≤25/day · spaced · plain text · working hours
        │
        ▼
  replies ──► Reply Classifier ──► yes | no | role_gone | unclear
        │           └─ unclear → straight to the human, no forced guess
        ├──► silent ≥5 days ──► Follow-up Drafter ──► REVIEW QUEUE (one, ever)
        └──► outcomes ──► Calibration Auditor ──► rubric proposal ──► human
```

---

## 11. The daily cycle, hour by hour

| Time | Stage | What runs | Human? |
|---|---|---|---|
| 02:00 | `source` | Scout Supervisor → 5 workers in parallel. ~8 min. | no |
| 02:10 | `triage` | Rule Gate (seconds) → Embedding Gate (~1 min) → Fit Judge over ~120 postings (~15 min). | no |
| 02:30 | `contact` | Contact Supervisor over the top ~15 companies, parallel. ~15 min. | no |
| 02:45 | `draft` | Persona Reader + Drafter per contact, sequential. ~10 min. | no |
| 02:55 | `audit` | Faithfulness Auditor + Voice Checker. ~3 min. | no |
| 03:00 | `queue` | Drafts land in the review queue. Morning report written. | no |
| 03:05 | `feedback` | Reply Classifier on overnight replies; stale-thread scan; follow-up drafts. | no |
| **09:00** | **review** | **You open it once. ~10 minutes.** | **yes** |
| 09:10→ | `send` | Approved mail goes out spaced across working hours, ≤25. | no |

**If the laptop was closed at 02:00**, the conductor resumes from `cycle_state` on next
wake and runs the remaining stages. Stages already committed are not re-run — that's
what the content hashes are for.

---

## 12. Budget as a first-class resource

The 25/day cap is not a limit the system respects. It is the resource the system
allocates.

```python
# The only path to an outbound email. Not reachable by any agent.
def send_approved(draft_id: int, actor: str) -> SendResult:
    with db.transaction():                      # single transaction, no exceptions
        approval = require_approval(draft_id, actor)   # raises if absent
        draft    = require_not_expired(draft_id)
        budget   = lock_budget_row(today())            # SELECT … FOR UPDATE

        if budget.used >= budget.cap:
            raise BudgetExhausted
        if draft.contact.confidence == "guessed" and budget.guessed_used >= GUESSED_CAP:
            raise GuessedBudgetExhausted

        budget.used += 1
        if draft.contact.confidence == "guessed":
            budget.guessed_used += 1

        result = gmail.send(draft)               # inside the txn: no send without a decrement
        record_send(draft_id, result)
    return result
```

**How the budget shapes upstream decisions:**

| Consumer | How it uses the budget |
|---|---|
| Outreach Supervisor | Drafts `remaining + 20%`, not everything available. Drafting past the cap wastes compute and creates a queue the human must reject. |
| Contact Ranker | Sorts so that scarce sends land on `verified` addresses first. |
| Fit Judge | Scores are pessimistic *because* sends are scarce. If sends were free, an optimistic scorer would be fine. |
| The UI | Remaining budget is on **every** screen, depleting. The scarcity has to be felt at review time, not discovered at send time. |

---

## 13. The evidence system — how "don't lie" is enforced mechanically

The user-facing rule is: *never invent a project, a number, or a shared connection.*
Prompts alone do not enforce this. Three mechanisms do.

**1. The Persona Reader can only emit cited observations.** Its output schema requires
an evidence span per observation. An observation without one fails schema validation
and is dropped before the Drafter ever sees it. The Drafter therefore cannot inherit an
uncited "fact" — it never receives one.

**2. The Drafter must attribute every specific claim.** Its output is not a string, it
is a body plus a list of `(sentence_index → evidence_span)` mappings. Sentences with no
mapping must be *generic* — they may not contain a proper noun, a number, or a
second-person claim about the recipient's work.

**3. The Faithfulness Auditor runs two passes:**

| Pass | Kind | Checks |
|---|---|---|
| Span existence | deterministic | Does `artifacts[id][start:end]` exist, and is the artifact one this run actually fetched? Catches fabricated citations outright. |
| Span support | LLM (small) | Does that text actually support the sentence? Catches real citations attached to claims they don't back. |

**On failure the auditor strips, it does not rewrite.** [DECISION] A rewrite gives the
model a second chance to invent something. Stripping degrades the email toward generic,
which is the acceptable failure. If stripping leaves the draft with no specific content
at all, the draft is marked `generic` and shown to the human labelled as such — they
can decide whether a generic honest note is worth one of their 25.

This is gtm-os's faithfulness gate applied to outbound text rather than to knowledge-graph
claims: *reject anything whose evidence span is not literally present in its cited source.*

---

## 14. Tech stack

| Layer | Choice | Why |
|---|---|---|
| **Language** | Python 3.12 | Matches the reference codebase; the scraping and email ecosystem is here. |
| **Orchestration** | Custom durable state machine over SQLite | See §15 — Temporal is right for gtm-os and wrong for a laptop. |
| **Storage** | **SQLite (WAL) + `sqlite-vec`** | One file, no daemon, trivially backed up, survives a laptop reboot. Postgres+pgvector is the right call for a multi-tenant server and overkill for one user. |
| **Migrations** | Alembic (hand-written) | Same convention as gtm-os: no autogenerate. |
| **Models** | **Ollama, local** | Nothing leaves the laptop. Three tiers: small (~3B) for classification/extraction, mid (~14B) for scoring, best-available for drafting. |
| **Embeddings** | local sentence-transformers | Same reason. |
| **Validation** | Pydantic | Every envelope and every agent output is a validated model. Schema failure is a caught, logged, retried event. |
| **HTTP** | `httpx` + a wrapper enforcing the egress allowlist, robots, per-host rate limits, backoff | The allowlist is the privacy guarantee in code. |
| **Git mining** | `git log` over shallow clones, or the GitHub commits API | Public data, obtained the ordinary way. |
| **Email** | Gmail API (OAuth, `gmail.send` + `gmail.readonly`) | Sends from the user's own account so replies land in the user's own inbox. |
| **UI** | Local web app — review queue, funnel dashboard, budget meter | Review has to take ten minutes or the system fails at the only step that needs a human. |
| **Scheduling** | `launchd` (macOS) / `systemd` timer | No cloud scheduler; the machine is the deployment. |
| **Tooling** | `uv`, `ruff`, `pyright`, `pytest` | Same as the reference repo. |

**Explicitly rejected:** LangChain/LangGraph/CrewAI as the orchestration layer. The
hierarchy here is five supervisors and eighteen narrow workers with typed envelopes —
that is ~400 lines of Python. A framework would add an abstraction over the one thing
this system most needs to be readable: what ran, why, and what it cost. [DECISION]

---

## 15. What we take from gtm-os and what we drop

### Taken

| Pattern | In gtm-os | In JobHunter |
|---|---|---|
| **Append-only raw layer** | `episodes` — raw ingest, content-hashed, never rewritten | `artifacts` — same idea, same reason |
| **Evidence spans + faithfulness gate** | Claims rejected if `evidence_span` isn't in the cited episode | Draft sentences stripped if their span doesn't support them |
| **Proposal → human → truth** | `fact_proposals` + `/review` + `review_decisions` | `drafts` + review queue + `approvals` |
| **The dangerous capability is named, not omitted** | `EXECUTE_OUTREACH` exists in the enum; one role holds it and still can only *propose* (`hitl=required`) | `send_email` is a named capability held by no agent; reachable only from the approval handler |
| **Capability-gated tools, checked first line, server-side** | `enforce_capability(role, tool)` is the first line of every tool activity; unknown tool → `ValueError` | Envelope capabilities narrowed on the way down; unknown tool → hard error |
| **No auto-reject** | Two thresholds (0.85 / 0.70), no auto-reject constant, pinned by a pytest gate | A low score ranks a role last; it never deletes it |
| **The budget triple, enforced at three layers** | `BudgetSpec(max_tool_calls, max_input_tokens, wall_clock_seconds)`, frozen, with `first_run`/`rerun` profiles per role | Same triple, same immutability, same two-profile split (cold company vs. re-check) |
| **Durable run ledger** | `agent_runs` — input, status, steps, cost, trace id | `runs` — plus `parent_run_id` for the tree |
| **Multi-phase agents as workflows, not one call** | gather → draft → verify → commit as separate durable steps | Same shape per stage, checkpointed in `cycle_state` |
| **SSRF-guarded fetch, untrusted-content wrapping** | `web_fetch.py` rejects private addresses; results wrapped as untrusted | Same guard + a stricter egress allowlist |
| **Versioned prompts/rubrics on every output** | `extractor: agent:transcript_miner@v1` | `rubric_version` / `prompt_version` on every score and draft |

### Dropped, and why

| Dropped | Why it exists in gtm-os | Why JobHunter doesn't need it |
|---|---|---|
| **Postgres RLS + role split** | Multi-tenant SaaS; a cross-tenant leak is fatal | One user, one laptop, one SQLite file. There is no second tenant to leak to. |
| **Temporal** | Long-running workflows across a distributed fleet, retried across deploys | A 45-minute nightly run on one machine. A committed state machine over SQLite gives the same resumability without a server, a namespace, and mTLS. |
| **LiteLLM proxy + per-tenant virtual keys** | Routing + per-tenant billing across providers | One local model. No routing, no billing, no keys. |
| **Nango** | OAuth across 13 connector providers | One OAuth integration (Gmail), done directly. |
| **Bi-temporal claims** | Auditing what the system believed on a past date, for a customer | Nobody will audit this. `computed_at` + `rubric_version` covers re-derivation, which is the real need. |
| **GCS + Cloud Run + Terraform** | It's a deployed product | It's a laptop. |
| **Free-form predicate knowledge graph** | Open-schema facts across accounts, no migration per fact type | The domain is narrow and known: roles, companies, people, contacts, outcomes. A typed schema is simpler and enough. |

**The one thing worth reconsidering later:** if JobHunter ever tracks *many* people's
searches (a placement cell, a cohort), the multi-tenancy decision flips and RLS comes
back. Everything else stays. [OPEN]

---

## 16. Configuration and secrets

```ini
# === Storage ===
DB_PATH=./jobhunter.db

# === Local models (Ollama) ===
OLLAMA_HOST=http://localhost:11434
MODEL_SMALL=llama3.2:3b            # classification, extraction, span-support checks
MODEL_MID=qwen2.5:14b              # fit scoring, follow-ups, weekly analysis
MODEL_DRAFT=qwen2.5:14b-instruct   # drafting — the best local model available
EMBED_MODEL=all-MiniLM-L6-v2

# === The constraint ===
DAILY_SEND_CAP=25
GUESSED_SEND_CAP=5                 # of the 25, at most this many to unverified addresses
SEND_WINDOW=09:30-18:00
SEND_SPACING_MIN=8                 # minutes between sends
FOLLOWUP_AFTER_DAYS=5
DRAFT_EXPIRY_DAYS=7

# === Funnel widths (the cost gradient, as config) ===
RULE_GATE_KEEP=800
EMBED_GATE_TOP_K=120
SCORE_SHORTLIST=40
CONTACT_COMPANIES=15

# === Gmail (OAuth — token cached locally, never committed) ===
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_TOKEN_PATH=./.secrets/gmail_token.json

# === Optional, off by default ===
GITHUB_TOKEN=                      # raises the commits-API rate limit; not required

# === Egress ===
# Allowlist is code, not config — editing it is a reviewed change, not a runtime knob.
```

**There is no LLM API key**, and that is the point. If one ever appears here, the
local-first guarantee has been broken and the claim in §6/D7 must be removed from the
UI.

---

## 17. Failure modes — what breaks first

Ordered by likelihood, honestly.

| # | Failure | Signal | Mitigation |
|---|---|---|---|
| 1 | **Scrapers break silently.** A board changes its JSON shape; the scout returns 0 rows and nothing errors. | `source_health.last_count` drops to 0 while others are normal | Freshness alarm: any source returning 0 for 2 consecutive cycles is surfaced in the morning report as a **failure**, not a quiet day. This is the single most likely way the system dies without anyone noticing. |
| 2 | **The human stops reviewing.** Ten minutes a day is small until it isn't. | Queue depth grows; approvals/day → 0 | Drafts expire at 7 days and are deleted. A growing queue is shown as a problem, not a backlog. If the queue is untouched for 5 days the pipeline pauses sourcing — generating drafts nobody reads is pure waste. |
| 3 | **Bounces damage the sending account.** Guessed addresses fail; Gmail notices the pattern. | Bounce rate per confidence tier | Hard `GUESSED_SEND_CAP`. Bounce rate is tracked per tier and shown; if `guessed` bounces exceed ~30%, the pattern inferencer is disabled until re-tuned. [TARGET] |
| 4 | **The local model isn't good enough to score honestly.** A 14B model may not distinguish "5 years required, firm" from boilerplate. | Calibration: predicted odds vs actual screens | This is what `outcomes` and the Calibration Auditor exist for. Expect the first two weeks of scores to be poorly calibrated and say so in the UI rather than pretending. **[OPEN]** — the real risk is that local models plateau below useful here. |
| 5 | **Drafts read as templates anyway.** Same structure, same opener, twenty times. | Reply rate flat and low | Voice Checker compares against approved drafts; the Funnel Analyst reports reply rate by framing. Structural variety must be measured, not assumed. |
| 6 | **Company resolution merges two different companies.** Two "Nova"s become one; contacts get crossed. | Manual notice, usually after a wrong send | Domain match first, model only for the residue, and never merge on name alone. A merge affecting an already-contacted company requires human confirmation. |
| 7 | **Commit mining yields nothing** for companies with no public code — which is most non-infra companies. | `verified` contact rate per company | Expected, not a bug. Page Reader is the fallback; if both fail, the company is dropped rather than guessed at. Better to skip a company than to burn a send on a fabricated address. |
| 8 | **Nightly run doesn't finish before morning.** Gates widen, model slows. | `cycle_state` stage timings | Every stage has a wall-clock budget; exceeding it truncates the stage (processing the highest-scoring items first) and reports the truncation. Never silently drop. |

---

## 18. Explicit non-goals and hard limits

These are architectural commitments, not preferences. Each is enforced somewhere in
code, and the enforcement point is named.

| Never | Enforced by |
|---|---|
| **No logged-in LinkedIn automation.** A banned LinkedIn destroys the exact asset the strategy depends on — the ability to be referred. | LinkedIn is not on the egress allowlist. Public pages only, unauthenticated, if at all. |
| **No auto-apply.** Applications are cheap and worthless in bulk; the referral is the leverage. | There is no application-submission tool. |
| **No send without a human.** Ever. | `send_approved()` requires an `approvals` row with a human actor; no agent holds the capability. |
| **No invented experience, shared connection, or number.** | Evidence spans + faithfulness gate (§13). Unsupported specifics are stripped. |
| **No more than one follow-up per thread.** | `CHECK (followup_count <= 1)` on `threads`. |
| **No data leaves the laptop.** | Egress allowlist in the fetch wrapper; local model; no LLM API key. |
| **No contact list building.** One person is contacted at most once, for one role. Contacts are not exported, aggregated, or reused across roles without a fresh human decision. | Unique constraint on `(person_id)` in `sends`; no export path. |
| **No scraping behind a login, and robots.txt is respected.** | The fetch wrapper. |

On the ethics of git-mined emails, plainly: commit author emails are public by design
and open-source maintainers expect to be contacted. What makes that acceptable is
**volume and intent** — one personal, specific message about a real role is within
norms; a hundred templated ones is not, regardless of where the address came from. The
25/day cap is what keeps the system on the right side of that line, which is a second
reason it is a ledger and not a config value.

---

## 19. Build order

Each milestone is independently useful. Nothing here requires the next thing to exist.

| # | Milestone | Ships | Why this order |
|---|---|---|---|
| **M1** | **Source + store** | ATS Scout over ~50 known boards → `artifacts` + `roles`. A list you can read. | Proves the highest-yield source works. Zero agents, zero LLM. If this isn't good, nothing downstream matters. |
| **M2** | **Triage** | Rule Gate + Embedding Gate + Fit Judge + the review UI showing scored roles | The first genuinely useful output: "here are 40 roles worth your attention, with honest numbers." Usable alone, forever. |
| **M3** | **Contacts** | Commit Miner + Deliverability + confidence labels | Now you know *who* to ask. Still no sending — you could copy the addresses out by hand and it would already be worth it. |
| **M4** | **Drafts + the gate** | Persona Reader, Drafter, Faithfulness Auditor, review queue | The first point where the system writes on your behalf. The gate ships *with* it, not after. |
| **M5** | **Send + budget ledger** | `send_approved`, the 25/day ledger, spacing, the budget meter | The irreversible step. Last, deliberately. |
| **M6** | **Feedback loop** | Reply Classifier, one follow-up, `outcomes` | Closes the loop; makes calibration possible. |
| **M7** | **Calibration + analytics** | Calibration Auditor, Funnel Analyst | Turns the funnel into something you can adjust rather than hope about. |

**The ordering principle:** every irreversible capability ships after everything that
constrains it. The send path is built last because the gate, the ledger, and the
confidence labels all have to exist first.

---

## 20. Open questions

1. **Is a 14B local model good enough for calibrated scoring?** [OPEN] The whole value
   of Triage rests on the score being *honestly pessimistic*, which is a harder
   instruction to follow than it sounds — models are trained toward encouragement.
   Falsifiable in M2: score 100 roles, apply to 20 across the odds range, compare.
2. **What's the actual verified-contact yield?** [OPEN] Commit mining is excellent for
   infra/dev-tools companies and probably near-zero elsewhere. If it's under ~20%
   across a realistic target set, the Contact stage needs a different primary method.
3. **Does the review step actually take ten minutes?** [OPEN] If it takes forty, the
   system fails at its only human step. Measure it in M4 before building M5.
4. **Should supervisors be LLM-backed at all?** [OPEN] Scout and Triage supervisors may
   be pure policy — "run all healthy sources", "score the top K". If so, demote them to
   code and the hierarchy has agents only where judgement genuinely lives.
5. **Follow-up: one, or one *per stage*?** The doc says one, ever. A defensible
   alternative is one follow-up plus one much-later re-approach if the role reopens.
   Currently ruled out for simplicity. [OPEN]
6. **What happens when a company replies from a different address than the one
   contacted?** Thread matching by `thread_id` handles most of it; person-level identity
   across addresses is unsolved. [OPEN]

---

## Appendix — the one-line version

> Job hunting is mostly search, filtering, and follow-up, which are machine work, plus
> judgement and voice, which are not. JobHunter does the machine work exhaustively and
> stops dead at the point where you're needed.

The architecture above is that sentence, made structural: a deterministic conductor
over five thin supervisors over eighteen narrow workers, spending a scarce, ledgered
budget of 25 irreversible actions a day, every one of which passes through a human.
