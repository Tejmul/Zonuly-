# gtm-arch — build gtm-os from scratch

A complete, self-contained rebuild specification for **gtm-os**: what problem it solves, every
tool and vendor it depends on, how the pieces fit, and the order to build them in.

If you read this file top-to-bottom and follow the build order in §14, you end up with the same
system that lives in this repository. Nothing here assumes you have the existing code.

---

## Table of contents

1. [Problem statement](#1-problem-statement)
2. [Product thesis and non-negotiables](#2-product-thesis-and-non-negotiables)
3. [System shape](#3-system-shape)
4. [Full tool and vendor inventory](#4-full-tool-and-vendor-inventory)
5. [The data model — knowledge graph](#5-the-data-model--knowledge-graph)
6. [Multi-tenancy and isolation](#6-multi-tenancy-and-isolation)
7. [Ingestion — the connector framework](#7-ingestion--the-connector-framework)
8. [Unification — raw records to canonical entities](#8-unification--raw-records-to-canonical-entities)
9. [Scraping — everything external, in detail](#9-scraping--everything-external-in-detail)
10. [The agent runtime](#10-the-agent-runtime)
11. [The agent roster](#11-the-agent-roster)
12. [Artifacts, HITL, and the review loop](#12-artifacts-hitl-and-the-review-loop)
13. [API and frontend](#13-api-and-frontend)
14. [Build order — 14 milestones](#14-build-order--14-milestones)
15. [Local development environment](#15-local-development-environment)
16. [CI, deploy, and infrastructure](#16-ci-deploy-and-infrastructure)
17. [Conventions that keep the codebase coherent](#17-conventions-that-keep-the-codebase-coherent)
18. [Complete environment variable reference](#18-complete-environment-variable-reference)

---

## 1. Problem statement

Go-to-market teams run on fragmented, unstructured evidence. The facts that decide a deal —
who the champion is, what budget was mentioned on a call six weeks ago, which competitor got
named in an email thread, whether the buyer's company just laid off half of engineering — exist
in call recordings, mailboxes, CRM notes, LinkedIn, and news. A CRM stores *fields*; it does not
store *reasoning over evidence*.

So the work that actually moves revenue is manual reading:

- An AE re-reads three months of transcripts before a renewal call.
- An SDR builds a prospect dossier by hand from a website, LinkedIn, Crunchbase, and G2.
- Marketing writes a battle card by trawling competitor sites and review sites.
- Nobody notices the hiring spike, the funding round, or the champion's job change until it is
  too late to act on it.

Every one of those tasks is **reading, reasoning, and drafting** — exactly what an LLM does well
— but they are gated on having a single trustworthy memory of the account, and on nobody being
allowed to send fabricated claims to a customer.

**gtm-os is the operating system for that.** One shared, typed, bi-temporal memory of every
account, fed by connectors and scrapers, read and written by a fleet of durable LLM agents,
with every outbound write gated behind human approval.

The three hard problems it exists to solve:

| Problem | The answer in this system |
|---|---|
| Facts live in unstructured text nobody re-reads | Agents mine transcripts/emails/pages into **claims** with an exact evidence span |
| Facts go stale and contradict each other | **Bi-temporal claims** — valid-time and transaction-time; nothing is deleted, beliefs are retracted |
| LLMs hallucinate, and GTM output is customer-facing | **Faithfulness checks + human-in-the-loop proposals** — an agent can only propose, never commit |

---

## 2. Product thesis and non-negotiables

"Agent-native" is a structural claim, not a marketing one. Build it this way or the system is a
different product:

1. **Agents are the interpretation layer, not a feature.** A transcript becomes structured data
   because an agent mined it. An account brief exists because an agent synthesised the graph.
   There is no hand-written parser fallback.
2. **Every agent run is a durable workflow.** Temporal, not a request-scoped `asyncio.gather`.
   Multi-phase agents are workflows calling per-phase activities, so each phase retries alone.
3. **Every agent write is a proposal.** Agents write to `fact_proposals` / `edge_proposals` /
   `node_proposals` / `draft_proposals`. A confidence rule, a Guardian agent, or a human
   promotes it. Nothing else can.
4. **Permissions are enforced server-side at the tool layer, not in the prompt.** A role holds a
   capability set; a tool refuses to execute if the caller lacks the capability. Prompt-level
   "please don't do X" is not a control.
5. **Every claim carries provenance.** `source_episode_ids`, `evidence_span` (verbatim text),
   `extractor` (e.g. `agent:transcript_miner@v1`). A claim whose evidence span is not literally
   present in its cited episode is rejected before it reaches the graph.
6. **All scraped/fetched content is untrusted.** Web and LinkedIn results are wrapped in
   `<INGESTED_UNTRUSTED_CONTENT>…</INGESTED_UNTRUSTED_CONTENT>` before entering any prompt.
7. **Tenant isolation is a database property.** Postgres Row-Level Security on a per-session
   GUC, with an application role that does *not* have BYPASSRLS. Not `WHERE tenant_id = ...`.
8. **Sending is never an agent capability.** `EXECUTE_OUTREACH` exists in the capability enum
   and no role holds it. External sends go through an approved draft.

---

## 3. System shape

A `uv` workspace: one repo, ten Python workspace members (seven shared libraries, three
deployable services), plus a Next.js frontend.

```
gtm-os/
├── packages/                      # shared libraries (uv workspace members)
│   ├── db/                        # SQLAlchemy models + Alembic migrations + session/RLS helpers
│   ├── common/                    # config (pydantic-settings), Temporal client, LLM + embed,
│   │                              #   Brave search, GCS signed URLs, Secret Manager, health
│   ├── connectors/                # connector framework + per-provider packages + Apify/Nango clients
│   ├── context/                   # context_chunks index (write + semantic read), PDF/DOCX extract
│   ├── files/                     # /v1/files store — folders as entities, GCS-backed uploads
│   ├── identity/                  # canonical identity registry: Resolver, LLM judge, normalisation
│   └── unification/               # entity resolution + merge (source_records -> canonical entities)
├── services/
│   ├── api/                       # FastAPI (gtm_api) — 41 route modules, auth, middleware
│   ├── worker/                    # Temporal worker (gtm_worker) — connector sync + unification
│   └── agents/                    # Temporal worker (gtm_agents) — agent roles, workflows,
│       │                          #   activities, tools, render, KG sweeper, schedules
│       └── litellm/               # LiteLLM proxy config + Dockerfile
├── frontend/                      # Next.js 16 / React 19 / Tailwind v4
├── infra/                         # init-db.sh, temporal dynamic config, terraform/
├── nango/                         # Nango self-hosted config + sync definitions
├── scripts/                       # dev + ops one-shots, ci/ helpers
├── docs/                          # architecture, ops, audits, compliance, research, setup
├── tests/                         # cross-cutting tests
├── docker-compose.yml             # postgres + redis + temporal (+UI) + nango
├── Makefile
└── pyproject.toml                 # uv workspace + ruff/pyright/pytest config
```

### The three services

| Service | Runtime | Role |
|---|---|---|
| `gtm-api` | FastAPI, uvicorn, port 8000 | The only HTTP surface. Auth, tenant resolution, reads over the graph, review/proposal queues, file access, connector management, agent-run triggers. |
| `gtm-worker` | Temporal worker | CRM data plane: connector sync workflows + unification workflow. Queue `gtm-sync-tasks-{env}`. |
| `gtm-agents` | Temporal worker(s) | Agent plane: per-role workflows, activities, shared tool surface. One process hosts several `Worker` instances, each polling its own task queue. |

### End-to-end data flow

```
   connected tool (HubSpot, Gmail, Slack, Apollo, …)   +   scrapers (Apify, Brave)
                       │  sync workflow                             │
                       ▼            services/worker                 │
             source_records  (raw, immutable, JSONB)                │
                       │  unification: resolve + merge              │
                       ▼            packages/unification            │
      accounts / contacts / deals / activities  (canonical)         │
                       │                                            │
                       │  an activity carrying a transcript fires   │
                       ▼            services/agents                 ▼
              Transcript Miner ───────────────────────────►  episodes (append-only)
                       │  emits claim proposals with evidence spans
                       ▼
      fact_proposals / edge_proposals / node_proposals   (status=pending)
                       │  confidence rule (≥0.85 auto) │ Guardian │ human /review
                       ▼
        claims  +  kg_nodes  +  relationships   ===   the knowledge graph
                       │  projection views (vw_facts, vw_account_profile, …)
                       ▼
   Synthesiser · Account Intelligence · Battle Card · Prospect · Knowledge Base ·
   LinkedIn audits · Outbound Sequence · Growth Report · Alpha Feed · Signal Monitor
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
  agent_outputs + PDF/DOCX      draft_proposals (HITL queue — nothing auto-sends)
        │                             │
        └──────────► gtm-api ─────────┴──────────► Next.js frontend
```

---

## 4. Full tool and vendor inventory

Everything the system depends on, by layer. This is the shopping list.

### 4.1 Language + runtime

| Tool | Version | Why |
|---|---|---|
| Python | 3.12+ | Backend language. `StrEnum`, `|` unions, `datetime.UTC`. |
| `uv` | 0.9+ | Workspace manager. `uv sync --all-packages` — a plain `uv sync` installs only the root and silently skips members. |
| Node | 20+ | Frontend build. |
| Docker Desktop / Compose | current | Local infra stack. |
| `hatchling` | — | Build backend for every workspace member wheel. |

### 4.2 Backend libraries

| Library | Pin | Used for |
|---|---|---|
| `fastapi` | ≥0.115 | HTTP API |
| `uvicorn[standard]` | ≥0.30 | ASGI server |
| `python-multipart` | ≥0.0.12 | `UploadFile` / `Form()` decoding |
| `sqlalchemy[asyncio]` | ≥2.0 | ORM, async engine |
| `asyncpg` | ≥0.29 | Async Postgres driver (app path) |
| `psycopg2-binary` | ≥2.9 | Sync driver (Alembic path) |
| `alembic` | ≥1.14 | Migrations — hand-written, never `--autogenerate` |
| `pgvector` | ≥0.3 | Vector column type + ANN search |
| `pydantic` / `pydantic-settings` | ≥2.0 | Typed schemas + env config |
| `pydantic-ai-slim[openai]` | ≥1.99,<2 | Agent loop framework (pinned to the v1 line deliberately) |
| `temporalio` | ≥1.25 | Durable workflows |
| `litellm` | ≥1.80 | LLM client library (proxy server runs separately) |
| `langfuse` | ≥3.0 | Optional LLM tracing |
| `authlib` + `itsdangerous` | ≥1.3 / ≥2.2 | OAuth + signed session cookies |
| `httpx` | ≥0.27 | All outbound HTTP |
| `weasyprint` | ≥68.0 | HTML → PDF rendering |
| `jinja2` | ≥3.1 | Render templates |
| `pypdf` | ≥6.0 | PDF → text (pure Python, **no JS execution** — deliberate safety choice) |
| `python-docx` | ≥1.2 | DOCX read + write |
| `python-magic` | ≥0.4.27 | Magic-byte MIME sniffing on upload (needs `libmagic` system lib) |
| `thefuzz[speedup]` | ≥0.22 | Fuzzy match in the unification merger |
| `rapidfuzz` | ≥3.0 | Tier-2 entity resolution (`token_sort_ratio`) |
| `splink` | ≥4.0 | Fellegi–Sunter probabilistic entity resolution in the KG sweeper |
| `duckdb` | ≥1.0 | Splink backend — single-process, per-tenant batches, no Spark |
| `tldextract` | ≥5.0 | Public-suffix-aware registrable-domain block key |
| `pyyaml` | ≥6.0 | Connector `mapping.yaml` loader |
| `google-cloud-storage` | ≥2.18 | Artifact + file blobs |
| `google-cloud-secret-manager` | ≥2.20 | Prod secrets |
| `google-auth` | ≥2.30 | ID tokens for internal Cloud Run ingress |
| `redis` | ≥5.0 | Cache, rate limiting |

Dev tools: `ruff` ≥0.8 (lint, line-length 100, rules `E,F,I,UP,B,SIM`), `pyright` ≥1.1.390
(basic mode), `pytest` ≥8 + `pytest-asyncio`, `pre-commit`.

### 4.3 Infrastructure

| Component | Dev | Prod |
|---|---|---|
| Database | `pgvector/pgvector:pg16` on port **5434** | Cloud SQL Postgres 16 + pgvector |
| Cache | `redis:7-alpine` on 6379 | Memorystore |
| Orchestration | `temporalio/auto-setup` on 7233, UI on 8088 | Temporal Cloud with mTLS |
| Connector auth | `nangohq/nango-server:hosted` on 3003 (`admin`/`admin`) | Nango |
| LLM proxy | LiteLLM on host, port 4000 | Cloud Run service, ingress=internal |
| Object storage | GCS buckets | GCS (`*-reports`, `*-files`) |
| Compute | host processes | Cloud Run services, Terraform-managed |

> **Why LiteLLM is not a Compose service:** on 8 GB machines Docker Desktop's default memory
> (~970 MB) OOM-kills it at boot; its Python deps need ~1.5 GB. It runs on the host in its own
> venv (`.venv-litellm`) and talks to the dockerised Postgres on `localhost:5434`.

### 4.4 Model providers (all routed through the LiteLLM proxy by alias)

Agent code only ever knows the **alias**. The upstream provider is owned by
`services/agents/litellm/config.yaml`.

| Alias | Upstream | Timeout | Used for |
|---|---|---|---|
| `claude-opus` | `anthropic/claude-opus-4-7` | 900s | Long-form narrative synthesis (prospect report, growth report, outbound sequences) |
| `claude-sonnet` | `anthropic/claude-sonnet-4-6` | 600s | Default. Multi-step research loops, extraction, review |
| `claude-haiku` | `anthropic/claude-haiku-4-5-20251001` | 300s | Cheap scoring (signal evaluator) |
| `kimi-k2` | `moonshot/kimi-k2.6` | 600s | Cost-sensitive fan-out (~5× cheaper than Sonnet) |
| `minimax` | `openai/MiniMax-M2.1` via `api.minimax.io/v1` | 600s | Cheap agentic tier |
| `openrouter-nano` | `openai/gpt-5-nano` via OpenRouter | — | Cheapest reliable, 400k ctx |
| `openrouter-flash` | `z-ai/glm-4.7-flash` via OpenRouter | — | Cheap agentic |

Embeddings bypass the proxy and go direct: `text-embedding-3-small`, 1536 dimensions (OpenAI,
or OpenRouter's OpenAI-compatible `/embeddings` when `OPENROUTER_API_KEY` is set).

**Critical setting:** `num_retries: 0` on every proxy alias, and `max_retries=0` in the OpenAI
client. Temporal owns retry. Double-retry burns budget and breaks the retry-policy contract.

**Per-tenant billing:** each tenant has a LiteLLM *virtual key* (`LITELLM_VIRTUAL_KEY_{SLUG}`).
`get_litellm_key_for_tenant` raises if the key is empty — **no silent master-key fallback**.
Keys are explicit `Settings` attributes, never dynamic `getattr`, so an injected slug cannot
resolve to arbitrary settings state.

### 4.5 External data vendors

| Vendor | Purpose | Auth | Cost control |
|---|---|---|---|
| **Apify** | All scraping — LinkedIn, news, Crunchbase, SimilarWeb, Ahrefs, SEO, SERP, Reddit, Instagram, TikTok, tech-stack, screenshots | App-level `Authorization: Bearer <APIFY_TOKEN>` | Per-tenant daily budget (`tenant_settings.apify_daily_budget_usd`, default $10) + `?maxCharge=` platform ceiling + 24h per-tenant cache + `apify_run_log` cost ledger |
| **Brave Search API** | Agent `web_search` tool | `BRAVE_API_KEY` | Empty key raises — never silently returns `[]` |
| **Nango** | OAuth + proxy for CRM connectors | `NANGO_SECRET_KEY` | — |
| **HeyReach** | LinkedIn outbound execution | App-level `HEYREACH_API_KEY`; inbound webhook authed by shared secret in path | HITL-gated |
| **Podchaser / Listen Notes** | Podcast feed sources | `PODCHASER_API_KEY` | — |
| **Langfuse** | LLM tracing (optional) | public/secret key | — |

---

## 5. The data model — knowledge graph

Postgres 16 + pgvector. 102 hand-written Alembic migrations (latest revision 106). Three layers plus canonical nodes.

### Layer 1 — `episodes` (append-only raw ingest)

| Column | Meaning |
|---|---|
| `content` | The raw text: call transcript, email body, meeting note, scraped page |
| `content_hash` | Dedup key |
| `occurred_at` | When it happened in the world |
| `source_ref` | JSONB pointer back to origin |
| `embedding` | pgvector column for semantic search |

Never destructively rewritten. If a downstream fact turns out wrong, the episode is still truth.

### Layer 2 — `claims` (bi-temporal assertions)

A subject / predicate / object triple where each part may be an entity reference, a name, a
literal, or a JSONB payload. **Predicates are free-form text by design** — a new kind of fact
(`mentioned_budget_timing`, `evaluated_competitor`, `reports_to`) needs no migration.

Provenance columns, all mandatory:

- `source_episode_ids` — array, so one claim can cite several episodes
- `evidence_span` — the exact quoted text the claim rests on
- `extractor` — `agent:transcript_miner@v1`, `human:nl`, or a rule id

Bi-temporality:

- `valid_from` / `valid_to` — when the fact held **in the world**
- `tx_from` / `tx_to` — when the system **believed** it

Claims are never deleted. A retracted belief gets `tx_to` stamped. This is what makes "what did
we think on March 3rd?" answerable.

### Layer 3 — projection views (the read contract)

Application code reads views, not base tables, so read rules live in one place:

| View | Contract |
|---|---|
| `vw_facts` | **The canonical read.** Accepted, non-retracted claims inside their valid-time window |
| `vw_account_profile` | Account-centric rollup |
| `vw_account_signals` | External signals per account |
| `vw_action_items` | Open action items |
| `vw_pulse_events` | Timeline feed |

Views inherit RLS from their base tables. Because they are views, schema changes don't require
rebuilding them.

### Canonical KG nodes (stable per-tenant identity)

`competitors`, `account_competitors`, `objections`, `account_objections`, `account_successes`,
`account_action_items`, `account_recommendations`, plus two tiers of derived facts:
`derived_facts` (short-lived, TTL) and `historical_facts` (permanent, high-confidence).

### Edges

`relationships` — typed, **time-bounded** rows: `works_at`, `champion`, `decision_maker`,
`blocker`, `reports_to`, `acquired_by`, … Time bounds mean the graph reflects history, not just
the present state.

### Full table inventory

```
Tenancy/identity  tenants, users, memberships, oauth_accounts, entities,
                  entity_identifiers, resolution_requests, resolution_candidates
Canonical CRM     accounts, contacts, deals, activities,
                  account_lifecycle_events, contact_lifecycle_events
Ingest            connections, source_records, field_provenance, integration_audit
Knowledge graph   episodes, claims, relationships, embeddings, competitors,
                  account_competitors, objections, account_objections,
                  account_successes, account_action_items, account_recommendations,
                  derived_facts, historical_facts
HITL              fact_proposals, edge_proposals, node_proposals, review_decisions,
                  guardian_decisions, draft_proposals
Agent runtime     agent_runs, agent_run_costs, agent_outputs, batch_runs, sweeper_runs
Signals           signals, external_signals, alpha_feeds, account_next_best_actions
Outbound          outbound_campaigns, outbound_campaign_leads, outbound_events
Context/files     context_chunks, play_library, apify_run_log, audit_log
```

---

## 6. Multi-tenancy and isolation

Every tenant-scoped row carries `tenant_id`, and isolation is enforced **at the database** with
Row-Level Security. Three load-bearing parts — all three are required:

1. **An RLS policy on every tenant-scoped table**, filtering on a per-session GUC, written
   fail-closed: a request that forgot to set tenant context reads **zero rows** rather than
   erroring mid-query or leaking. (Later migrations use `NULLIF` on the GUC for PII tables.)
2. **A single `apply_tenant_rls` helper** that sets the GUC per HTTP request and per Temporal
   activity. One helper, not scattered `SET LOCAL` calls.
3. **A role split.** `gtm` (migrations, cross-tenant scripts) has **BYPASSRLS**. `gtm_app`
   (API, worker, agents) does **not**. Without this split RLS never fires against application
   traffic — this is the piece people forget, and it is the one that matters.

A user is a global identity; a `membership` ties a user to one tenant with a role.

Verify with `scripts/verify_tenant_isolation.py` plus cross-tenant regression tests in CI.

---

## 7. Ingestion — the connector framework

`packages/connectors/`. A provider is a declarative sub-package.

### What a provider declares

```
providers/<name>/
├── __init__.py       # ProviderSpec + register_provider(spec)
├── syncs.py          # @register_sync streams
├── actions.py        # @register_action write-backs (optional)
└── mapping.yaml      # raw field -> canonical entity mapping (optional)
```

**`ProviderSpec`** — identity, `auth_type` (`oauth_nango` | `api_key` | `platform_managed`),
capabilities, category, scopes, sync strategy, catalog status (`live`/`beta`/`coming_soon`),
`FieldSpec` list for the paste-token modal, and an async `verify` fn.

**`@register_sync`** — one decorated async function per stream. Mirrors Nango's `createSync`
shape: one Pydantic `CheckpointBase` subclass (the incremental cursor, stored as JSONB), one
Pydantic record model, one async exec fn whose only job is to page and call `ctx.batch_save(...)`.
Defaults on the checkpoint model must yield a valid "full sync from scratch" cursor.

**`@register_action`** — a typed, agent-callable write-back. Every action becomes one tool entry
on the agent loop. Three HITL modes:

- `auto` — execute immediately (prefer not to use it)
- `required` — **always** route through `draft_proposals`; the runtime refuses to fire unless the
  context was built via `ActionContext.from_approved_proposal`
- `tenant_setting` — defer to the tenant's autonomy slider, resolved before `exec_fn` runs

**Every action must go through `framework.invoke.invoke_action`.** Never call `spec.exec_fn`
directly. The guard enforces input validation, tenant/connection consistency, HITL gating, rate
limiting, audit, and output validation.

**`mapping.yaml`** — declarative raw→canonical field mapping. A provider that only lands raw rows
in `source_records` doesn't need one. Unmapped fields land in a `properties` JSONB overflow so
nothing is dropped silently.

### Providers present

`hubspot` (most complete; owns the production sync path), `salesforce`, `apollo`, `gmail`,
`outlook`, `slack`, `notion`, `crunchbase`, `heyreach`, `linkedin_apify`, and feed sources
`listen_notes`, `podchaser`, `newswire_rss`.

Unification stays gated per connector (`triggers_unification=False` by default) until that
provider's mapping is wired.

### Auth

Nango owns OAuth and the proxy. The **read loop is owned in-repo** (Temporal), not Nango's hosted
sync runtime. Direct-API credentials (HeyReach etc.) are Fernet-encrypted at rest with
`CONNECTOR_CREDENTIALS_KEY`.

---

## 8. Unification — raw records to canonical entities

`packages/unification/` + `packages/identity/`. Runs in `gtm-worker` as a Temporal workflow.

- `entity_resolver.py` — match a raw record against existing canonical entities
- `entity_merge.py` / `merger.py` — merge fields with provenance recorded in `field_provenance`
- `domain_naming.py` — registrable-domain normalisation (via `tldextract`)
- `lifecycle_writer.py` — emits `account_lifecycle_events` / `contact_lifecycle_events`

Resolution tiers:

1. **Exact identifier** — `entity_identifiers` (email, domain, external id) via
   `gtm_identity.Resolver` + `normalize_identifier`. Post-migration-041 this is one shared
   namespace for both connector ingestion and agent proposals.
2. **Fuzzy** — `rapidfuzz.token_sort_ratio` for noisy strings ("HubSpot Inc." vs "HubSpot, Inc").
3. **LLM judge** — `packages/identity/llm_judge.py` for genuinely ambiguous pairs.
4. **Probabilistic sweep** — the KG Sweeper (`services/agents/kg/sweeper`) runs Splink
   (Fellegi–Sunter) on a DuckDB backend over per-tenant batches under ~100k canonical rows.
   Block key is the registrable domain. Ships with docs-default m/u priors; EM tuning deferred.
   Results land in `sweeper_runs` and as merge proposals, never as direct merges.

---

## 9. Scraping — everything external, in detail

This is the part most rebuilds get wrong. Read it fully.

### 9.1 Architecture

Every scrape goes through **one client**: `ApifyClient.invoke_actor(logical_name, ...)` in
`packages/connectors/framework/apify.py`. The client looks up a
`(actor_id, version, output_model, estimated_cost_usd)` pin in `framework/pinned_actors.py`.

Nothing calls Apify directly. Nothing hardcodes an actor id at a call site.

### 9.2 The pin registry

`PINNED_ACTORS: dict[str, ActorPin]` — logical name → pin. A pin carries:

- `actor_id` — **tilde form** (`apimaestro~linkedin-profile-detail`). The Apify v2 REST API 404s
  on the slash form even though the Store URL uses slashes. This bites everyone once.
- `version` — pinned build. **The cache key includes the version**, so a bump auto-invalidates.
  Empty string means unpinned (accepted for actors whose build ids churn).
- `output_model` — a Pydantic model. A shape mismatch raises `ApifyResponseValidationError`,
  which is **non-retryable** (a retry returns the same broken shape; operator action is to bump
  the pin and update the model).
- `estimated_cost_usd` — the budget pre-flight default. Refresh when actuals diverge >25%.
- `list_response_field` — for dataset-list-shaped actors.

**Version drift detection:** if the live actor's build list doesn't include the pinned version,
the client logs `WARN` — it does not halt.

### 9.3 The complete pinned actor table

**LinkedIn — apimaestro suite (rich, per-profile)**

| Logical name | Actor | Ver | ~$/call | Purpose |
|---|---|---|---|---|
| `li_person_profile` | `apimaestro~linkedin-profile-detail` | 1.4.2 | 0.05 | Full person profile |
| `li_company_profile` | `apimaestro~linkedin-company-detail` | 1.2.1 | 0.04 | Full company profile |
| `li_post_scraper` | `apimaestro~linkedin-profile-posts` | 1.3.0 | 0.06 | Person's recent posts |
| `li_company_post_scraper` | `apimaestro~linkedin-company-posts` | 1.0.0 | — | Company page posts |
| `li_url_health_check` | `apimaestro~linkedin-profile-detail-light` | 0.2.0 | 0.001 | Status only — is the URL still live? No body fetched. |
| `li_post_comments_scraper` | `apimaestro~linkedin-post-comments-replies-engagements-scraper-no-cookies` | pinned build | ~0.005 | Comment-reply suggestions |
| `li_posts_keyword_search` | `apimaestro~linkedin-posts-search-scraper-no-cookies` | — | — | Alpha-feed keyword search |

The **no-cookies** variants are a deliberate account-safety posture: no LinkedIn session token
ever round-trips through Apify.

**LinkedIn — harvestapi suite (cheap, dataset-list)**

| Logical name | Actor | ~$/call | Purpose |
|---|---|---|---|
| `linkedin_company_harvest` | `harvestapi~linkedin-company` | 0.004 | Company firmographics |
| `linkedin_employees_harvest` | `harvestapi~linkedin-company-employees` | 0.15 (50 × $0.003) | Employee list |
| `linkedin_person_harvest` | `harvestapi~linkedin-profile-scraper` | 0.004 | Person profile |
| `linkedin_company_search_harvest` | `harvestapi~linkedin-company-search` | 0.001 | Slug finder (free tier) |
| `linkedin_job_search` | `harvestapi~linkedin-job-search` | 0.001 | Hiring-spike signal |
| `linkedin_company_posts_harvest` | `harvestapi~linkedin-company-posts` | 0.0015 | Company posts |
| `linkedin_profile_posts_harvest` | `harvestapi~linkedin-profile-posts` | 0.0015 | Person posts |

**News, firmographics, web**

| Logical name | Actor | ~$/call | Purpose |
|---|---|---|---|
| `google_news_scraper` | `epctex~google-news-scraper` | 0.005 | News signal source |
| `newswire_rss` | `hgservices~pr-newswire-scraper` | 0.002 | Press-release feed |
| `crunchbase_company_scraper` | `vulnv~crunchbase-scraper-pro` | ~0.0063 | Firmographics + funding rounds. Input shape `company_urls=[{"url": ...}]`. Replaced `magicfingers~crunchbase-scraper`, which returned 0 items. |
| `website_tech_stack_detector` | `benthepythondev~tech-stack-detector` | 0.003 | Tech-stack signal |

**Growth report suite**

| Logical name | Actor | ~$/call | Purpose |
|---|---|---|---|
| `growth_similarweb` | `ecomdate~similarweb-scraper` | 0.30 | Traffic + engagement |
| `growth_ahrefs` | `radeance~ahrefs-scraper` | 0.20 | DR, backlinks, ref domains |
| `growth_seo_audit` | `UFSUQD7pWNwN3jExC` | 0.50 | On-site SEO crawl (≤20 pages) |
| `growth_google_serp` | `nFJndFXA5zjCTuudP` | 0.10 | Category-query SERP |
| `growth_reddit` | `trudax~reddit-scraper-lite` | 0.15 | Brand mentions (≤50) |
| `growth_instagram` | `apify~instagram-profile-scraper` | 0.10 | Profile + follower stats |
| `growth_tiktok` | `clockworks~tiktok-profile-scraper` | 0.10 | Profile + follower stats |
| `growth_screenshot` | `apify~screenshot-url` | — | Page capture. **Deliberate substitute for Playwright** — agent workers ship no browser runtime, and the actor path gets the budget gate + cache for free. |

### 9.4 Cost, cache, and budget controls

- **Per-tenant 24h cache**, keyed on `(tenant_id, actor_id, version, input_hash)`. The tenant id
  is *inside* the hash and the PK is composite — this is what prevents a cross-tenant cache hit.
- **Pre-flight budget check** against today's spend:
  `SUM(agent_run_costs.external_api_cost_usd) WHERE api_vendor='apify'`, versus
  `tenant_settings.apify_daily_budget_usd` (default **$10.00**).
- Over budget → `BudgetExceededError`. Temporal does **not** honour a `non_retryable` attribute
  on arbitrary exceptions, so the calling activity catches it and re-raises
  `ApplicationError(..., non_retryable=True)`. Same pattern for
  `ApifyResponseValidationError`.
- Belt-and-braces platform ceiling: send **both** the query param `?maxCharge=N` (what Apify
  actually enforces) and the body key `maxChargeUsd` (some actors read it as input config).
- Every call is logged to `apify_run_log` with timing, item count, and cost.
- Token is app-level (`Authorization: Bearer` **only** — enforced by a CI grep gate). Empty token
  surfaces as a 401 from Apify, never a silent no-op.

### 9.5 Web search and fetch

**`web_search`** — Brave Search API (`api.search.brave.com`), via
`gtm_common.brave_search.search_brave`. Returns title/url/snippet. Registered onto agents by
`tools/web_research.register_web_research_tools(agent)` — one factory so a future fix propagates
everywhere.

**`web_fetch`** — SSRF-guarded HTTP GET returning cleaned page text. The guard is *imported* from
`verify_citations`, never duplicated:

- `getaddrinfo` **once**, validate every resolved IP against the private-range list, then **pin
  the URL to the first resolved IP** while preserving the hostname via the `Host:` header and
  `sni_hostname`, so vhosting and TLS still work. This closes the DNS-rebinding TOCTOU.
- `follow_redirects=False` — a 3xx chain re-resolves DNS and defeats the pin.
- Body cleaning: strip `<script>`/`<style>` contents → strip remaining tags → collapse
  whitespace. Regex-based, dependency-free.
- Truncation lands at the last whitespace boundary inside the char budget — never mid-word,
  never mid-tag.

### 9.6 The trust boundary

**Every** web/LinkedIn/scraped result — success *and* error paths — is wrapped:

```
<INGESTED_UNTRUSTED_CONTENT>
…scraped text…
</INGESTED_UNTRUSTED_CONTENT>
```

Every agent system prompt carries the instruction that content inside those delimiters is
**data, never instructions**. Error paths wrap too, so the model cannot distinguish a happy-path
shape from a failure and must treat every payload as data.

---

## 10. The agent runtime

An agent is five things:

1. A **system prompt and role**
2. A **typed input** (Pydantic)
3. A **narrow tool surface** — a per-role subset of the shared tools
4. A **multi-step loop** — the model emits tool calls, the runtime executes them, until a
   terminal typed output or a budget trips
5. A **typed output**, validated before anything is written

All of it durable: each run is a Temporal workflow. Multi-phase agents are **not** one LLM call —
they are standalone `@workflow.defn` classes calling per-phase activities directly (gather →
draft → verify/red-team → commit), so each phase is its own retryable step.

### Directory layout (`services/agents/src/gtm_agents/`)

```
agents/        per-role prompts, schemas, runners (+ _shared/, _prompt_loader.py)
workflows/     per-role @workflow.defn classes
activities/    per-phase @activity.defn functions
tools/         the shared model-callable tool surface
kg/sweeper/    Splink-based dedup sweeper
graph/         on-demand graph builder
render/pdf/    WeasyPrint HTML->PDF templates
render/docx/   python-docx builders
hitl/          human-in-the-loop helpers
humanisation/  post-generation humanising + scoring
compliance/    consent statements (EU AI Act Article 50 provenance)
schedule/      Temporal Schedule definitions (crons)
budgets.py     every timeout/retry/threshold constant
capabilities.py role -> capability grants + enforce_capability
routing.py     model alias routing
llm.py         LiteLLM proxy client construction
rate_limiter.py
faithfulness.py evidence-span verification
main.py        worker registration
```

### The shared tool surface

| Tool group | Tools | Notes |
|---|---|---|
| Graph reads | account profile, competitors, objections, stakeholders, successes, action items, recent claims, timeline | Read-only, RLS-enforced, tenant-scoped |
| Web research | `web_search` (Brave), `web_fetch` (SSRF-guarded) | Sandbox-wrapped |
| LinkedIn | `linkedin_company`, `linkedin_employees`, `linkedin_person`, `linkedin_person_posts` | Apify-backed, per-call cost logged |
| Connector actions | Adapter turning `registry.all_actions()` into model-callable tool blocks | Input validation, tenant check, HITL gate, rate limit, audit trail |
| Memory | `memory_fs` — a per-run filesystem-shaped scratchpad (Anthropic `memory_20250818` shape) backed by the files store | Read via `USE_MEMORY`; write via `MEMORY_WRITE` **plus** a per-role path-prefix whitelist |
| Delegation | `subagent` — child-workflow dispatch so one agent can call another (e.g. Prospect → Battle Card) | `DELEGATE_TO_SUBAGENT` |

### Capabilities

```python
class Capability(StrEnum):
    READ_GRAPH, PROPOSE_CLAIM, PROPOSE_MERGE, PROPOSE_ACTION,
    WEB_ACCESS, USE_MEMORY, MEMORY_WRITE, DELEGATE_TO_SUBAGENT,
    EXECUTE_OUTREACH   # reserved — NO role holds it in v1
```

`ROLE_CAPABILITIES: dict[str, set[Capability]]` grants narrow subsets — prefer explicit grants
over convenience bundles so a cross-role leak is obvious in a diff.
`enforce_capability(role, tool_name)` is the **first line of every tool activity**. Orchestrator
activities (`commit_dual_sink`, `gather_context`, `verify_citations`) bypass it intentionally —
they are deterministic pipeline stages, not model-callable tools.

### Budgets, retries, and thresholds (`budgets.py` — one source of truth)

```
Per-activity timeout    5 min
Per-workflow timeout    30 min
Heartbeat timeout       30 s
Retry                   3 attempts, exponential 1s -> 4s -> 16s
Edge budget             20 edges per entity per enrichment run (hard drop + structured log)
AUTO_APPROVE_THRESHOLD  0.85   (>=0.85 AND guardian != 'hitl' -> approved + canonical write
                                in the same transaction)
HITL_ROUTE_THRESHOLD    0.70   (<0.70 -> HITL with reason; 0.70-0.85 -> pending middle band,
                                surfaces in /review)
```

**There is deliberately no auto-reject threshold.** Low-confidence rows route to HITL, they are
never silently dropped. A pytest gate asserts the symbol does not exist, so re-adding it breaks
loudly.

Rate-limit handling: a global provider 429 **is** retryable (Temporal backoff absorbs it). A
per-tenant LiteLLM budget-exceeded 429 is **not** — the tenant must top up, so surface it rather
than burning retry budget. `is_budget_exceeded_error()` is the classifier.

### Task queues

Env-suffixed so a laptop worker can never drain a prod-enqueued task even on a shared namespace:

```
gtm-sync-tasks-{env}                   worker: connector sync + unification
gtm-agent-tasks-{env}                  shared: enrichment, LinkedIn family, outbound,
                                       alpha feed, signal monitor, growth report, NBA,
                                       orchestrator sweep, files GC, context index
gtm-agent-transcript-miner-tasks       per-role
gtm-agent-synthesiser-tasks            per-role
gtm-agent-prospect-tasks               per-role
gtm-agent-battle-card-tasks            per-role
```

One Cloud Run service runs several `Worker` instances in one process, each polling its own queue.

### Agent run ledger

Every run writes an `agent_runs` row: input, status, memory, per-step scratch log, cost, trace id.
`agent_runs.role` is constrained by a CHECK, mirrored in code by
`gtm_db.agent_roles.VALID_AGENT_RUN_ROLES`, with a live-DB test asserting the two sets are equal.

> **Adding a role is a two-step change and both are required:** add the string to the frozenset
> *and* ship a migration recreating `ck_agent_runs_role`. Skip the migration and the first
> activity dies on a CHECK violation — and because most triggers are fire-and-forget, it fails
> **silently**. This has shipped as a bug twice.

Current roles: `transcript-miner`, `synthesiser`, `prospect`, `battle-card`, `account-intel`,
`li_person_audit`, `li_company_audit`, `linkedin_post_generator`, `linkedin_humanizer`,
`outbound_sequence`, `outbound_sequence_generator`, `linkedin_to_twitter`, `li_comment_replies`,
`account_nba_generator`, `account_orchestrator`, `build_tam`, `email-composer`, `growth_report`.

### Standard workflow skeleton

Every multi-phase workflow follows the same shape — copy it:

```python
@workflow.defn
class SomethingWorkflow:
    @workflow.run
    async def run(self, inp: AgentRunInput) -> AgentRunResult:
        # replay-safe primitives computed ONCE at body entry
        today_iso = ...          # trusted date injection into prompts
        run_id = workflow.info().run_id

        await workflow.execute_activity(create_agent_run_row_impl, ...)
        try:
            for phase in (load, discovery, collect, analysis, commit):
                try:
                    result = await workflow.execute_activity(phase, ...)
                    self._phase_events.append(...)      # append-only log
                except Exception as e:
                    return await self._classify_and_finalize(e)
        except Exception:
            return await self._finalize("failed")

    @workflow.query("get_phase_events")
    def get_phase_events(self) -> list[dict]: ...
```

Rules that fall out of it:

- **Replay safety**: compute dates and ids once at body entry, never inside a loop.
- **Payload discipline**: large intermediates (scrape bundles) go to GCS scratch; only the
  object name crosses the Temporal payload boundary.
- **Alias discipline**: the workflow body records `"claude-opus"` / `"claude-sonnet"` in
  `ai_generation_metadata` for Article 50 provenance; actual model construction happens in the
  runner via `build_model_for`.
- **Untimed `wait_condition` is banned** — CI enforces it. Every HITL wait carries a timeout.

---

## 11. The agent roster

### Research and content pipelines (each renders an artifact)

| Agent | Phases | Output |
|---|---|---|
| **Transcript Miner** | ingest → extract → semantic dedupe against existing claims → commit | Claim proposals with citations |
| **Synthesiser** | gather → draft → review | Brief paragraph, facts table, timeline snapshot |
| **Account Intelligence** | single structured pipeline | Deal-health score + label, health factors, stakeholder map, competitive landscape, objection history, recommended approach, next steps, risks, opportunities |
| **Prospect** | parallel research (institution, people, technology, financial, competitive) → pricing → verification → synthesis → review → commit+render | 10-section PDF dossier |
| **Battle Card** | parallel research (company, product, sentiment) → verification → merge → generation → optional deep dive → review → commit+render | Competitor battle card PDF |
| **Knowledge Base** | gather → draft → red-team → commit | Structured doc about the customer's *own* org, from domain + LinkedIn slugs |
| **Outbound Sequence** | load_context (KG) → drafting (Opus gen + Sonnet review) → commit | `draft_proposals` + DOCX playbook. Stops at a pending draft; live HeyReach execution is a separate piece. |
| **Growth Report** | load_account → discovery (Sonnet web research) → collect (Apify fan-out + AI-visibility + screenshots → GCS bundle) → analysis (Opus structured + Sonnet review) → commit | DOCX + `agent_outputs` + `/v1/files` projection |
| **LinkedIn family** | person audit, company audit, post generator (in captured voice), comment-reply suggester, linkedin→twitter | Audits render; content drafts go to the HITL queue with AI-generation metadata |

### Helper roles (composed by the above)

| Agent | Job |
|---|---|
| **Extractor** | Pull candidate KG entries (competitor, objection, stakeholder, claim) from a document, with confidence scores and evidence spans |
| **Guardian** | Reconcile candidates against the existing graph → `match` / `new` / `escalate`, plus implied edges |
| **Red Team** | Generic critic — re-check another agent's claims against the same graph and web sources, return pass/fail with issues |
| **Report Writer** | Reshape a prospect result into the closed 10-section report for PDF rendering |

### Signal and conversational roles

| Agent | Job |
|---|---|
| **Signal Evaluator** | Score one raw signal against account context for importance, suggest a claim predicate. One cheap Haiku call. |
| **Alpha Scorer** | Score alpha-feed posts against the tenant's ICP |
| **ICP Capture** | Conversational interview → structured ICP definition |
| **Ask** | Page-aware drawer chat, grounded in the current page, light tool support, **no surface mutations** |
| **Account NBA** | Per-account next-best-action generation |
| **Account Orchestrator** | Sweep that decides which agents to run per account |
| **Build TAM** | TAM list construction |

### Scheduled workflows (Temporal Schedules in `schedule/`)

| Cron | What it does |
|---|---|
| `signal_monitor_cron` | Daily per tenant. Per account, **sequentially** across 5 sources (LinkedIn company, LinkedIn person contacts, Google News, LinkedIn jobs, tech stack) — sequential to respect Apify rate limits, ~4 calls/account/day × ~50 accounts. Each result: detect → gather context → evaluate → write. Scrape failures are soft (skip the source, continue). Ends with one GCS markdown digest per account per day. |
| `alpha_feed_cron` | 04:00 UTC, one execution per active feed. Load config → cadence check (skip if <24h) → concurrent sage + keyword scrape → score/dedupe/store to `external_signals` (`signal_category='alpha'`) → advance cadence → stamp `last_collected_at` |
| `synthesiser_cron` | Periodic account synthesis |
| `sweeper_cron` | KG dedup sweep (Splink) |
| `account_orchestrator_sweep_cron` | Per-account agent orchestration |
| `linkedin_url_health_check_cron` | Cheap status-only check that tracked LinkedIn URLs are still live |
| `voice_refresh_daily_cron` | Refresh captured voice profiles |
| `files_gc_cron` | Garbage-collect orphan blobs |

---

## 12. Artifacts, HITL, and the review loop

### Three deliberately distinct output patterns

| Pattern | Used by | Storage |
|---|---|---|
| **Research artifact** | Prospect, Battle Card, Synthesiser, Account Intel, KB, LinkedIn audits, Growth Report | `agent_outputs` row + rendered PDF (WeasyPrint) or DOCX (python-docx) in GCS, projected into `/v1/files` |
| **Content draft** | LinkedIn posts, comment replies, outbound sequences, composed emails | `draft_proposals` row in the approval queue — **can never auto-send** |
| **UI suggestion** | one-shot suggestions (competitor suggestion, NBA) | JSONB blob on the run row |

### The promotion path

```
agent emits fact / edge / node
        │
        ▼
fact_proposals | edge_proposals | node_proposals   (status = pending)
        │
        ├── confidence >= 0.85  AND guardian != 'hitl'  ──► approved + canonical write
        │                                                   (same transaction)
        ├── 0.70 <= confidence < 0.85 ──► pending middle band, surfaces in /review
        ├── confidence < 0.70          ──► HITL with reason
        └── Guardian decision: match | new | escalate   (logged to guardian_decisions)
                │
                ▼
        human decision recorded in review_decisions
```

**The faithfulness gate** (`faithfulness.py` + `activities/verify_citations.py`): any claim whose
`evidence_span` is not literally present in its cited episodes is **rejected**. This is the single
control that keeps hallucinated facts out of the graph — build it early, not late.

Thresholds are per-tenant (`load_tenant_thresholds_activity`) with the 0.85 / 0.70 defaults.

---

## 13. API and frontend

### API — `services/api` (FastAPI, port 8000)

41 route modules, grouped by surface:

```
Auth/identity     auth, users, voice_consent
Entities          accounts, contacts, deals, activities, episodes
Knowledge graph   competitors, proposals, review, review_models, foundation
Agents            runs, agent_outputs, agent_admin, enrichment_admin,
                  account_intelligence, account_synthesis, account_next_moves,
                  knowledge_base, reports, plays
Signals           pulse, alpha_feeds, tam
Content           drafts, composer, outbound, chat
Files             files, files_search, file_bindings, file_bindings_write,
                  file_counts, context
Connectors        connections, webhooks
Admin/ops         admin_costs, admin_kg, health
```

Supporting: `deps.py` (DI: current user, tenant, session), `middleware/` (tenant RLS application,
CORS, request id), `schemas/`, `services/`, `pagination.py`, `slug.py`.

Auth: OAuth via Authlib (Microsoft Entra + Google Workspace) plus magic links; sessions are
`itsdangerous`-signed cookies with a **key ring** (`session_signing_key` +
`session_signing_key_previous`) so keys rotate without logging everyone out.

### Frontend — `frontend/` (Next.js 16, React 19)

| Piece | Choice |
|---|---|
| Framework | Next.js 16 App Router, React 19 |
| Styling | Tailwind v4 (`@tailwindcss/postcss`) |
| Primitives | Radix UI (avatar, collapsible, dialog, dropdown, popover, tabs, tooltip, visually-hidden) |
| Chat | Vercel AI SDK (`ai`, `@ai-sdk/react`) + assistant-ui (`@assistant-ui/react`, `-ai-sdk`) |
| Data | `openapi-fetch` against types generated by `openapi-typescript` |
| Extras | `cmdk` (command palette), `lucide-react`, `react-virtuoso`, `react-markdown` + `remark-gfm` + `rehype-slug` + `rehype-autolink-headings`, `sonner` (toasts), `@dnd-kit`, `@nangohq/frontend` (Connect UI) |

**API client is generated, never hand-written:**

```bash
npm run codegen   # curl $API_SCHEMA_URL/openapi.json -> openapi/schema.json
                  # openapi-typescript -> src/lib/api/schema.d.ts
```

CI runs an **OpenAPI drift check** — a backend route change that isn't regenerated fails the build.

Route groups: `(auth)` and `(app)` with `accounts`, `contacts`, `deals`, `pipeline`, `review`,
`chat`, `composer`, `files`, `library`, `foundation`, `knowledge-base`, `icps`, `alpha-feed`,
`outbound`, `tam`, `settings`, `team`, `users`, `your-brand`, `admin`.

Auth guard is an **edge proxy** (`src/proxy.ts`): if the `gtm_session` cookie is absent on a
protected path, redirect to `/login?next=…`. It deliberately does **not** verify the cookie — the
API is the source of truth and 401s on a tampered cookie, at which point the `(app)` layout's
`fetchMe()` redirects again.

CI guardrail: **no `localhost:8000` hardcoded anywhere in the frontend.**

---

## 14. Build order — 14 milestones

Each milestone is independently demoable. Don't reorder 1–5.

**M1 — Workspace skeleton.** `pyproject.toml` with `[tool.uv.workspace]` members and
`[tool.uv.sources]` marking each `gtm-*` as `{ workspace = true }`. Ruff/pyright/pytest config.
`Makefile` (`sync`, `up`, `down`, `migrate`, `lint`, `typecheck`, `test`, `check`, `ci-local`).
`docker-compose.yml` for postgres/redis/temporal/temporal-ui/nango. `infra/init-db.sh` creating the
`nango` and `litellm` databases alongside `gtm_os` (Temporal's own DB is created by the
`auto-setup` image).

**M2 — `packages/db` + tenancy.** Base model, `tenants`, `users`, `memberships`, async session,
Alembic set up for **hand-written** migrations. Then, immediately, the RLS spine: policies on
every tenant-scoped table keyed on a session GUC, the `apply_tenant_rls` helper, and the
`gtm` / `gtm_app` role split with `gtm_app` lacking BYPASSRLS. Write
`verify_tenant_isolation.py` now — retrofitting isolation is the most expensive rewrite in this
system.

**M3 — `packages/common`.** `pydantic-settings` `Settings`, Temporal client factory,
`llm_completion` + `llm_embed`, `brave_search`, GCS signed-URL helper, Secret Manager accessor,
health probe.

**M4 — Knowledge graph schema.** `episodes`, `claims` (bi-temporal, free-form predicates,
provenance columns), `relationships`, `embeddings` with pgvector, the KG node tables, and the
projection views (`vw_facts` first). Seed a tenant and hand-write claims to prove the views.

**M5 — `gtm-api` skeleton.** FastAPI app, auth (OAuth + magic link + signed sessions), tenant
middleware applying the RLS GUC, `/health`, and read routes over accounts/claims. Enable the
OpenAPI schema endpoint — the frontend contract depends on it.

**M6 — `gtm-worker` + connector framework.** `ProviderSpec`, `@register_sync`,
`@register_action`, `invoke_action` guard, `mapping.yaml` loader, `NangoClient`. Ship **HubSpot
first, end to end** into `source_records`. Then the unification workflow → canonical entities,
with `field_provenance`.

**M7 — `gtm-agents` skeleton + LiteLLM.** `litellm/config.yaml` with the aliases (`num_retries: 0`),
`scripts/run_litellm_local.sh` bootstrapping `.venv-litellm`, per-tenant virtual keys. Then
`budgets.py`, `capabilities.py`, `agent_runs` + the role allowlist + its CHECK constraint, and
the `agent_run_lifecycle` activities. Prove the loop with one trivial role.

**M8 — Proposals + HITL.** `fact_proposals` / `edge_proposals` / `node_proposals` /
`review_decisions` / `guardian_decisions`, the confidence-threshold promotion path, the
faithfulness / evidence-span gate, and the `/v1/review` API. **Do this before the second agent.**

**M9 — First real agent: Transcript Miner.** ingest → extract → semantic dedupe → commit. This
exercises episodes, claims, proposals, faithfulness, and the review queue in one pipeline. When
it works, the spine is real.

**M10 — Tool surface.** Graph reads, `web_search` (Brave), `web_fetch` (SSRF guard + DNS pin +
sandbox wrap), memory_fs, subagent dispatch, connector-action adapter. Enforce capabilities at
every tool's first line.

**M11 — Scraping.** `ApifyClient` with pin registry, per-tenant cache, budget pre-flight,
`apify_run_log`, non-retryable error mapping. Then the LinkedIn tools on top.

**M12 — Render + artifacts.** WeasyPrint PDF templates, python-docx builders, `agent_outputs`,
`packages/files` (GCS store, folders as entities, upload pipeline with magic-byte MIME
validation), and `/v1/files`.

**M13 — The agent fleet.** Synthesiser → Account Intelligence → Battle Card → Prospect →
Knowledge Base → LinkedIn family → Outbound → Growth Report. Each follows the M9 skeleton, so
each is additive. Add signals (Signal Monitor, Alpha Feed) and their Temporal Schedules.

**M14 — Frontend.** Next.js app, `npm run codegen` against the live OpenAPI schema, edge auth
proxy, then surface by surface: accounts → review queue → chat → files → composer → signals.

Cross-cutting, start at M1 and never let it lapse: CI (`ruff`, `pyright`, migration round-trip,
pytest, OpenAPI drift, frontend lint/typecheck/build, the custom guardrails).

---

## 15. Local development environment

```bash
git clone <repo> ~/workspace/gtm-os && cd ~/workspace/gtm-os
cp .env.example .env                   # fill in secrets
make sync                              # uv sync --all-packages  -> .venv
make up                                # docker compose up -d --wait
make migrate                           # alembic upgrade head
cd frontend && npm install && cd -
```

`make sync` is mandatory. A plain `uv sync` installs the root project and **skips the workspace
members** — wrong for this repo.

**Two virtualenvs, on purpose:**

| venv | Created by | Owns |
|---|---|---|
| `.venv/` | `make sync` | all workspace packages (editable) + dev tools + the `litellm` *library* |
| `.venv-litellm/` | `make litellm` → `scripts/run_litellm_local.sh` | `litellm[proxy]` + `prisma` + `langfuse` — the proxy *server* |

**Run everything** (each in its own terminal so logs stay visible):

| What | Command | Port |
|---|---|---|
| Infra | `make up` | 5434 / 6379 / 7233 / 8088 / 3003 |
| LiteLLM proxy | `make litellm` | 4000 |
| API | `uv run uvicorn gtm_api.main:app --reload --reload-dir services/api/src --reload-dir packages --port 8000` | 8000 |
| Worker | `uv run python -m gtm_worker.main` | — |
| Agents | `uv run python -m gtm_agents.main` | — |
| Frontend | `cd frontend && npm run dev` | 3000 |

The `--reload-dir` flags are load-bearing: without them the watcher scans `frontend/`, `.venv/`,
and `viz/`, and a save anywhere triggers a useless restart. Temporal workers have no hot reload —
restart by hand after editing.

Temporal UI: `http://localhost:8088`. Nango dashboard: `http://localhost:3003` (`admin`/`admin`).

**Migrations** — hand-written, never `--autogenerate`:

```bash
make migration MSG="add foo column"   # create the revision, then edit it
make migrate                          # upgrade head
make reset-db                         # wipe + recreate gtm_os
```

`make migrate` connects as `gtm` (BYPASSRLS) and passes `GTM_APP_DB_PASSWORD` so the role-split
migration can create `gtm_app` on first run. In prod the role is pre-created and the password
lives in Secret Manager.

**Useful scripts:** `seed_tenants.py`, `seed_litellm_local_keys.sh`, `seed_secrets.sh`,
`seed_play_library.py`, `seed_knowledge_base.py`, `run_unification.py`, `review_claims.py`,
`auto_promote_claims.py`, `verify_tenant_isolation.py`, `verify_agent_queue.py`,
`provision-files-bucket.sh`, `dump_state.py` / `debug_state.py`.

---

## 16. CI, deploy, and infrastructure

### CI (GitHub Actions, `.github/workflows/ci.yml`)

Backend job runs against **real** pgvector + Redis services (not mocks), then:

1. `ruff check .`
2. `pyright`
3. Alembic **round-trip** migration check (up and back down)
4. `pytest -m 'not local and not slow'`
5. **OpenAPI drift check**
6. Frontend `lint`, `typecheck`, `build`
7. Custom guardrails, each a CI step:
   - no `localhost:8000` hardcoded in the frontend
   - no untimed `wait_condition` in `services/agents` (HITL timeout discipline)
   - KG reads don't bypass the intended path (`check_direct_folder_kg_read.sh`)
   - Apify token used as `Authorization: Bearer` only

**Concurrency gotcha, learned the hard way:** workflow-level `cancel-in-progress` cancels the
entire run *including* jobs with their own `concurrency: cancel-in-progress: false` override —
per-job concurrency controls queueing, not shielding. So: cancel stale PR runs, **never** cancel
main. Main pushes deploy; the deploy job's own group serialises rollouts.

### Test markers

```
(default)   pytest -m 'not local and not slow'     what CI runs
local       belt-and-braces (prompt byte-hash fidelity, extra="forbid" repetition,
            module-imports-cleanly). Every prompt edit invalidates them in lockstep,
            so they gate pushes, not deploys. `make test-local` before pushing.
slow        integration / latency tests
```

### Infrastructure (Terraform, `infra/terraform/`)

`main.tf`, `cloud-run.tf`, `database.tf` (Cloud SQL), `redis.tf` (Memorystore), `gcs.tf`,
`iam.tf`, `secrets.tf`, `networking.tf`, `loadbalancer.tf`, `registry.tf`, `tenants.tf`,
`outputs.tf`, `variables.tf`, `prod.auto.tfvars`.

Deploy targets: `api`, `frontend`, `worker`, `agents`, `litellm` — Cloud Run services, one
region, behind a load balancer. The LiteLLM service is `ingress=internal`; worker and agents mint
Google-signed ID tokens from the Cloud Run metadata server to reach it (the helper skips fetching
when the target is `localhost` or no metadata server is reachable).

Secrets in Secret Manager, mounted as Cloud Run env vars: `session-signing-key`,
`connector-credentials-key`, `brave-api-key`, `litellm-virtual-key-{slug}`, provider API keys.

Docker note: the agents image needs WeasyPrint's system deps (`libpango-1.0-0` et al) and
`libmagic1`. Copy **every** workspace package into the build context — a missing
`packages/identity` surfaced as a `ModuleNotFoundError` on first prod boot.

---

## 17. Conventions that keep the codebase coherent

These are cheap to adopt on day one and expensive to retrofit.

- **Hand-written migrations only.** No `--autogenerate`.
- **Never truncate with `[:N]`.** Cut at a whitespace boundary within a char budget.
- **Aliases, not model ids, at call sites.** `model="claude-sonnet"`, never
  `"anthropic/claude-sonnet-4-6"`. The proxy config owns the mapping.
- **Inject the date into prompts.** Compute `today_iso` once at workflow body entry and pass it
  in; models otherwise reason from their training cutoff.
- **ASCII only in prompt files and generated content** unless there's a reason.
- **Long natural-language prompt lines are exempt from E501** via `per-file-ignores` — wrapping
  mid-sentence hurts both the model's parse and the reader's eye. Pydantic
  `Field(description=...)` strings are the LLM's contract surface; don't wrap them either.
- **Pyright false positives from side-effect decorators** (`@agent.tool`, `@router.get`,
  `@activity.defn`, `@workflow.defn`) and FastAPI trigger-only `Depends()` params are silenced
  globally (`reportUnusedFunction`/`reportUnusedVariable = "none"`), not per-line.
- **`B008` is suppressed only under `services/api`** — `Depends()` in a default is FastAPI's
  intended idiom, not a bug.
- **Comments carry the *why*, including the incident.** Much of this repo's value is in comments
  recording why a pin changed, why an actor was swapped, why a constant is what it is. Keep that
  habit; it is what makes the pins auditable.
- **Every constant that fans out lives in `budgets.py`** and is pinned by a test, so a silent
  retune is impossible.
- **Structured logs on every hard drop** (edge budget, cache eviction, version drift) — silent
  drops are how data loss hides.

---

## 18. Complete environment variable reference

```bash
# === Database ===
DATABASE_URL=postgresql+asyncpg://gtm:gtm@localhost:5434/gtm_os
DATABASE_URL_SYNC=postgresql://gtm:gtm@localhost:5434/gtm_os
GTM_APP_DB_PASSWORD=gtm_app          # consumed by the role-split migration on first run

# === Redis ===
REDIS_URL=redis://localhost:6379/0

# === Temporal ===
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TLS_CERT_PATH=              # prod: Temporal Cloud mTLS
TEMPORAL_TLS_KEY_PATH=

# === LLM providers (consumed by the LiteLLM proxy) ===
ANTHROPIC_API_KEY=
OPENAI_API_KEY=                      # embeddings only
MOONSHOT_API_KEY=                    # kimi-k2 alias
MINIMAX_API_KEY=                     # minimax alias
OPENROUTER_API_KEY=                  # openrouter-* aliases; also enables OR embeddings

# === LiteLLM proxy wiring ===
LITELLM_PROXY_URL=http://localhost:4000
LITELLM_PROXY_KEY=sk-gtm-local
LITELLM_MASTER_KEY=sk-gtm-local
LITELLM_DEFAULT_MODEL=claude-sonnet  # an ALIAS, not a provider model id
AGENT_MODEL=claude-sonnet
LITELLM_VIRTUAL_KEY_<TENANTSLUG>=    # one per tenant; empty -> raises, no master-key fallback

# === Embeddings (direct to provider, not proxied) ===
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536

# === Connectors ===
NANGO_SECRET_KEY=
NANGO_HOST=http://localhost:3003
NANGO_PUBLIC_URL=                    # when Nango sits behind a VPC
NANGO_ENCRYPTION_KEY=
CONNECTOR_CREDENTIALS_KEY=           # Fernet key for direct-API creds
COMMONROOM_WEBHOOK_SECRET=

# === Scraping / data vendors ===
APIFY_TOKEN=                         # app-level; Bearer header only
BRAVE_API_KEY=                       # agent web_search; empty -> raises
PODCHASER_API_KEY=
HEYREACH_API_KEY=                    # LinkedIn outbound execution
HEYREACH_WEBHOOK_SECRET=             # authenticates inbound deliveries (path segment)

# === Storage / GCP ===
GCP_PROJECT=
GCS_REPORTS_BUCKET=                  # agent PDFs — 5min signed reads, no deletes
GCS_FILES_BUCKET=                    # user files — uploads, deletes, orphan GC
SECRETS_BACKEND_STUB=false           # local dev only: in-memory plaintext secrets

# === Auth / session ===
SESSION_SECRET=
SESSION_SIGNING_KEY=                 # current; falls back to SESSION_SECRET
SESSION_SIGNING_KEY_PREVIOUS=        # verify-only, enables rotation
SESSION_COOKIE_DOMAIN=               # e.g. .example.com so app.* and api.* share auth
API_PUBLIC_URL=http://localhost:8000
FRONTEND_PUBLIC_URL=http://localhost:3000
CORS_ALLOWED_ORIGINS=http://localhost:3000
MICROSOFT_OAUTH_CLIENT_ID=
MICROSOFT_OAUTH_CLIENT_SECRET=
MICROSOFT_OAUTH_TENANT=common        # or `organizations`
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=

# === Observability ===
LANGFUSE_PUBLIC_KEY=                 # optional; empty disables callbacks
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
SLACK_ALERTS_WEBHOOK=                # 80%-of-soft-budget alerts; empty disables

# === App ===
ENVIRONMENT=development              # suffixes Temporal task queues
LOG_LEVEL=INFO
API_PORT=8000
CONNECTOR_PORT=8001
```

---

## Appendix — the ten mistakes to avoid

Each of these cost real debugging time in this codebase.

1. **`uv sync` instead of `uv sync --all-packages`** — installs the root, silently skips members.
2. **Apify actor ids in slash form** — the v2 REST API 404s; the Store URL lies. Use `~`.
3. **RLS without the role split** — policies exist, `gtm_app` has BYPASSRLS, nothing fires.
4. **Adding an agent role in code but not in a migration** — CHECK violation on the first
   activity, silent because triggers are fire-and-forget.
5. **Letting LiteLLM retry inside Temporal** — double retry, burned budget. `num_retries: 0`.
6. **Trusting `non_retryable` on a plain exception** — Temporal ignores it. Catch and re-raise
   `ApplicationError(non_retryable=True)`.
7. **Skipping the `--reload-dir` flags** — the API watcher restarts on every frontend save.
8. **Passing large payloads through Temporal** — put scrape bundles in GCS, pass the object name.
9. **Workflow-level `cancel-in-progress: true` on main** — cancels in-flight deploys and leaves a
   partial revision set.
10. **Forgetting a workspace package in the service Dockerfile context** — clean local runs, a
    `ModuleNotFoundError` on first prod boot.
