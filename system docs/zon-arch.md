# ZON-ARCH — MVRX Portal: Complete Rebuild Specification

> Purpose of this document: everything needed to rebuild the MVRX Portal from an empty directory —
> the problem it solves, every tool and external service it uses, every table, route, page, background
> job, scraper, prompt, and convention, and the order to build them in. Written from a full inventory
> of the codebase on 2026-08-28 (branch `trigger-to-temporal`, 242 commits since 2026-02-24).
>
> Companion docs in the repo: `README.md`, `docs/architecture.md`, `docs/design-decisions.md`,
> `docs/local-dev.md`, `HOWTO.md`, `TRIGGER_DETAILS.md`, `NOTES.md`, `docs/plans/**`.

---

## Table of contents

1. [Problem statement](#1-problem-statement)
2. [Requirements](#2-requirements)
3. [System overview & topology](#3-system-overview--topology)
4. [Tech stack (exact)](#4-tech-stack-exact)
5. [External services & accounts you must create](#5-external-services--accounts-you-must-create)
6. [Environment variables (complete)](#6-environment-variables-complete)
7. [Repository layout & dependency rules](#7-repository-layout--dependency-rules)
8. [Local development setup](#8-local-development-setup)
9. [Data model (every table)](#9-data-model-every-table)
10. [Authentication & middleware](#10-authentication--middleware)
11. [API surface (every route)](#11-api-surface-every-route)
12. [UI pages & components](#12-ui-pages--components)
13. [Scraping & external data acquisition](#13-scraping--external-data-acquisition)
14. [Background jobs — Trigger.dev](#14-background-jobs--triggerdev)
15. [Background jobs — Temporal](#15-background-jobs--temporal)
16. [Subsystem flows, start to end](#16-subsystem-flows-start-to-end)
17. [AI layer: Claude, models, prompts, humanisation](#17-ai-layer-claude-models-prompts-humanisation)
18. [Slack integration](#18-slack-integration)
19. [Google integration](#19-google-integration)
20. [Documents: DOCX builders & Drive output](#20-documents-docx-builders--drive-output)
21. [Conventions & quality gates](#21-conventions--quality-gates)
22. [Deployment](#22-deployment)
23. [Rebuild order (milestones)](#23-rebuild-order-milestones)
24. [Known issues to fix in a rebuild](#24-known-issues-to-fix-in-a-rebuild)

---

## 1. Problem statement

**MVRX Labs** is a marketing / go-to-market agency. Clients pay them to make their executives visible
on LinkedIn and Twitter/X and to turn that visibility into leads. Done by hand, that work is:

1. Study an executive's profile and posts, write an audit, propose a content strategy.
2. Write posts in that person's voice; make sure AI-written copy doesn't sound like AI.
3. Go and engage (comment / like / repost) on posts from people the client wants to be seen by.
4. Track who engages with the client's posts, harvest them as leads, score them against the
   client's ideal customer profile (ICP), export lists.
5. Reply quickly to comments on the client's posts.
6. Report weekly on post performance.
7. Produce strategy deliverables: GTM strategy, SEO audit, GEO (AI search visibility) audit,
   growth report, sentiment analysis, outbound sequence playbook.
8. Keep track of what was said / decided / promised across dozens of client Slack channels.
9. Prepare for client meetings.

**The portal automates that agency workflow.** It is an **internal tool** — no public signup, no
billing, no tenant isolation. Users are the MVRX team (Google accounts on `@mvrxlabs.com`). Slack is a
first-class UI surface: engagement approvals, alerts, weekly reports and digests all land in Slack.

The central concept is an **Account** (a client company). Nearly everything hangs off it:

```
                        ACCOUNT (client company)
                                |
    +-----------+---------------+---------------+-------------+------------+
    |           |               |               |             |            |
contacts    tracked          ICP defs       Slack         secrets     knowledge
(people)    profiles        (who they      channels      (client      (Slack ->
            (LinkedIn/X)     target)       (per feature)  creds)      state docs)
                |                |
        scraped via Apify   alpha feeds (sages + keywords)
                |
     posts, comments, engagers, snapshots
                |
    +-----------+-----------+------------------+
    |           |           |                  |
  LEADS     weekly      engagement          comment
  (+ICP     analytics   Slack cards         alerts +
  scoring)  to Slack    (approve/comment)   AI reply suggestions
```

---

## 2. Requirements

### 2.1 Functional

| #   | Requirement                                                                                                                          | Implemented by                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| R1  | Manage client companies and the people at them (CRM-lite: notes, MRR, owner, voice guidance, action items, contract links)           | `accounts`, `contacts`, `account_actions`; `/accounts`, `/accounts/[slug]`    |
| R2  | Audit a LinkedIn / Twitter profile and produce a client-ready DOCX                                                                   | `linkedin-audit-generation`, `twitter-audit-generation`                       |
| R3  | Generate posts in a specific person's voice from source material                                                                     | `linkedin-post-generator`, `twitter-post-generator`                           |
| R4  | Repurpose content across platforms                                                                                                   | `linkedin-to-twitter`, `twitter-to-linkedin`                                  |
| R5  | Make AI copy not read as AI                                                                                                          | `src/lib/humanisation/`, `audit-post-process.ts`                              |
| R6  | Watch tracked profiles' posts and let the team engage in one tap from Slack                                                          | LinkedIn/Twitter sync → Slack cards → `engagementSlackAction`                 |
| R7  | Harvest engagers (reactions, reposts, comments, replies, retweets) into leads, CSV exports                                           | `linkedin-lead-upsert`, `twitter-lead-upsert`, `leads`, `lead_csvs`           |
| R8  | Score leads against the client's ICP (tier, conversion %, rationale)                                                                 | `icp_definitions`, `src/lib/lead-enrichment.ts`                               |
| R9  | Weekly performance reporting per managed profile → Slack                                                                             | `weekly-analytics`, `twitter-weekly-analytics`                                |
| R10 | Alert on unreplied comments with AI reply suggestions                                                                                | `sendUnrepliedCommentAlerts` in `linkedin-sync-core.ts`                       |
| R11 | Alpha feed: per-ICP feed of relevant posts (from "sages" and keyword searches) to engage with, in portal and Slack                   | `alpha_feeds`, `alpha-feed-core.ts`, `/alpha-feed`                            |
| R12 | Strategy deliverables (GTM, SEO, GEO, growth, sentiment, outbound sequence) as DOCX in Google Drive                                  | `/tools/*` + matching tasks + DOCX builders                                   |
| R13 | Turn Slack chatter into structured account knowledge (action items, decisions…) with living per-account state docs and daily digests | Knowledge Hub (`src/lib/knowledge/`, `knowledge_*` tables)                    |
| R14 | Auto-prep the team before client meetings                                                                                            | `calendar-sync`, `calendar-meeting-notifier`                                  |
| R15 | Let the team request features in English → get a GitHub PR; ingest third-party Claude Skills as tools                                | `implement-suggestion`, `ingest-skill`, `idea-generator`, `code-quality-scan` |
| R16 | Programmatic access for local agents/scripts                                                                                         | `x-api-key` middleware path, `HOWTO.md`                                       |
| R17 | Run history of every background job                                                                                                  | `tool_runs`, `/history`                                                       |
| R18 | Browse client Google Drive folders in-app                                                                                            | `/resources`, `src/lib/gdrive.ts`                                             |
| R19 | Store client credentials (Apollo keys, etc.) scoped to account/contact                                                               | `secret_types`, `secrets`, `/org/secrets`                                     |

### 2.2 Non-functional (design decisions)

- **Long jobs never run in HTTP handlers.** Vercel functions cap at 60 s; AI jobs run minutes.
  All heavy work runs in a background worker (Trigger.dev v4 today; Temporal being adopted).
- **Subsystems fail independently.** Calendar sync failing must not block audits, etc.
- **All external data is dirty.** Never assume an account/contact is complete; LinkedIn URLs go
  stale; company associations can be wrong. Handle missing fields gracefully.
- **Scraping spend is controlled** via a DB-backed Apify response cache (actor + input hash + TTL).
- **Every background failure notifies Slack** (`sendSlackNotification`).
- **Slack is a UI**, not just a notification sink.
- **One-way dependency layers** enforced by a lint script (see §7).
- **Prefixed CUID2 IDs** (`acct_…`, `run_…`) so logs are self-documenting.
- **Zod at every API boundary** (`src/lib/api-schemas/`).
- **No test suite** exists today (manual `scripts/test-*.ts` only) — a rebuild should add one.

---

## 3. System overview & topology

```
Browser (team)                          Local agents / scripts
   |  Google OAuth session (JWT)           |  x-api-key header
   v                                       v
+---------------------------------------------------------------------+
|  Next.js 16 App Router  (Vercel)                                     |
|   - ~35 UI pages (account-scoped tools + org admin + /dev/slack)     |
|   - ~97 REST API route handlers, Zod-validated                       |
|   - middleware: session OR API key; Slack routes verify signatures   |
+----------------------------+----------------------------------------+
                             |  tasks.trigger()  |  client.workflow.start()
            +----------------+------+   +---------+-------------------+
            v                       v   v                             v
+---------------------------+   +-----------------------------------------+
| Trigger.dev v4 worker     |   | Temporal worker (npm run temporal:worker)|
| (cloud, separate deploy)  |   | (local docker dev server today)          |
|  - AI tools (Claude)      |   |  - LinkedIn/Twitter profile sync         |
|  - scheduled/cron tasks   |   |  - engagement Slack actions              |
|  - knowledge pipeline     |   |  - lead upserts                          |
|  - calendar sync          |   |  - alpha feed collection (+ schedule)    |
+------+---------+---------++   +----+----------+----------+---------------+
       |         |         |         |          |          |
       v         v         v         v          v          v
  PostgreSQL   Google    Slack     Apify     Anthropic   GitHub / OpenAI
  (Drizzle)  Drive/Cal  (3 bots)  (19 actors) (Claude)   (PR bots / Whisper)
```

Key facts:

- The Next.js app and the background worker(s) are **separate deployments sharing one repo and one
  database**. Deploying one without the other causes drift.
- Both workers import the same `src/lib/` — subsystem "core" modules (`linkedin-sync-core.ts`,
  `twitter-sync-core.ts`, `alpha-feed-core.ts`) are runner-agnostic and are wrapped by a thin
  Trigger task _and_ a thin Temporal activity.
- Realtime progress: Trigger runs are subscribed to via `@trigger.dev/react-hooks` with a public
  token; Temporal runs are polled via `GET /api/temporal-runs/[workflowId]`.

---

## 4. Tech stack (exact)

| Layer                          | Choice                                                                                             | Version (package.json)                                                                 |
| ------------------------------ | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Framework                      | Next.js App Router, React, TypeScript                                                              | `next ^16.1.6`, `react ^19.2.4`, `typescript ^5.9.3`                                   |
| Styling                        | Tailwind CSS via PostCSS plugin; CSS variables for theme (`text-(--muted)`)                        | `tailwindcss ^4.2.1`, `@tailwindcss/postcss ^4.2.1`, `postcss ^8.5.6`                  |
| ORM / DB                       | Drizzle ORM + `postgres` driver; PostgreSQL 16 (Docker local, Neon prod)                           | `drizzle-orm ^0.45.1`, `drizzle-kit ^0.31.9`, `postgres ^3.4.8`                        |
| IDs                            | CUID2 with type prefixes                                                                           | `@paralleldrive/cuid2 ^3.3.0`                                                          |
| Validation                     | Zod 4                                                                                              | `zod ^4.3.6`                                                                           |
| Auth                           | NextAuth v5 (beta), Google provider, JWT sessions, domain-locked                                   | `next-auth ^5.0.0-beta.30`                                                             |
| Background jobs (current)      | Trigger.dev v4 SDK + build extensions + React hooks                                                | `@trigger.dev/sdk 4.5.9`, `@trigger.dev/build 4.5.9`, `@trigger.dev/react-hooks 4.5.9` |
| Background jobs (migrating to) | Temporal TypeScript SDK                                                                            | `@temporalio/{client,worker,workflow,activity} ^1.21.1`                                |
| AI                             | Anthropic Claude via Claude Agent SDK (agent loops with tools) and raw SDK                         | `@anthropic-ai/claude-agent-sdk ^0.2.63`, `@anthropic-ai/sdk ^0.78.0`                  |
| Transcription                  | OpenAI Whisper (`whisper-1`) via REST                                                              | (no SDK; `fetch`)                                                                      |
| Scraping                       | Apify actors via REST (`run-sync-get-dataset-items`); Playwright for screenshots; cheerio for HTML | `playwright ^1.52.0`, `cheerio ^1.2.0`, `sharp` (worker build)                         |
| SEO audit                      | `@seomator/seo-audit` CLI (installed in the worker image)                                          | via Trigger `additionalPackages`                                                       |
| Documents                      | `docx` for reports; Google Docs for post drafts                                                    | `docx ^9.6.0`, `image-size ^2.0.2`                                                     |
| Google APIs                    | Manual service-account JWT + REST (`googleapis` present but REST used)                             | `googleapis ^171.4.0`                                                                  |
| Charts                         | Recharts                                                                                           | `recharts ^3.8.0`                                                                      |
| Env loading (workers/scripts)  | dotenv                                                                                             | `dotenv ^17.3.1`                                                                       |
| Tooling                        | ESLint (`eslint-config-next`), Prettier, `tsx`, pre-commit hooks                                   | `eslint ^9.39.3`, `prettier ^3.8.1`, `tsx ^4.21.0`                                     |
| Runtime                        | Node (current LTS; `@types/node ^25`)                                                              | —                                                                                      |

---

## 5. External services & accounts you must create

| Service                                   | What for                                                                                              | What to set up                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Google Cloud project**                  | Sign-in + Drive + Calendar                                                                            | (a) OAuth 2.0 client (web) with redirect `https://<domain>/api/auth/callback/google` and `http://localhost:3000/api/auth/callback/google`; (b) a **service account** with a JSON key, Drive API + Calendar API enabled, **domain-wide delegation** granted in Google Workspace admin for scopes `https://www.googleapis.com/auth/drive` and `https://www.googleapis.com/auth/calendar.readonly`; (c) share the "Generated Materials" and "Generation Templates" Drive folders with the service account |
| **Neon** (prod) / Docker Postgres (local) | Database                                                                                              | Postgres 16; pooled connection string                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Vercel**                                | Hosts the Next.js app                                                                                 | Import repo; set all app env vars; Google OAuth redirect must match the domain                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **Trigger.dev**                           | Background worker (cloud)                                                                             | Project (`proj_omchykblaxtcsrpezhql` today); set worker env vars **separately** in the Trigger dashboard; deploy with `npx trigger.dev@latest deploy`                                                                                                                                                                                                                                                                                                                                                  |
| **Temporal**                              | Replacement orchestrator                                                                              | Local: `temporalio/temporal` docker dev server (gRPC 7233, UI 8233). Prod: Temporal Cloud or self-hosted with mTLS (`TEMPORAL_TLS_*`)                                                                                                                                                                                                                                                                                                                                                                  |
| **Apify**                                 | All LinkedIn/Twitter/web scraping                                                                     | API token; the 19 actors in §13 (marketplace actors — pay per run)                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **Anthropic**                             | All AI generation                                                                                     | API key; Claude Agent SDK requires the Claude Code runtime available to the worker                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **OpenAI**                                | Whisper transcription of Slack voice notes                                                            | API key                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **Slack**                                 | 3 apps (see §18): main bot, analytics bot, knowledge bot; plus an incoming webhook for failure alerts | Bot tokens, signing secrets, Request URLs pointing at the deployed domain; invite bots to each target channel                                                                                                                                                                                                                                                                                                                                                                                          |
| **GitHub**                                | PR bots                                                                                               | Token with `repo` scope on `MVRX-Labs/portal`                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **Google Workspace**                      | User identity                                                                                         | All users must have `@mvrxlabs.com` accounts                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

---

## 6. Environment variables (complete)

`.env.example` is the template; `.env.local` is used by Next.js, drizzle-kit, the Temporal worker and
scripts (`src/temporal/load-env.ts` loads `.env.local` then `.env`). Trigger.dev worker env vars are
set in the Trigger dashboard, **not** read from this file.

| Variable                                                                         | Used by                                                               | Notes                                                                     |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `STORAGE_DATABASE_URL`                                                           | `src/lib/db.ts` (everything)                                          | Local: `postgres://mvrx:mvrx@localhost:5433/mvrx` (Docker maps 5433→5432) |
| `PROD_STORAGE_DATABASE_URL`                                                      | `drizzle-prod.config.ts`, `db:fix-prod-journal`                       | Neon pooled URL                                                           |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`                                       | NextAuth Google provider                                              |                                                                           |
| `AUTH_SECRET`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL`                                 | NextAuth                                                              | `NEXTAUTH_URL=http://localhost:3000` locally                              |
| `GOOGLE_SERVICE_ACCOUNT_EMAIL`, `GOOGLE_PRIVATE_KEY`                             | `src/lib/google-auth.ts` (Drive, Docs, Sheets, Calendar)              | Private key with literal `\n` sequences                                   |
| `GOOGLE_DRIVE_GENERATED_MATERIALS_FOLDER_ID`                                     | `gdrive.ts` root for account folders (prod)                           | Default in example: `1DXTesLdv0LRO_CCmjg5qFBEQdl_zke9F`                   |
| `DEV_GOOGLE_DRIVE_GENERATED_MATERIALS_FOLDER_ID`                                 | same, when `NODE_ENV=development`                                     |                                                                           |
| `GOOGLE_DRIVE_GENERATION_TEMPLATES_FOLDER_ID`                                    | templates folder                                                      | Default: `19Gv1fiPlWfv7DJFfvB6YAGgRxgH1g9hn`                              |
| `SLACK_WEBHOOK_URL`                                                              | failure / suggestion / idea notifications                             | Incoming webhook (Slack app 1)                                            |
| `SLACKBOT_TOKEN`                                                                 | engagement cards, DMs, user lookup, file uploads                      | App 1 bot token `xoxb-…`                                                  |
| `SLACK_SIGNING_SECRET`                                                           | verifies engagement button clicks (LinkedIn **and** Twitter routes)   | App 1                                                                     |
| `ANALYTICS_SLACKBOT_TOKEN`                                                       | weekly analytics, comment alerts, post tracking, **alpha feed cards** | App 2 ("MVRX Portal Alerts" / Performance-Tracker)                        |
| `KNOWLEDGE_SLACKBOT_TOKEN`                                                       | Knowledge Hub read (`conversations.*`), digests, `chat.update`        | App 3                                                                     |
| `KNOWLEDGE_SLACK_SIGNING_SECRET`                                                 | verifies ✅ reaction events                                           | App 3; route fails closed (503) if unset                                  |
| `KNOWLEDGE_TEST_CHANNEL`                                                         | `scripts/test-knowledge-ingest.ts`                                    |                                                                           |
| `SLACK_DEV_MODE`                                                                 | `1` = divert all outgoing Slack to `slack_outbox` + `/dev/slack`      | Never active when `NODE_ENV=production`                                   |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE`                  | Temporal client + worker                                              | Defaults `localhost:7233`, `default`, `portal-main`                       |
| `TEMPORAL_TLS_CA`, `TEMPORAL_TLS_CERT`, `TEMPORAL_TLS_KEY`                       | Temporal Cloud/mTLS (future)                                          | Empty locally                                                             |
| `ANTHROPIC_API_KEY`                                                              | Claude Agent SDK + raw SDK                                            |                                                                           |
| `OPENAI_API_KEY`                                                                 | `src/lib/knowledge/transcribe.ts` only                                |                                                                           |
| `APIFY_API_TOKEN`                                                                | `src/lib/apify/client.ts`                                             | Query-string token on every call                                          |
| `APIFY_USER_ID`, `NGROK_BASE_URL`                                                | declared, **unused**                                                  | dead                                                                      |
| `TRIGGER_SECRET_KEY`, `TRIGGER_PROD_SECRET_KEY`                                  | Trigger.dev SDK (`tr_dev_…` locally)                                  | needed for `tasks.trigger()` from API routes                              |
| `AGENT_API_KEY`, `AGENT_USER_ID`, `AGENT_USER_NAME`, `AGENT_USER_EMAIL`          | middleware API-key path                                               | agent user resolved from env only                                         |
| `GITHUB_TOKEN`, `GITHUB_REPO_OWNER` (`MVRX-Labs`), `GITHUB_REPO_NAME` (`portal`) | PR bots                                                               |                                                                           |
| `VERCEL_GIT_COMMIT_SHA`                                                          | `/api/version` fallback build id                                      | Vercel-provided                                                           |

---

## 7. Repository layout & dependency rules

```
src/
  app/                       Next.js App Router
    page.tsx                 Login (Google sign-in) — only public page
    layout.tsx               Root: SessionProvider + AccountProvider + Sidebar + Toaster + VersionRefreshNotice
    dashboard/  accounts/  accounts/[slug]/  leads/  linkedin-leads/  twitter-leads/
    linkedin-engagement/  twitter-engagement/  analytics/  twitter-analytics/
    alpha-feed/  twitter-alpha-feed/  history/  resources/  resources/[fileId]/
    ingest-skill/  dev/slack/
    tools/{linkedin-audit,twitter-audit,linkedin-post-generator,twitter-post-generator,
           linkedin-to-twitter,twitter-to-linkedin,gtm-strategy,seo-audit,growth-report,
           geo-audit,sentiment-analysis,outbound-sequence}/
    org/{calendar,knowledge,knowledge/state,knowledge/units,users,secrets}/
    api/                     ~97 route.ts handlers (see §11)
  components/                Sidebar, AccountProvider, ToolForm, RunProgress, indicators, modals, Toaster
  lib/                       Shared: schema, db, ids, api-client, slack, gdrive, gcalendar, google-auth,
                             claude-agent, audit-utils, humanisation/, knowledge/, apify/, growth-report/,
                             geo-audit/, outbound-sequence/, *-docx builders, *-sync-core, alpha-feed-core,
                             analytics-*, lead-enrichment, linkedin-*/twitter-* helpers, api-schemas/ (24 files)
  trigger/                   Trigger.dev tasks (44 files, 52 task ids) + prompt files
  temporal/                  client.ts, worker.ts, shared.ts, load-env.ts, workflows/, activities/
  middleware.ts              Session / API-key auth
drizzle/                     37 SQL migrations + meta/ snapshots + README
scripts/                     seed, temporal-schedules, lint-architecture.sh, prettier hook, test-* scripts, archive/
docs/                        architecture, design-decisions, local-dev, tech-debt, trigger-task-inventory,
                             plans/{active,completed,paused}, slack-app-manifests/
guides/linkedin/             13 writing/style guides (reference; 50-linkedin-hooks.md transcribed into code)
apify/                       20 actor sample outputs + inputs/ (fixtures)
trigger.config.ts  drizzle.config.ts  drizzle-prod.config.ts  docker-compose.yml  .pre-commit-config.yaml
.file-length-allowlist       300-line file cap exemptions
CLAUDE.md  AGENTS.md  HOWTO.md  NOTES.md  TRIGGER_DETAILS.md  README.md
```

### Dependency layers (enforced by `scripts/lint-architecture.sh`, run in pre-commit)

```
lib/  -->  trigger/ | temporal/  -->  app/api/  -->  app/pages + components/
```

1. `src/trigger/` must **not** import from `@/app/` (tasks don't run inside Next.js).
2. `src/lib/` must **not** import from `@/trigger/` or `../trigger/`.
3. `src/components/` must **not** import from `@/trigger/` (UI talks to jobs only via API routes).
4. `src/trigger/` must **not** use `console.*` — use `logger` from `@trigger.dev/sdk`.
5. Temporal workflow files (`src/temporal/workflows/*`) run in a deterministic sandbox: only
   `@temporalio/workflow` imports and **type-only** activity imports; no DB/fetch/fs/`src/lib`.
   Activities (`src/temporal/activities/*`) run in plain Node and may import `src/lib/`.

### Standard tool request flow (memorise — every `/tools/*` follows it)

```
1. User fills form on /tools/xyz                (components/tool-form.tsx, config from TOOLS in lib/types.ts)
2. POST /api/tools/xyz                          (Zod-validated body from lib/api-schemas/tools.ts)
3. Route inserts tool_runs row (status running)  (userId from x-user-id header, accountId)
4. Route calls tasks.trigger("xyz-task", {runId, …})
5. Route mints auth.createPublicToken scoped to that run (read runs, 1–2 h)
6. Route returns { id, status, triggerRunId, publicAccessToken }
7. UI subscribes via useRealtimeRun(triggerRunId, {accessToken}); reads run.metadata.progress
8. Task: scrape/research → Claude agent → build DOCX → upload to Drive
9. Task writes tool_runs.status/output/outputUrl (or error)
10. Any failure → sendSlackNotification({tool, userName, error, runId})
```

---

## 8. Local development setup

```bash
cp .env.example .env.local          # fill values; DB URL uses port 5433
npm install
docker compose up -d                # postgres:16-alpine (5433→5432) + temporalio/temporal dev server (7233 gRPC, 8233 UI)
npm run db:push                     # apply schema (dev) — or db:generate + db:migrate for migration files
npm run db:seed                     # seeds users (scripts/seed.ts)
# terminal 1
npm run dev                         # Next.js on http://localhost:3000
# terminal 2 (Trigger.dev tasks: AI tools, knowledge hub, calendar, …)
npx trigger.dev@latest dev          # needs TRIGGER_SECRET_KEY=tr_dev_…
# terminal 3 (Temporal: sync, engagement actions, lead upserts, alpha feed)
npm run temporal:worker             # tsx watch src/temporal/worker.ts
npm run temporal:schedules          # upserts Temporal Schedules (created PAUSED); manage at http://localhost:8233
```

`npm run setup` = `docker compose up -d && sleep 2 && npm run db:push && npm run db:seed`.

Local Slack testing: set `SLACK_DEV_MODE=1` → every outgoing Slack call is written to `slack_outbox` and
rendered at `/dev/slack` with working buttons (which POST synthetic `block_actions` to the real
interactivity route; signature check is bypassed in dev mode). Set `SLACK_DEV_MODE=0` + real tokens to
post to real channels (double-check `accounts.*_slack_channel` values first).

Gotchas recorded in `NOTES.md`:

- `tsx watch` does **not** rebuild the Temporal workflow bundle on workflow-file edits — restart the worker.
- Temporal activity timeouts don't kill running JS; a too-short `startToCloseTimeout` causes a parallel
  retry that duplicates Apify spend. Size timeouts from per-item cost × item count.
- Docker Desktop can start the Temporal container without publishing ports → `docker compose up -d --force-recreate temporal`.
- LinkedIn post URLs carry per-viewer tracking params (`?utm_…&rcm=…`); canonicalise before deduping.
- Never add bare `catch {}` around `apiFetch` — errors are auto-toasted, swallowing hides empty-state bugs.

npm scripts: `dev`, `build`, `start`, `lint`, `typecheck` (`tsc --noEmit`), `format`/`format:check`,
`db:generate`, `db:migrate`, `db:push`, `db:seed`, `db:migrate-ids`, `db:fix-prod-journal`,
`db:migrate-prod`, `deploy:prod` (`db:migrate-prod && npx trigger.dev@latest deploy`), `setup`,
`temporal:worker`, `temporal:schedules`.

---

## 9. Data model (every table)

Source: `src/lib/schema.ts` (Drizzle, ~1050 lines, **37 tables**) and `src/lib/ids.ts`.
All PKs are `text` = `<prefix>_<cuid2>` generated in app code via `createObjectId(prefix)`
(`$defaultFn`). Timestamps are `timestamp` with `defaultNow()`; `updatedAt` is bumped in app code.
`ids.ts` exports `slugify`, `createObjectId`, `isObjectId`, `assertObjectId`, `prefixForTable` and
branded types (`AccountId = \`acct*${string}\``…). (`knowledge_digest_messages`uses inline`kdig*<uuid>`ids; seven legacy prefixes`engprof/engpost/engjob/engraw/mprof/mpost/msnap`remain in`ids.ts` for tables dropped in migration 0024.)

### 9.1 Core CRM

**`users`** (`user_`) — `id`, `name` NN, `email` NN **unique**, `slackUserId` (cached from `users.lookupByEmail`), `createdAt`.

**`accounts`** (`acct_`) — `id`, `name` NN, `slug` NN **unique**, `industry`, `website`, `emailDomain`
(calendar matching), `googleDriveFolderId`, `notes`, `contentVoiceGuidance` (fed to prompts), `ownerId`
FK→users, `mrr` int NN default 0, `mrrCurrency` NN default `'$'`, `nextMeetingAt`, `lastMeetingAt`,
`autoCreated` bool (created by calendar matching), `hidden` bool, `contentCalendarUrl`,
`contractLinks` jsonb `{url,label}[]`, `engagementSlackChannel`, `analyticsSlackChannel`
(comma-separated list allowed), `twitterEngagementSlackChannel`, `twitterAnalyticsSlackChannel`,
`alphaFeedSlackChannel`, `createdAt`, `updatedAt`.

**`contacts`** (`contact_`) — `id`, `name` NN, `accountId` NN FK, `accountEmail`, `personalEmail`
(both matched against calendar attendees), `contentVoiceGuidance`, `notes`, `nextMeetingAt`,
`lastMeetingAt`, `autoCreated`, `createdAt`, `updatedAt`.

**`account_actions`** (`action_`) — `id`, `accountId` NN FK, `title` NN, `description`, `status` NN
default `'pending'` (`pending|completed`; open = `!= 'completed'`), `dueDate`, `assigneeId` FK→users,
`createdAt`, `updatedAt`.

**`tool_runs`** (`run_`) — `id`, `tool` NN (task/tool id), `status` NN (`pending|running|completed|failed`),
`inputs` jsonb NN, `output` text, `outputUrl` (Drive link / PR url), `error`, `triggerRunId` (Trigger run
id or Temporal workflow id), `userId` FK→users nullable, `accountId` FK nullable, `createdAt`, `updatedAt`.

### 9.2 Leads / ICP / alpha feeds

**`leads`** (`lead_`) — `id`, `accountId` NN FK, `contactId` FK, `leadCsvId` (soft ref), `linkedinUrl`,
`linkedinUrnUrl` (`/in/ACo…` form), `linkedinSlug`, `twitterUrl`, `twitterHandle`, `firstName` NN,
`lastName`, `headline`, `company`, `title`, `division`, `region`, `email`, `phone`, `profileImageUrl`,
`engagementTypes` jsonb string[] (`reaction|repost|comment|like|retweet|quote_tweet|reply`),
`engagementPosts` jsonb string[] (post URLs), `tier` int (1–3), `conversionPct` int (0–100),
`rationale` (AI), `enrichedAt`, `firstSeenAt` NN, `lastSeenAt` NN (post dates, not scrape dates),
`createdAt`, `updatedAt`. **Partial unique indexes**: `(account_id, linkedin_url) WHERE linkedin_url IS NOT NULL`,
`(account_id, twitter_url) WHERE twitter_url IS NOT NULL`.

**`lead_csvs`** (`lcsv_`) — `id`, `accountId` NN FK, `contactId` FK, `profileId` FK→linkedin_profiles,
`scrapeWindow` NN (`early|late`), `description` NN, `filename` NN, `csvContent` NN (inline CSV),
`leadCount` int NN, `postUrls` jsonb string[], `createdAt`.

**`icp_definitions`** (`icp_`) — `id`, `accountId` NN FK, `name` NN, `description` NN,
`targetTitles`/`targetIndustries`/`targetCompanySizes`/`targetSignals` jsonb string[], `active` bool
default true, `createdAt`, `updatedAt`.

**`alpha_feeds`** (`afeed_`) — `id`, `icpDefinitionId` NN FK **unique** (1:1 with ICP), `accountId` NN FK,
`sages` jsonb `AlphaFeedSage[]`, `keywords` jsonb `AlphaFeedKeyword[]`, `dailyEntries` jsonb
`Record<YYYY-MM-DD, AlphaFeedEntry[]>`, `createdAt`, `updatedAt`.

```ts
AlphaFeedSage    { linkedinUrl; displayName; headline?; rationale?; active }
AlphaFeedKeyword { query; rationale?; active }
AlphaFeedEntry   { postUrl; authorName; authorLinkedinUrl?; authorHeadline?; content; likesCount;
                   commentsCount; repostsCount; postedAt?; engagementScore; sourceType:"sage"|"keyword";
                   sourceLabel; slackTs? /* set once posted to accounts.alpha_feed_slack_channel */ }
```

**`twitter_alpha_feeds`** (`tafeed_`) — same columns; `TwitterAlphaFeedSage {twitterUrl; twitterHandle?;
displayName; bio?; rationale?; active}`, `TwitterAlphaFeedEntry {tweetUrl; authorName; authorTwitterUrl?;
authorTwitterHandle?; authorBio?; content; likesCount; retweetsCount; repliesCount; viewsCount;
bookmarksCount; postedAt?; engagementScore; sourceType; sourceLabel}` (no `slackTs`).

### 9.3 LinkedIn

**`linkedin_profiles`** (`lprof_`) — unified registry. `id`, `accountId` NN FK, `linkedinUrl` NN,
`linkedinSlug`, `displayName` NN default `''`, `analyticsEnabled`, `outboundEnabled`, `inboundEnabled`
(non-exclusive feature flags), `engagementPersona` NN default `''` (persona for AI comments),
`sourceType` (`company|personal`), `contactId` FK, `active` default true, `lastSyncedAt`, `createdAt`,
`updatedAt`. Unique `(account_id, linkedin_url)`.

**`linkedin_posts`** (`lpost_`) — `id`, `profileId` NN FK, `accountId` NN FK, `apifyPostId` NN,
`content` NN default `''`, `postUrl` NN default `''`, `likesCount`, `commentsCount`, `repostsCount`
(ints default 0), `postedAt`, `discoveredAt` NN, `engagementStatus` (null for non-outbound;
`pending → sending → sent_to_slack → awaiting_action → engaged`, terminals `skip`, `failed`;
`processing` used as claim state), `slackMessageTs`, `agentComment`, `engagedAt`,
`earlyEngagersScrapedAt`, `lateEngagersScrapedAt`, `category`
(`thought_leadership|domain_knowledge|third_party_validation|case_study|storytelling|other`), `createdAt`.
Unique `(profile_id, apify_post_id)`.

**`linkedin_post_snapshots`** (`lsnap_`) — `id`, `postId` FK, `profileId` FK, `accountId` FK,
`likesCount`, `commentsCount`, `repostsCount`, `capturedAt`. (time series)

**`linkedin_sync_runs`** (`lsync_`) — `id`, `profileId` FK, `accountId` FK, `status` NN default
`'queued'` (`queued|running|completed|failed`), `postsFound`, `postsNew`, `errorMessage`, `apifyRunId`
(always `""` today), `triggerRunId`, `createdAt`, `completedAt`.

**`linkedin_post_comments`** (`lcomm_`) — `id`, `postId` FK, `profileId` FK, `accountId` FK,
`commentUrn` NN, `authorName` NN default `''`, `authorLinkedinUrl`, `authorHeadline`, `commentText` NN
default `''`, `commentUrl`, `commentedAt`, `parentCommentId` (soft self-ref), `isReply` bool,
`repliedToByOwner` bool, `notifiedAt`, `createdAt`. Unique `(post_id, comment_urn)`.

**`linkedin_post_engagements`** (`leng_`) — `id`, `postId` FK, `profileId` FK, `accountId` FK,
`authorName` NN default `''`, `authorLinkedinUrl`, `authorLinkedinSlug`, `authorHeadline`, `authorCompany`,
`authorProfileImage`, `engagementType` NN (`reaction|repost`), `engagedAt` (= post date),
`scrapeWindow` (`early|late`), `capturedAt`. Unique `lpe_post_author_type_unique (post_id, author_linkedin_url, engagement_type)`.

**`analytics_reports`** (`arpt_`) — `id`, `accountId` FK, `profileId` (soft ref to linkedin/twitter
profile), `reportType` NN default `'weekly'`, `periodStart` NN, `periodEnd` NN, `reportData` jsonb NN,
`pdfUrl`, `slackTs`, `createdAt`. Unique `(account_id, profile_id, report_type, period_start)`.

### 9.4 Twitter/X (mirrors LinkedIn)

**`twitter_profiles`** (`tprof_`) — as `linkedin_profiles` with `twitterUrl` NN, `twitterHandle` (no `@`). Unique `(account_id, twitter_url)`.

**`twitter_posts`** (`tpost_`) — `externalTweetId` NN, `content`, `tweetUrl`, `tweetType` NN default
`'tweet'` (`tweet|retweet|quote_tweet|reply`), `likesCount`, `retweetsCount`, `quotesCount`,
`repliesCount`, `bookmarksCount`, `viewsCount`, `postedAt`, `discoveredAt`, `engagementStatus`,
`slackMessageTs`, `agentComment`, `engagedAt`, `earlyEngagersScrapedAt`, `lateEngagersScrapedAt`,
`category`, `createdAt`. Unique `(profile_id, external_tweet_id)`.

**`twitter_post_snapshots`** (`tsnap_`) — six metric columns + `capturedAt`.
**`twitter_sync_runs`** (`tsync_`) — identical to `linkedin_sync_runs`.
**`twitter_post_replies`** (`trepl_`) — `tweetId` NN, `authorName`, `authorHandle`, `authorBio`,
`authorTwitterUrl`, `replyText`, `replyUrl`, `repliedAt`, `parentReplyId`, `isReply`, `repliedToByOwner`,
`notifiedAt`. Unique `(post_id, tweet_id)`.
**`twitter_post_engagements`** (`teng_`) — `authorName`, `authorHandle`, `authorTwitterUrl`, `authorBio`,
`authorCompany`, `authorProfileImage`, `engagementType` NN (`like|retweet|quote_tweet`; only `retweet`
is scraped — likes are private since 2024), `engagedAt`, `scrapeWindow`, `capturedAt`.
Unique `tpe_post_author_type_unique (post_id, author_twitter_url, engagement_type)`.

### 9.5 Calendar

**`calendar_sync_state`** (`calsync_`) — `userId` FK, `calendarId` NN (= user email), `syncToken`,
`lastSyncedAt`, `lastSyncError`. Unique `(user_id, calendar_id)`.
**`calendar_events`** (`calevent_`) — `googleEventId` NN, `calendarId` NN, `summary`, `description`,
`startTime` NN, `endTime` NN, `location`, `organizerEmail`, `status` NN default `'confirmed'`
(`confirmed|tentative|cancelled`), `attendees` jsonb NN `{email; displayName?; responseStatus?; self?; organizer?}[]`,
`isRecurring`, `recurringEventId`, `htmlLink`, `notifiedAt`. Unique `(calendar_id, google_event_id)`.
**`calendar_event_accounts`** (`calevtacct_`) — `eventId` FK, `accountId` FK, `matchConfidence` NN default
`'high'` (`high|low|auto_created`), `matchedVia` (`contact_email|contact_domain|email_domain|auto_created`). Unique `(event_id, account_id)`.
**`calendar_event_contacts`** (`calevtcont_`) — `eventId` FK, `contactId` FK, `attendeeEmail` NN,
`matchConfidence`, `matchedVia` (`account_email|personal_email|auto_created`). Unique `(event_id, contact_id)`.

### 9.6 Secrets

**`secret_types`** (`sectype_`) — `name` NN unique (user-defined categories, e.g. "Apollo API Key").
**`secrets`** (`secret_`) — `accountId` NN FK, `contactId` FK, `typeId` NN FK, `name` NN, `value` NN
(**plaintext** today), `description`, `createdAt`, `updatedAt`.

### 9.7 Knowledge Hub

**`knowledge_channels`** (`kchan_`) — `accountId` FK nullable (general/product channels),
`slackChannelId` NN unique, `slackChannelName` NN, `channelType` NN default `'shared'`
(`shared|internal`, legacy), `channelCategory` NN default `'client_shared'`
(`client_shared|client_internal|general|product|ops`), `workspaceId`, `active`.
**`knowledge_sync_state`** (`ksync_`) — `channelId` NN FK unique, `lastMessageTs` (cursor),
`lastSyncedAt`, `lastSyncError`, `messagesIngested` int.
**`knowledge_events`** (`kevt_`) — append-only raw log. `accountId` FK nullable, `channelId` NN FK,
`source` NN default `'slack'` (`slack|granola|drive|crm`), `sourceRef` NN (Slack ts), `threadRef`,
`authorSlackId`, `authorName`, `authorSide` (`mvrx|client`), `visibility` NN (`shared|internal`),
`contentType` NN default `'text'` (`text|voice_note|image|video|pdf|gdoc|gsheet|gpres`), `rawContent` NN,
`mediaUrl`, `resolvedContent` (transcript / fetched doc text), `links` jsonb, `driveLinks` jsonb,
`metadata` jsonb, `messageAt` NN, `processedAt` (null = pending normalisation).
Unique `(channel_id, source_ref)`; indexes `(account_id, message_at)`, `(channel_id, created_at)`.
**`knowledge_units`** (`kunit_`) — `accountId` FK nullable, `channelId` FK nullable, `unitType` NN
(`action_item|decision|context_update|content_draft|request|feedback|deliverable|blocker|product_bug|product_feature`),
`content` NN, `author`, `assignee`, `assigneeContactId` FK, `requestedBy`, `requestedByUserId` FK,
`status` NN default `'open'` (`open|done|superseded`; API-level `dismissed` = `done` + `metadata.dismissed=true`),
`dueDate`, `visibility`, `confidence` int default 80, `sourceEventIds` jsonb NN, `supersededBy`,
`metadata` jsonb, `extractedAt`, `createdAt`. Index `(account_id, unit_type)`.
**`knowledge_state`** (`kstate_`) — `accountId` NN FK, `stateType` NN (`brief|open_items|activity_log`),
`content` NN (markdown), `version` int, `updatedAt`, `createdAt`. Unique `(account_id, state_type)`.
**`knowledge_digest_messages`** (`kdig_`) — `unitId` NN FK, `recipientSlackId` NN, `channelId` NN
(Slack DM channel), `threadTs` NN, `messageTs` NN, `markedDone` bool NN. Unique `(unit_id, recipient_slack_id)`;
index `(channel_id, message_ts)`.

### 9.8 Caching & dev

**`apify_cache`** (`acache_`) — `cacheKey` NN unique (sha256 of actor + sorted input), `cacheKeyHuman` NN,
`actorId` NN, `input` jsonb NN, `response` jsonb NN, `createdAt`, `expiresAt` NN. Index on `expires_at`.
**`slack_outbox`** (`sobx_`) — `channel` NN, `ts` NN unique (fake Slack ts), `text`, `blocks` jsonb,
`source` NN (`chat.postMessage|chat.update|webhook|<method>`), `createdAt`, `updatedAt`.

### 9.9 Migrations

37 files `drizzle/0000_…` → `0036_burly_living_tribunal.sql` (journal `drizzle/meta/_journal.json`).
`drizzle.config.ts` uses `STORAGE_DATABASE_URL`; `drizzle-prod.config.ts` uses `PROD_STORAGE_DATABASE_URL`
(both load `.env.local`). Prod was originally built with `db:push`, so `scripts/fix-prod-migration-journal.ts`
backfills `__drizzle_migrations` before `db:migrate-prod` works. Notable history: 0014/0016 created the
legacy `engagement_*`/`managed_*` tables, dropped in 0024 after the unified `linkedin_profiles` registry (0021);
0028 apify cache; 0029–0030 ICP + alpha feeds; 0034–0035 Twitter; 0036 `slack_outbox` + `alpha_feed_slack_channel`.

---

## 10. Authentication & middleware

**NextAuth v5** (`src/lib/auth-config.ts`, handlers re-exported at `src/app/api/auth/[...nextauth]/route.ts`):

- Provider: Google only. `signIn` callback returns `false` unless `profile.email.endsWith("@mvrxlabs.com")`.
- Session strategy `jwt`; sign-in page `/`.
- `jwt` callback syncs the user to the `users` table (lookup by email, create with `createObjectId("user")`
  if missing) on sign-in, when `token.userId` is missing, or when `userVerifiedAt` is older than 1 hour.
- `session` callback copies `token.userId` → `session.user.id`.

**Middleware** (`src/middleware.ts`, wrapped in `auth(...)`):

1. `/` and `/api/auth/*` → pass.
2. `/api/knowledge/slack-events` → pass (verifies its own Slack signature).
3. If `x-api-key` header is present on `/api/*`: must equal `AGENT_API_KEY` (401 otherwise);
   `AGENT_USER_ID` required (500 otherwise); injects `x-user-id`/`x-user-name`/`x-user-email` from env
   (agent identity comes from env, not DB). Full session bypass.
4. No session → 401 JSON for `/api/*`, redirect to `/` for pages.
5. Prefetch requests get `x-user-id` stripped; otherwise inject `x-user-id`, `x-user-name`, `x-user-email`.

`matcher` (allow-list — routes outside it get **no** auth): pages `/dashboard`, `/tools`, `/history`,
`/org`, `/resources`, `/linkedin-engagement`, `/twitter-engagement`, `/leads`, `/linkedin-leads`,
`/twitter-leads`, `/analytics`, `/alpha-feed`, `/twitter-alpha-feed`, `/twitter-analytics`; APIs
`/api/tools`, `/api/history`, `/api/org`, `/api/resources`, `/api/runs`, `/api/accounts`, `/api/contacts`,
`/api/knowledge`. Slack interactivity routes use HMAC signature auth instead (see §18). See §24 for the
routes that are accidentally unprotected.

---

## 11. API surface (every route)

Conventions: bodies parsed with `parseBody(request, schema)` / `parseBodyOptional` from
`src/lib/api-schemas/common.ts` (400 `{error:"Validation error", details}`); identity from `x-user-*`
headers; responses typed by Zod schemas in `src/lib/api-schemas/*` (24 files: accounts, actions,
alpha-feed, analytics, calendar, common, contacts, dashboard, history, icp-definitions, knowledge, leads,
linkedin-engagement, linkedin-profiles, post-categories, resources, runs, skills, tools, twitter-\*, users, secrets).
Job-start responses: Trigger `{triggerRunId, publicAccessToken}`; Temporal `{workflowId}`; tools
`{id, status, triggerRunId?, publicAccessToken?, message?}`.

### 11.1 Accounts / contacts / actions / ICP

| Route                                               | Methods                                  | Purpose                                                                                                                                                                                                        |
| --------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/api/accounts`                                     | GET (`?q=`, `?includeHidden=true`), POST | List/search (with ownerName, contactCount, pendingActionCount, company linkedin/twitter URLs); create (`{name, industry?, website?, linkedinUrl?, twitterUrl?}`) → unique slug, Drive folder, company profiles |
| `/api/accounts/[id]`                                | GET, PUT                                 | id or slug; GET ensures Drive folder; PUT fields incl. all 5 Slack channel columns, contractLinks, voice guidance, linkedinUrl/twitterUrl (→ profile registry)                                                 |
| `/api/accounts/[id]/contacts`                       | GET                                      | contacts + their profile URLs                                                                                                                                                                                  |
| `/api/accounts/[id]/dashboard`                      | GET                                      | per-account KPIs, posts/engagement/leads per week, profile comparison (`src/lib/dashboard-data.ts`)                                                                                                            |
| `/api/accounts/[id]/actions`, `/actions/[actionId]` | GET, POST / PUT, DELETE                  | action items                                                                                                                                                                                                   |
| `/api/contacts`, `/api/contacts/[id]`               | GET, POST / PUT, DELETE                  | contacts (+ linkedin/twitter profile sync)                                                                                                                                                                     |
| `/api/accounts/[id]/icp-definitions`, `/[icpId]`    | GET, POST / PATCH                        | ICPs; PATCH `{active}`                                                                                                                                                                                         |

### 11.2 LinkedIn engagement / profiles / analytics

| Route                                                               | Methods                          | Purpose / job                                                                   |
| ------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------- |
| `/api/accounts/[id]/engagement/config`                              | GET, PATCH                       | `engagementSlackChannel`                                                        |
| `/api/accounts/[id]/engagement/profiles`, `/[profileId]`, `/upload` | GET, POST / PATCH, DELETE / POST | outbound profiles (`{linkedin_urls[], engagement_persona?}`), CSV upload        |
| `/api/accounts/[id]/engagement/posts`, `/jobs`                      | GET                              | scraped posts; `linkedin_sync_runs`                                             |
| `/api/accounts/[id]/engagement/scrape`                              | POST                             | **Temporal** `linkedinSyncProfile` per outbound profile → `{triggered, runs[]}` |
| `/api/accounts/[id]/linkedin-profiles`, `/[profileId]`              | GET / PATCH                      | registry; toggle analytics/outbound/inbound                                     |
| `/api/accounts/[id]/analytics/config`, `/profiles`, `/`             | GET, PATCH / GET, POST / GET     | analytics channel; managed profiles; weekly report data                         |
| `/api/accounts/[id]/analytics/scrape`                               | POST `{profile_id?}`             | **Trigger** `weekly-analytics`                                                  |
| `/api/linkedin-posts/[postId]`                                      | PATCH `{category}`               | set category                                                                    |
| `/api/categorise-posts`                                             | POST                             | **Trigger** `post-categoriser`                                                  |

### 11.3 Twitter mirrors

`/api/accounts/[id]/twitter-engagement/{config,profiles,profiles/[profileId],posts,jobs,scrape}`
(scrape → **Temporal** `twitterSyncProfile`), `/api/accounts/[id]/twitter-profiles[/[profileId]]`,
`/api/accounts/[id]/twitter-sync` (POST → **Trigger** `twitter-sync-profile` per analytics profile).

### 11.4 Alpha feed

| Route                                                             | Methods                                                                                              | Purpose / job                                                              |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------ |
| `/api/accounts/[id]/alpha-feed/[icpId]`                           | GET                                                                                                  | `{alphaFeed                                                                | null}` |
| `…/alpha-feed/[icpId]/sages`                                      | POST `{linkedinUrl, displayName?, headline?}`, PATCH `{linkedinUrl, active}`, DELETE `{linkedinUrl}` | manage sages                                                               |
| `…/alpha-feed/[icpId]/keywords`                                   | POST `{query}`, PATCH, DELETE                                                                        | manage keywords                                                            |
| `…/alpha-feed/[icpId]/generate`                                   | POST                                                                                                 | **Trigger** `alpha-feed-generate-spec` (LinkedIn + Twitter specs)          |
| `…/alpha-feed/[icpId]/collect`                                    | POST                                                                                                 | **Temporal** `alphaFeedCollect` → `{workflowId}`                           |
| `…/twitter-alpha-feed/[icpId]`, `/sages`, `/keywords`, `/collect` | GET / POST,PATCH,DELETE / … / POST                                                                   | Twitter variant; collect → **Trigger** `twitter-alpha-feed-collect-worker` |

### 11.5 Leads

`/api/accounts/[id]/leads` GET (`?page,limit≤100,q,contactId,source=linkedin|twitter`) → `{leads, pagination}`;
`/leads/export` GET → CSV; `/leads/csvs` GET; `/leads/csvs/[csvId]/download` GET;
`/leads/scrape` POST `{contactId?, daysBack?}` → **Trigger** batch `linkedin-sync-profile` then `linkedin-lead-upsert`.

### 11.6 Tools (all POST; insert `tool_runs` then trigger)

| Route                                | Body (`api-schemas/tools.ts`)                                                                                                                     | Trigger task                    |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| `/api/tools/linkedin-audit`          | `{contactId, accountId, model?}`                                                                                                                  | `linkedin-audit-generation`     |
| `/api/tools/twitter-audit`           | `{contactId, accountId, model?}`                                                                                                                  | `twitter-audit-generation`      |
| `/api/tools/linkedin-post-generator` | `{contactId, useLinkedinProfile?, sourceMaterial, voiceContext?, promptStyle?(default\|narrative\|analytical), customPrompt?, model?, accountId}` | `linkedin-post-generator`       |
| `/api/tools/twitter-post-generator`  | `{contactId, sourceMaterial, voiceContext?, promptStyle?(default\|thread\|analytical), customPrompt?, model?, accountId}`                         | `twitter-post-generator`        |
| `/api/tools/linkedin-to-twitter`     | `{postContent, promptStyle?(default\|human\|viral), customPrompt?, outputFormat?(thread\|single-tweet), callToAction?, model?, accountId}`        | `linkedin-to-twitter`           |
| `/api/tools/twitter-to-linkedin`     | `{postContent, outputFormat?(full\|short), model?, accountId}`                                                                                    | `twitter-to-linkedin`           |
| `/api/tools/gtm-strategy`            | `{accountId, industry, targetAudience, productDescription, model?}`                                                                               | `gtm-strategy-generation`       |
| `/api/tools/sentiment-analysis`      | `{productName, accountId, sources?, urls?, keywords?, model?}`                                                                                    | `sentiment-analysis-generation` |
| `/api/tools/seo-audit`               | `{websiteUrl, crawlMode(single\|crawl-20\|crawl-50\|crawl-100), categories?, includeCwv?, accountId, model?}`                                     | `seo-audit-generation`          |
| `/api/tools/geo-audit`               | `{accountId, websiteUrl, brandName?, model?}`                                                                                                     | `geo-audit`                     |
| `/api/tools/growth-report`           | `{accountId, model?}`                                                                                                                             | `growth-report-generation`      |
| `/api/tools/outbound-sequence`       | `{accountId, senderContactId?, targetIcp, valueProp, toneNotes?, audienceSegments?, leadListDescription?, senderAccountCount?, model?}`           | `outbound-sequence-generation`  |
| `/api/tools/suggestion`              | `{toolId, description}`                                                                                                                           | `implement-suggestion`          |
| `/api/tools/ingest-skill`            | `{skillUrl? \| skillMd?, slug?, notes?}` (`api-schemas/skills.ts`)                                                                                | `ingest-skill`                  |

`model` ∈ `haiku|sonnet|opus` (`MODEL_IDS`). Generic helper `createToolHandler(toolId, schema?)` in
`src/lib/tool-handler.ts` (inserts `pending` row inside `withTimeoutGuard`, returns `{id,status,message}`).

### 11.7 Org / runs / knowledge / misc

| Route                                                                | Methods                                                | Purpose                                                                                                  |
| -------------------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `/api/org/users`                                                     | GET, POST `{name,email}`, PUT `{id,…}`, DELETE `?id=`  | users                                                                                                    |
| `/api/org/secret-types`, `/api/org/secrets`, `/api/org/secrets/[id]` | GET, POST / GET, POST / PUT, DELETE                    | vault                                                                                                    |
| `/api/org/calendar-events`                                           | GET `?view=events\|stats\|sync-state&limit`            | calendar data                                                                                            |
| `/api/org/calendar-sync`                                             | POST                                                   | **Trigger** `calendar-sync`                                                                              |
| `/api/history`                                                       | GET `?page,limit,tool,user,status,account`             | `tool_runs` history                                                                                      |
| `/api/runs/[id]`                                                     | GET                                                    | run + fresh `publicAccessToken` while running (1 h); `maxDuration=300`                                   |
| `/api/temporal-runs/[workflowId]`                                    | GET                                                    | `{workflowId, status}` via `describe()`                                                                  |
| `/api/dashboard`                                                     | GET                                                    | org dashboard (`src/lib/org-dashboard-data.ts`, includes MRR)                                            |
| `/api/resources`, `/api/resources/[fileId]`                          | GET                                                    | Drive listing (`?folderId` or `?accountId`); file meta/preview or `?action=export` text                  |
| `/api/knowledge/channels`, `/[id]`, `/[id]/sync`                     | GET, POST / PATCH / POST                               | register (calls `conversations.info`), toggle, ingest one (**Trigger** `knowledge-slack-ingest-channel`) |
| `/api/knowledge/ingest`                                              | POST `{channelDbId?}`                                  | one channel or all (**Trigger** `…-scheduled`)                                                           |
| `/api/knowledge/units`, `/[id]`                                      | GET (filters) / PATCH `{status?, content?, assignee?}` | units                                                                                                    |
| `/api/knowledge/digest`                                              | POST / PATCH `{updates[]}`                             | **Trigger** `knowledge-digest-on-demand`; bulk status                                                    |
| `/api/knowledge/state`, `/state/synthesise`, `/stats`                | GET `?accountId` / POST `{accountId?}` / GET           | state docs (**Trigger** `knowledge-state-synthesis-on-demand`)                                           |
| `/api/accounts/[id]/knowledge-channels`, `/knowledge-state`          | GET                                                    | per-account views                                                                                        |
| `/api/auth/[...nextauth]`                                            | GET, POST                                              | NextAuth                                                                                                 |
| `/api/version`                                                       | GET                                                    | `{buildId}` (`.next/BUILD_ID` or `VERCEL_GIT_COMMIT_SHA` or `dev`), no-store                             |
| `/api/debug-auth`                                                    | GET                                                    | dumps cookies/JWT/session (**should be removed**)                                                        |
| `/api/dev/slack/{outbox,clear,seed}`                                 | GET / POST / POST                                      | dev simulator; 403 unless `SLACK_DEV_MODE=1`                                                             |
| `/api/linkedin-engagement-slack`                                     | POST (form `payload=`)                                 | Slack interactivity → **Temporal** `engagementSlackAction`                                               |
| `/api/twitter-engagement-slack`                                      | POST                                                   | → **Temporal** `twitterEngagementSlackAction`                                                            |
| `/api/engagement-slack`                                              | POST                                                   | legacy alias of the LinkedIn handler                                                                     |
| `/api/knowledge/slack-events`                                        | POST (Events API)                                      | ✅ reaction added/removed → mark units done/open                                                         |
| `/api/slack/analytics-events`                                        | POST (Events API `app_mention`)                        | extract post URLs, ack in thread, **Trigger** `track-post` ×5 (delays 5m/30m/1h/2h/4h)                   |

---

## 12. UI pages & components

`src/app/layout.tsx` (`"use client"`): `SessionProvider`; on `/` renders bare `<main>`; otherwise
`<Suspense><AccountProvider><Sidebar/><main>{AccountWarningBanner}{children}</main></AccountProvider></Suspense>`;
always mounts `<Toaster/>` and `<VersionRefreshNotice/>`.

### Pages

| Route                                                            | Purpose                                                                                                                                                          | Calls                                                                 |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `/`                                                              | Google sign-in ("Only @mvrxlabs.com accounts")                                                                                                                   | —                                                                     |
| `/dashboard`                                                     | `AccountDashboard` if an account is selected, else `OrgDashboard` (Recharts)                                                                                     | `/api/accounts/[id]/dashboard`, `/api/dashboard`                      |
| `/accounts`, `/accounts/[slug]`                                  | account table; account overview/editor (sections: details, contacts, ICP + alpha feed specs, integrations incl. 3 Slack channel fields, actions, notes) **BETA** | `/api/accounts*`                                                      |
| `/analytics`, `/twitter-analytics`                               | post analytics, channel config, run weekly scrape                                                                                                                | `/api/accounts/[id]/analytics*`, `/twitter-profiles`, `/twitter-sync` |
| `/linkedin-engagement`, `/twitter-engagement`                    | engagement bot console: Slack channel, tracked profiles + persona, jobs, posts with status, "Scrape now"                                                         | `/api/accounts/[id]/engagement*` / `twitter-engagement*`              |
| `/alpha-feed`, `/twitter-alpha-feed`                             | per-ICP feed: sages/keywords editor, Generate Spec (Trigger), Collect Now (Temporal / Trigger), day tabs of posts                                                | `/api/accounts/[id]/alpha-feed/*`                                     |
| `/leads`, `/linkedin-leads`, `/twitter-leads`                    | paginated leads, search, CSV export, CSV history, scrape trigger                                                                                                 | `/api/accounts/[id]/leads*`                                           |
| `/history`                                                       | every `tool_runs` row with filters                                                                                                                               | `/api/history`                                                        |
| `/resources`, `/resources/[fileId]`                              | Drive browser + sandboxed preview/export                                                                                                                         | `/api/resources*`                                                     |
| `/org/users`, `/org/secrets`, `/org/calendar`                    | admin                                                                                                                                                            | `/api/org/*`                                                          |
| `/org/knowledge`, `/org/knowledge/state`, `/org/knowledge/units` | Knowledge Hub channels/stats, state docs + synthesise, units table                                                                                               | `/api/knowledge/*`                                                    |
| `/ingest-skill`, `/tools/<12 tools>`                             | 9-line wrappers: `TOOLS.find(id)` → `<ToolForm/>`                                                                                                                | via ToolForm                                                          |
| `/dev/slack`                                                     | dev Slack simulator (renders `slack_outbox` as Block Kit, buttons hit the real interactivity route)                                                              | `/api/dev/slack/*`                                                    |

**Tool registry**: `TOOLS` in `src/lib/types.ts` — one `ToolConfig` per tool (`id`, name, description,
fields, prompt presets, beta flag). **Adding a tool UI = adding a config entry, not a page.**

### Components (`src/components/`)

`sidebar.tsx` (nav: General / LinkedIn 💼 / Twitter-X 𝕏 (BETA) / Other tools / Organization; items
disabled until an account is selected; `__SLUG__` placeholder; BETA/DEV badges), `account-provider.tsx`
(`useAccount()` → `{account, contacts, loading, setAccount, refreshContacts}`; resolves from `?account=`
or `/accounts/[slug]`), `account-selector.tsx` (debounced search), `account-warning-banner.tsx`,
`tool-form.tsx` (generic form renderer + `PromptSelectField` presets + submit + `<RunProgress/>` +
polling `/api/runs/[id]`), `run-progress.tsx` (`useRealtimeRun`, reads
`metadata.progress = {step, stepNumber, totalSteps, percentage}`), `trigger-run-indicator.tsx`,
`temporal-run-indicator.tsx` (polls `/api/temporal-runs/[id]` every 4 s), `contact-picker.tsx`,
`create-account-modal.tsx`, `create-contact-modal.tsx`, `secret-modal.tsx`, `notes-field.tsx`,
`resource-viewer.tsx`, `toaster.tsx` (6 s auto-dismiss), `version-refresh-notice.tsx`.
Hook: `src/lib/hooks/use-pending-runs.ts`.

Client fetch layer `src/lib/api-client.ts`: `apiFetch(url, zodSchema)` / `apiMutate(url, schema, {method, body})`
— network/HTTP/Zod failures are **auto-toasted** and trigger a build-version check (`src/lib/version-check.ts`).

---

## 13. Scraping & external data acquisition

### 13.1 Apify client — `src/lib/apify/{client,cache-config,index}.ts`

`runApifyActor(actorId, input, {label?, retries=2, timeoutSecs?, signal?, skipCache?, log?})`:

- Synchronous endpoint, **no polling**: `POST https://api.apify.com/v2/acts/{id with / → ~}/run-sync-get-dataset-items?token=APIFY_API_TOKEN[&timeout=]`,
  JSON body = actor input; response = dataset items array.
- **Cache**: key `sha256(actorId + sortedStringify(input))` in `apify_cache`; hit only if `expiresAt > now`;
  read/write errors are non-fatal. TTLs (`cache-config.ts`): 5 min for post/tweet/reaction/comment/reshare
  actors, 1 h for LinkedIn post search, default **30 days** for everything else. `cleanExpiredApifyCache()`.
- Fetch timeout `(timeoutSecs ?? 300)+30` s; retries only on `fetch failed` / `ECONNREFUSED` with 0/5/10 s backoff.
- `runApifyActorPaginated(actorId, baseInput, {maxPages=5,…})` adds `page_number`, stops on 0 or <100 results.
- Fixtures: `apify/<actor>-sample.json` + `apify/inputs/<actor>.json` (20 each); `scripts/test-scrapers.ts`.

### 13.2 Every Apify actor

| #   | Actor id                                                                   | Called from                                                                                                                             | Input                                                                                                                                                                                                               | Powers                                                                                                                                                                                             |
| --- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `supreme_coder/linkedin-post`                                              | `scrapeProfilePosts(url, max)` in `lib/linkedin-engagement-bot.ts`                                                                      | `{urls:[url], limitPerSource}` (3 sync / 5 alpha sages / 1 tracker)                                                                                                                                                 | LinkedIn profile sync posts, post tracker, alpha feed sages. Fields: `urn, url, text, numLikes, numComments, numShares, rootShare, author{occupation…}, authorName, authorProfileUrl, postedAtISO` |
| 2   | `Wpp1BZ6yGWjySadk3` (LinkedIn Posts Scraper)                               | `lib/linkedin-audit.ts` (`limitPerSource:100, deepScrape`), `lib/growth-report/scrapers.ts` (20)                                        | `{urls, limitPerSource, deepScrape:true}`                                                                                                                                                                           | LinkedIn audit, growth report                                                                                                                                                                      |
| 3   | `apimaestro~linkedin-post-reactions`                                       | `scrapePostReactions` in `lib/linkedin-engagement.ts` (paginated, maxPages 3)                                                           | `{post_urls:[url], page_number}`                                                                                                                                                                                    | engager windows → `linkedin_post_engagements`                                                                                                                                                      |
| 4   | `apimaestro~linkedin-post-comments-replies-engagements-scraper-no-cookies` | `scrapePostComments` (paginated)                                                                                                        | `{postIds:[url], page_number}`                                                                                                                                                                                      | comments + nested replies → `linkedin_post_comments`                                                                                                                                               |
| 5   | `apimaestro~linkedin-post-reshares`                                        | `scrapePostReshares` (paginated)                                                                                                        | `{post_urls, page_number}`                                                                                                                                                                                          | repost engagers                                                                                                                                                                                    |
| 6   | `apimaestro~linkedin-posts-search-scraper-no-cookies`                      | `lib/alpha-feed-core.ts`                                                                                                                | `{keyword, total_posts:5, date_filter:"past-24h", sort_type:"date_posted"}`                                                                                                                                         | alpha feed keyword lane (`post_url, text, author{name,headline,profile_url}, stats{total_reactions,comments,shares}, posted_at{timestamp}, is_reshare`)                                            |
| 7   | `VhxlqQXRwhW8H5hNV` (LinkedIn Profile Scraper)                             | `lib/linkedin-audit.ts`, growth report                                                                                                  | `{username: slug}`                                                                                                                                                                                                  | profile JSON for audit/generator/growth                                                                                                                                                            |
| 8   | `scrape.badger/twitter-tweets-scraper`                                     | `lib/twitter-engagement-bot.ts` (`scrapeProfileTweets`, `scrapeTweetReplies`, `scrapeTweetRetweeters`), `trigger/twitter-alpha-feed.ts` | modes: `Advanced Search` (`query:"from:<handle>"` or keyword, `query_type:"Latest"`, `max_results`), `Get Replies` (`id, max_results:50, page_number`), `Get Retweeters`; `Get Favoriters` unusable (likes private) | all Twitter scraping                                                                                                                                                                               |
| 9   | `nFJndFXA5zjCTuudP` (Google SERP)                                          | `lib/sentiment-scraper.ts`, growth report                                                                                               | `{queries:"q1\nq2", maxPagesPerQuery:1, resultsPerPage:10}`                                                                                                                                                         | sentiment, growth SERP                                                                                                                                                                             |
| 10  | `oKbfaRlpOJ4bubyBN` (Reddit)                                               | sentiment                                                                                                                               | `{searches:[…], maxItems:30, sort:"relevance", time:"year"}`                                                                                                                                                        | sentiment                                                                                                                                                                                          |
| 11  | `compass/Google-Maps-Reviews-Scraper`                                      | sentiment                                                                                                                               | `{searchStringsArray:[…], maxReviews:50, language:"en"}`                                                                                                                                                            | sentiment                                                                                                                                                                                          |
| 12  | `aYG0l9s7dbB7j3gbS` (web/cheerio scraper)                                  | sentiment (`scrapeWebUrls`, G2/Capterra search URLs)                                                                                    | `{startUrls:[{url}], maxCrawlingDepth:0, maxPagesPerCrawl}`                                                                                                                                                         | sentiment                                                                                                                                                                                          |
| 13  | `trudax/reddit-scraper-lite`                                               | growth report                                                                                                                           | `{searches:[brand], maxItems:50, sort:"relevance", time:"all"}`                                                                                                                                                     | growth                                                                                                                                                                                             |
| 14  | `ecomdate/similarweb-scraper`                                              | growth report                                                                                                                           | `{domains:[…]}`                                                                                                                                                                                                     | traffic benchmarks                                                                                                                                                                                 |
| 15  | `radeance/ahrefs-scraper`                                                  | growth report                                                                                                                           | `{urls:[…], searchMode:"domain_overview"}`                                                                                                                                                                          | domain authority                                                                                                                                                                                   |
| 16  | `UFSUQD7pWNwN3jExC` (SEO audit)                                            | growth report                                                                                                                           | `{startUrls:[{url}], maxPagesPerCrawl:20}`                                                                                                                                                                          | SEO section                                                                                                                                                                                        |
| 17  | `apify/instagram-profile-scraper`                                          | growth report                                                                                                                           | `{usernames:[handle]}`                                                                                                                                                                                              | social                                                                                                                                                                                             |
| 18  | `clockworks/tiktok-profile-scraper`                                        | growth report                                                                                                                           | `{profiles:[handle]}`                                                                                                                                                                                               | social                                                                                                                                                                                             |
| 19  | `apify/screenshot-url`                                                     | growth report — **commented out**, replaced by Playwright                                                                               | —                                                                                                                                                                                                                   | —                                                                                                                                                                                                  |

### 13.3 Non-Apify sources

| Source                                 | Where                                                                                                                                    | Purpose                                                                                                                                                                  |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Playwright Chromium                    | `lib/growth-report/take-screenshots.ts`                                                                                                  | site screenshots (1280×800 @2x, overlay dismissal, `sharp` → JPEG ≤5 MB) for growth report; `screenshot-test` task                                                       |
| cheerio + `fetch`                      | `lib/geo-audit/{fetch-page,citability-scorer,llmstxt-validator,brand-scanner}.ts`; `lib/growth-report/scrapers.ts#fetchAiVisibility`     | GEO audit: page meta/JSON-LD/links/security headers, `robots.txt` AI-crawler classification (14 bots), `llms.txt`, sitemap crawl (20 pages), Wikipedia/Wikidata presence |
| `@seomator/seo-audit` CLI              | `trigger/seo-audit.ts`                                                                                                                   | `seomator init -y` then `seomator audit <url> --format json [--crawl -m N] [-c cats] [--no-cwv] -o audit-results.json`                                                   |
| Claude `WebSearch`/`WebFetch` tools    | via Claude Agent SDK in GTM, audits, GEO, enrichment, outbound research, alpha-feed spec, growth discovery, idea bot                     | web research inside agent loops                                                                                                                                          |
| Anthropic Messages API (raw)           | categorisers, `generateReply`, comment reply suggestions, lead scoring, audit post-process                                               | short-form generation/classification                                                                                                                                     |
| OpenAI Whisper                         | `lib/knowledge/transcribe.ts` (`whisper-1`, multipart)                                                                                   | voice notes from Slack                                                                                                                                                   |
| Google Drive/Docs/Sheets/Calendar REST | `lib/gdrive.ts`, `lib/knowledge/drive-resolver.ts`, `lib/gcalendar.ts`                                                                   | uploads, doc text, calendar events (syncToken)                                                                                                                           |
| Slack Web API (read)                   | `lib/knowledge/slack-client.ts` (`conversations.history/replies/info`, `users.list`, file download; 2000 msgs/run, 300 ms between pages) | knowledge ingestion                                                                                                                                                      |
| GitHub REST                            | 4 PR-bot tasks (`POST /repos/{o}/{r}/pulls`)                                                                                             | PRs                                                                                                                                                                      |

---

## 14. Background jobs — Trigger.dev

`trigger.config.ts`: project `proj_omchykblaxtcsrpezhql`, runtime `node`, `maxDuration 3600`,
retries default `maxAttempts 3, 1 s→10 s, factor 2, randomize`, `dirs ["./src/trigger"]`, machine
`small-2x`, `build.external` = agent SDK, anthropic SDK, `postgres`, `playwright-core`; extensions
`additionalPackages([@seomator/seo-audit, @anthropic-ai/sdk, sharp, cheerio@1.2.0])` and
`playwright({browsers:["chromium"]})`. Conventions: `logger` not console, `metadata.set("progress", …)`,
Slack notify on failure, tmp session dir per agent run removed in `finally`.

**All 14 crons are commented out (`CRON DISABLED 2026-05-12`)** — tasks remain triggerable manually.

| Task id                                                                 | File                          | Kind / cron (disabled)                  | maxDur  | Queue/conc                     | Purpose                                                                                 |
| ----------------------------------------------------------------------- | ----------------------------- | --------------------------------------- | ------- | ------------------------------ | --------------------------------------------------------------------------------------- |
| `linkedin-audit-generation`                                             | linkedin-audit.ts             | task                                    | 3600    | —                              | Apify profile+posts → Claude (opus) → `postProcessAudit` → DOCX                         |
| `twitter-audit-generation`                                              | twitter-audit.ts              | task                                    | 1800    | —                              | 50 tweets → Claude → DOCX                                                               |
| `linkedin-post-generator`                                               | linkedin-post-generator.ts    | task                                    | 1800    | —                              | source material + optional profile scrape + 5 random hooks → Google Doc                 |
| `twitter-post-generator`                                                | twitter-post-generator.ts     | task                                    | 1800    | —                              | 3 parallel agents (single/thread/long) → Google Doc                                     |
| `linkedin-to-twitter` / `twitter-to-linkedin`                           | \*.ts                         | task                                    | 300     | —                              | text-only Claude (haiku) → `tool_runs.output`                                           |
| `gtm-strategy-generation`                                               | gtm-strategy.ts               | task                                    | 3600    | —                              | ≥7 web searches → JSON → DOCX                                                           |
| `seo-audit-generation`                                                  | seo-audit.ts                  | task                                    | 3600    | —                              | seomator → Claude (haiku) → DOCX                                                        |
| `sentiment-analysis-generation`                                         | sentiment-analysis.ts         | task                                    | 3600    | —                              | 4 Apify sources → Claude → DOCX                                                         |
| `geo-audit`                                                             | geo-audit.ts                  | task                                    | 1800    | `geo-audit`/2                  | cheerio gather → Claude (60 turns) → DOCX                                               |
| `growth-report-generation`                                              | growth-report.ts              | task, `medium-2x`                       | 3600    | —                              | discovery agent → 12 Apify sources → screenshots → analysis agent → review agent → DOCX |
| `outbound-sequence-generation`                                          | outbound-sequence.ts          | task                                    | 3600    | —                              | ICP research → generation → review agents → DOCX playbook                               |
| `linkedin-sync-scheduler` → `linkedin-sync-profile`                     | linkedin-sync.ts              | cron `5 */6 * * *` → task               | 600     | `linkedin-sync`/3              | fan-out; per-profile `syncLinkedinProfileCore`                                          |
| `twitter-sync-scheduler` → `twitter-sync-profile`                       | twitter-sync.ts               | cron `15 */4 * * *` → task              | 600     | `twitter-sync`/3               | Twitter sync (inline core)                                                              |
| `linkedin-lead-upsert` / `twitter-lead-upsert`                          | \*.ts                         | task                                    | 600     | `*-lead-upsert`/2              | engagers+comments → `leads`, CSV DM, ICP scoring (no Apify)                             |
| `weekly-analytics-scheduler` → `weekly-analytics`                       | linkedin-analytics-scrape.ts  | cron `0 7 * * 1` → task                 | 300     | `analytics-scrape`/2           | `runWeeklyReportForProfile` → Slack                                                     |
| `twitter-weekly-analytics-scheduler` → `twitter-weekly-analytics`       | twitter-analytics-scrape.ts   | cron `30 7 * * 1`                       | 300     | `twitter-analytics`/2          | last-7-days aggregate → Slack                                                           |
| `track-post` / `track-tweet`                                            | \*-post-tracker.ts            | task (delayed ×5)                       | 300     | —                              | re-scrape metrics, snapshot, reply in Slack thread                                      |
| `post-categoriser(-scheduler)` / `twitter-post-categoriser(-scheduler)` | \*-post-categoriser.ts        | cron `15 7 * * *` / `30 7 * * *` London | 300     | —                              | raw Anthropic `claude-sonnet-4-6`, batches of 30 → `category`                           |
| `engagement-slack-action` / `twitter-engagement-slack-action`           | \*-engagement-slack-action.ts | task                                    | 60      | —                              | legacy (Temporal now)                                                                   |
| `alpha-feed-generate-spec`                                              | alpha-feed.ts                 | task                                    | 900     | —                              | 2 parallel sonnet agents (WebSearch) → sages/keywords merge-upsert                      |
| `alpha-feed-collect-scheduler` → `alpha-feed-collect-worker`            | alpha-feed.ts                 | cron `0 7 * * *` → task                 | 1800    | `alpha-feed-collect`/3         | `collectAlphaFeedCore` (Temporal now)                                                   |
| `twitter-alpha-feed-collect-scheduler` → `…-worker`                     | twitter-alpha-feed.ts         | cron `30 7 * * *`                       | 300     | `twitter-alpha-feed-collect`/3 | inline Twitter collection, no Slack                                                     |
| `calendar-sync`                                                         | calendar-sync.ts              | cron `*/30 7-22 * * *` London           | 600     | —                              | Google Calendar incremental sync + matching                                             |
| `calendar-meeting-notifier`                                             | calendar-meeting-notifier.ts  | cron `25,55 6-21 * * *` London          | 120     | —                              | DM prep 30 min before meetings                                                          |
| `account-enrichment`                                                    | account-enrichment.ts         | task                                    | 120     | `account-enrichment`/2         | web-research auto-created accounts                                                      |
| `knowledge-slack-ingest-scheduled` / `-channel`                         | knowledge-slack-ingest.ts     | cron `*/30 8-22 * * 1-5` London         | 1800    | —                              | ingest → `triggerAndWait` resolve → normalise-all                                       |
| `knowledge-resolve-media`                                               | knowledge-resolve.ts          | task                                    | 600     | —                              | Whisper + Drive resolution                                                              |
| `knowledge-normalise-channel` / `-all`                                  | knowledge-normalise.ts        | task                                    | 300/600 | —                              | two-stage LLM extraction                                                                |
| `knowledge-state-synthesis-schedule` / `-on-demand`                     | knowledge-state-synthesis.ts  | cron `0 8 * * 1` London                 | 600     | —                              | brief / open_items / activity_log                                                       |
| `knowledge-digest-schedule` / `-on-demand`                              | knowledge-digest.ts           | cron `0 9 * * 1-5` London               | 300     | —                              | threaded Slack DM digest                                                                |
| `idea-generator`                                                        | idea-generator.ts             | cron `0 9 * * 1-5` London               | 3600    | —                              | ideation + implementation agents → PR, appends `IDEAS.md`                               |
| `code-quality-scan`                                                     | code-quality-scan.ts          | cron `0 8 * * 1` London                 | 3600    | —                              | doc-gardening agent → PR                                                                |
| `implement-suggestion`                                                  | implement-suggestion.ts       | task                                    | 3600    | —                              | suggestion → PR                                                                         |
| `ingest-skill`                                                          | ingest-skill.ts               | task                                    | 3600    | —                              | analyse SKILL.md → implement tool → PR                                                  |
| `screenshot-test`                                                       | screenshot-test.ts            | task (manual)                           | —       | —                              | Playwright QA harness                                                                   |

---

## 15. Background jobs — Temporal

`src/temporal/`: `load-env.ts` (dotenv, must be first import), `client.ts` (lazy `Client` singleton for
API routes), `shared.ts` (`TASK_QUEUE`, `WORKFLOWS` name map), `worker.ts` (`Worker.create({workflowsPath,
activities})`), `workflows/*` (sandboxed), `activities/*` (Node). Failure rule preserved: each activity
catches, calls `sendSlackNotification({userName:"temporal-worker", runId: workflowId})`, rethrows.

| Workflow                                   | Activity                                                                                              | Replaces                       | Timeout / retry | Started by                                                             |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------- | ------------------------------ | --------------- | ---------------------------------------------------------------------- |
| `engagementSlackAction`                    | `processEngagementSlackAction`                                                                        | `engagement-slack-action`      | 60 s / 1        | `/api/linkedin-engagement-slack`                                       |
| `twitterEngagementSlackAction`             | `processTwitterEngagementSlackAction`                                                                 | Twitter version                | 60 s / 1        | `/api/twitter-engagement-slack`                                        |
| `linkedinSyncProfile`                      | `syncLinkedinProfile` (→ `syncLinkedinProfileCore`, dispatches `linkedinLeadUpsert` child via client) | `linkedin-sync-profile`        | 600 s / 2       | `/api/accounts/[id]/engagement/scrape`                                 |
| `twitterSyncProfile`                       | `syncTwitterProfile`                                                                                  | `twitter-sync-profile`         | 600 s / 2       | `/api/accounts/[id]/twitter-engagement/scrape`                         |
| `linkedinLeadUpsert` / `twitterLeadUpsert` | `upsertLinkedinLeads` / `upsertTwitterLeads`                                                          | lead upserts                   | 600 s / 2       | from sync activities                                                   |
| `alphaFeedCollect`                         | `collectAlphaFeed` (→ `collectAlphaFeedCore`)                                                         | `alpha-feed-collect-worker`    | **30 min** / 2  | `/api/accounts/[id]/alpha-feed/[icpId]/collect`, `alphaFeedCollectAll` |
| `alphaFeedCollectAll`                      | `listActiveAlphaFeedIds` + `executeChild` ×N (3 at a time)                                            | `alpha-feed-collect-scheduler` | —               | Schedule `alpha-feed-collect-daily`                                    |

`scripts/temporal-schedules.ts` upserts schedules **paused**: `alpha-feed-collect-daily` =
`{calendars:[{hour:8, minute:0}], timezone:"Europe/London"}`, overlap `SKIP`. Migration plan and
remaining phases (tool tasks, knowledge hub, calendar, Twitter, cron tasks, cutover) live in
`docs/plans/active/temporal-migration.md`. Workflow ids: `<name>:<entityId>:<Date.now()>`.
Frontend polls `/api/temporal-runs/[workflowId]` (status name from `describe()`).

---

## 16. Subsystem flows, start to end

### 16.1 LinkedIn profile sync (`src/lib/linkedin-sync-core.ts`, 10 steps)

Constants: `MAX_POSTS_PER_SYNC=3`, `OUTBOUND_MAX_AGE_DAYS=1`, `COMMENT_SCRAPE_MAX_AGE_DAYS=2`,
early engager window 4–12 h, late window 68–80 h after posting. 0. Load `linkedin_profiles` row; insert `linkedin_sync_runs` (`running`).

1. `scrapeProfilePosts(url, 3)` (actor 1).
2. `normalizeApifyPost` — drop reposts/other authors, truncate content to 500 chars, dedupe by `apifyPostId`.
3. Load existing posts; backfill `displayName`.
4. Upsert `linkedin_posts` (new outbound posts ≤1 day old get `engagementStatus="pending"`); insert `linkedin_post_snapshots`.
5. Posts ≤2 days: `scrapePostComments` (actor 4) → upsert `linkedin_post_comments` (replies flattened with `parentCommentId`); an owner reply marks **its parent** `repliedToByOwner=true`.
6. Per post in an unscraped window: `scrapePostReactions` + `scrapePostReshares` in parallel (actors 3,5) → `linkedin_post_engagements` (`scrapeWindow`, `engagedAt` = post date); stamp `early/lateEngagersScrapedAt`.
   6b. If `inboundEnabled` and windows scraped → dispatch lead upsert `{profileId, accountId, contactId, scrapeWindow}`.
7. If `outboundEnabled`: read `accounts.engagementSlackChannel`; atomically claim `pending→sending`; `sendPostToSlack` card (Comment/Like/Repost/Skip/Go to Post) → `sent_to_slack` + `slackMessageTs`; revert to `pending` on failure.
8. If `analyticsEnabled`: `sendUnrepliedCommentAlerts` — top-level, unreplied, un-notified comments ≤7 days, grouped per post, AI reply suggestions (`claude-opus-4-6`, voice guidance from contact/account) → `sendAnalyticsSlackMessage` to every channel in `accounts.analyticsSlackChannel`; set `notifiedAt`.
9. Update `lastSyncedAt`. 10. Mark run `completed` (`postsFound`, `postsNew`); on error mark `failed`, rethrow.

### 16.2 Engagement Slack action

Slack button → `/api/linkedin-engagement-slack` (HMAC verify, 5-min replay window) → parse
`engage_(comment|like|repost|skip):<postId>` → Temporal `engagementSlackAction` → activity: load post +
profile → **atomic claim** `sent_to_slack → processing` (double-click safe) → if `comment`:
`generateComment(content, persona)` (agent SDK, humanisation rules; failure → status `failed`, card repainted)
→ status `skip` or `awaiting_action` → `updateSlackCard` with decision + generated comment. The human
then posts the comment on LinkedIn manually.

### 16.3 Lead upsert (`linkedin-lead-upsert` / Temporal activity)

Read engagements + comments for the profile; normalise to `EngagerRecord`; dedupe by trailing-slash
URL, then merge URN URLs with slug URLs by name; transactional upsert into `leads` (partial unique
index); if `scrapeWindow` set: build CSV (`lib/csv.ts`), insert `lead_csvs`, back-link `leads.leadCsvId`,
DM the CSV to `tarun@mvrxlabs.com` via `sendSlackFile`; then `scoreLeadsBatch` (`lib/lead-enrichment.ts`,
Claude) against active `icp_definitions` → `tier`, `conversionPct`, `rationale`.

### 16.4 Weekly analytics

Scheduler fans out per `analyticsEnabled` profile → `runWeeklyReportForProfile` (`lib/analytics-pipeline.ts`,
`analytics-report.ts`, `analytics-slack.ts`): aggregate last 7 days from `linkedin_posts`/snapshots,
upsert `analytics_reports` (unique per period), `buildAnalyticsSlackMessage` → each channel in
`accounts.analyticsSlackChannel`. Post tracking: `@mention` the analytics bot with a post URL in a
channel → `/api/slack/analytics-events` → 5 delayed `track-post` runs reply in-thread with metrics.

### 16.5 Alpha feed (`src/lib/alpha-feed-core.ts`)

Spec: `alpha-feed-generate-spec` runs LinkedIn + Twitter sonnet agents with WebSearch from the ICP
(`trigger/alpha-feed-prompts.ts`) and merge-upserts `sages[]`/`keywords[]`.
Collect (`collectAlphaFeedCore`, daily 08:00 UK via Temporal schedule or "Collect Now"):

1. Sage lane: `scrapeProfilePosts(sage, 5)`; skip `rootShare===false` (reposts); author link/headline from raw.
2. Keyword lane: actor 6 (`past-24h`, 5 posts); skip `is_reshare`.
3. `engagementScore = likes + comments*3 + reposts*5`; `dedupeEntries` (canonical URL without query
   string **and** `author|first-200-chars` fingerprint, highest score wins).
4. Carry over `slackTs` from previous days; `dailyEntries[today] = …`; prune >7 days; save.
5. `sendNewEntriesToSlack`: `accounts.alphaFeedSlackChannel`; candidates = no `slackTs`, `postedAt`
   within 7 days, `likes+comments+reposts >= SLACK_MIN_ENGAGEMENTS (10)`, top `SLACK_MAX_POSTS_PER_RUN (10)`;
   `buildAlphaFeedCard` (🔥 Alpha Feed · ICP, linked author + headline, 500-char excerpt, 👍💬🔁 · source ·
   date, "Go to Post") via `sendAnalyticsSlackMessage`; set `slackTs`; save again.
   Twitter variant (`trigger/twitter-alpha-feed.ts`): inline, score `likes + rt*3 + replies*2 + views*0.01`, no Slack.

### 16.6 AI tool (e.g. LinkedIn audit)

Route inserts `tool_runs` → task: Apify profile + posts → write JSON files into a tmp session dir →
`query()` / `runClaudeAgent` with `Read`/`WebSearch` tools → `extractJSON` (fenced JSON or session-dir
fallback) → `postProcessAudit` → `buildAuditDocx` → `findOrCreateFolder(accountName)` under Generated
Materials → `uploadFile("MVRX | <name> | LinkedIn Audit.docx")` → `tool_runs.completed` with `outputUrl`.
Growth report adds a discovery agent, 12 scrapers, Playwright screenshots + vision evaluation, an analysis
agent (opus), a review agent (sonnet) and `repairJSON` fallback; outbound sequence adds ICP research →
generation → review agents; Twitter post generator runs 3 format agents in parallel.

### 16.7 Knowledge Hub

ingest (`lib/knowledge/ingest.ts`: cursor `lastMessageTs`, skip join/leave subtypes, `authorSide` by
MVRX team ids `T07LGKRJ2AC`/`T0A72PKB8R2` or `@mvrxlabs.com`, `visibility` internal for
`client_internal`/`internal` channels) → `knowledge_events` → resolve media (Whisper voice notes; Drive
docs/sheets text) → normalise (`normaliser.ts`: batch 50; classification prompt groups general-channel
messages by account; extraction prompt → `extractionOutputSchema {units[], completedItems[]}`; Jaccard
dedup against 500 recent units; `claude-sonnet-4-6`, cost tracked) → `knowledge_units` → weekly state
synthesis (one LLM call → `brief`, `open_items`, `activity_log`, versioned) → daily digest (threaded DMs
per account/item to hard-coded recipients `U0ACUKDKYGK`, `U0AJ4E662G1`; stale >3 weeks flagged;
`knowledge_digest_messages`) → ✅ reaction on a digest line (`/api/knowledge/slack-events`) marks the unit
done and updates every recipient's DM (idempotent; reaction removed reopens).

### 16.8 Calendar

`calendar-sync`: rotate stale `nextMeetingAt`→`lastMeetingAt`; per user: incremental sync with
`syncToken` (410 → full sync −7/+7 days); skip events without external attendees; upsert
`calendar_events`; `matchOrCreateForAttendee` (`lib/calendar-matching.ts`: contact email → contact
domain → account `emailDomain` → auto-create account, personal domains skipped) → join tables with
`matchConfidence`/`matchedVia`; new domains trigger `account-enrichment`; update next/last meeting
timestamps. `calendar-meeting-notifier`: events starting in ≤30 min, `confirmed`, `notifiedAt IS NULL`
→ `sendSlackDM` to the calendar owner with accounts, contacts + RSVP status; set `notifiedAt`.

### 16.9 PR bots

All clone `https://x-access-token:$GITHUB_TOKEN@github.com/$OWNER/$REPO.git --depth 50`, commit as
`danny-hunt <danny@mvrxlabs.com>`, push a branch, open a PR against `main`.
`idea-generator` (branch `idea/<ts>-<rand>`, random scope/multi-idea/web-search config, appends to
`IDEAS.md` on main), `code-quality-scan` (`doc-gardening/<date>`, `*.md` only), `implement-suggestion`
(`suggestion/<runId>/<toolId>`), `ingest-skill` (`skill/<slug>`, PR body has a security checklist).

---

## 17. AI layer: Claude, models, prompts, humanisation

- **`runClaudeAgent(prompt, cwd, {allowedTools, maxTurns, model?})`** (`src/lib/claude-agent.ts`) wraps
  `query()` from `@anthropic-ai/claude-agent-sdk` with `permissionMode:"bypassPermissions"`,
  `persistSession:false`, logs every tool call, returns `{output, costUsd, durationMs, turns}`; default
  model `claude-opus-4-6`. Tasks needing abort signals call `query()` directly.
- **Models** (`src/lib/audit-utils.ts`): `MODEL_MAP = {haiku:"claude-haiku-4-5-20251001",
sonnet:"claude-sonnet-4-6", opus:"claude-opus-4-6"}`; `resolveModel(requested, fallback)`. One stale
  pin: `lib/linkedin-engagement-bot.ts#generateComment` uses `claude-sonnet-4-20250514` (retired) — fix in rebuild.
- **JSON handling**: `extractJSON` (fenced ```json or bare object), `extractJSONFromSessionDir`,
`repairJSON` (asks Claude to fix broken JSON).
- **Session dirs**: `os.tmpdir()/<prefix>-<uuid>`, deleted in `finally`. Input files (`scraped-*.json`,
  `source-material.txt`, `voice-context.txt`, `research.json`, `similarweb.json`…) are written there and
  the agent reads them with `Read`/`Glob`.
- **Cost**: per-run `costUsd` logged / returned / put in `metadata.totalCostUsd`; no cost table.
- **Prompt files**: `trigger/alpha-feed-prompts.ts`, `idea-generator-prompts.ts`, `ingest-skill-prompts.ts`,
  `linkedin-hook-templates.ts` (50 hooks, `getRandomHookTemplates(5)`); `lib/linkedin-post-prompts.ts`,
  `twitter-post-prompts.ts`, `twitter-prompts.ts` (UI-editable presets, `{{POST}}`/`{{POSTER_NAME}}`
  placeholders); `lib/knowledge/prompts.ts`; `lib/growth-report/{analysis,review}-prompt.ts`;
  `lib/outbound-sequence/{generation,review}-prompt.ts`; inline `GTM_PROMPT`, `SEO_ANALYSIS_PROMPT`,
  `SENTIMENT_PROMPT`, `buildAuditPrompt` (GEO, 6 weighted dimensions), categoriser prompts.
- **Humanisation** (`src/lib/humanisation/`): `AI_TELL_VOCABULARY` (~70 words: delve, tapestry,
  leverage, robust, …), `AI_TELL_PHRASES`, `CORPORATE_BANNED_PHRASES`; blocks `buildAntiAIVocabBlock`,
  `buildPunctuationRulesBlock` (**no em dashes**, ≤1–2 emojis), `buildNaturalnessBlock` (contractions,
  burstiness, grade 6–8), `buildBannedPhrasesBlock`, `buildHumanisationPassBlock` (5-step self-edit),
  `buildShortFormHumanisationBlock`. Used by all generators, audits, engagement reply generation, outbound.
  `guides/linkedin/*.md` are reference material (not loaded at runtime).
- **Raw SDK uses**: post categorisers (`claude-sonnet-4-6`, batch 30), comment reply suggestions
  (`claude-opus-4-6`), Twitter reply generation (`claude-sonnet-4-6`), lead scoring, audit post-process.

---

## 18. Slack integration

Three Slack apps + one incoming webhook (`docs/slack-app-manifests/`):

| App                                                                         | Token / secret                                                | Scopes needed                                                                                                                                                                                                                        | Used for                                                                                  |
| --------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| App 1 "main bot"                                                            | `SLACKBOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_WEBHOOK_URL` | `chat:write`, `users:read`, `users:read.email`, `files:write`, `im:write`; Interactivity Request URL → `/api/linkedin-engagement-slack` (and `/api/twitter-engagement-slack`)                                                        | engagement cards + buttons, meeting DMs, lead CSV DMs, failure/PR notifications (webhook) |
| App 2 "MVRX Portal Alerts" (`analytics-bot.yaml`; bot `mvrx-portal-alerts`) | `ANALYTICS_SLACKBOT_TOKEN`                                    | `chat:write`, `channels:read`, `groups:read` (+ `app_mentions:read` + Events URL `/api/slack/analytics-events` for post tracking)                                                                                                    | weekly analytics, unreplied-comment alerts, post tracking, **alpha feed cards**           |
| App 3 "knowledge bot"                                                       | `KNOWLEDGE_SLACKBOT_TOKEN`, `KNOWLEDGE_SLACK_SIGNING_SECRET`  | `channels:history`, `groups:history`, `channels:read`, `users:read`, `users:read.email`, `files:read`, `im:write`, `chat:write`, `reactions:read`; Events URL → `/api/knowledge/slack-events` (`reaction_added`, `reaction_removed`) | Knowledge Hub ingest (read-only client), digests, ✅ handling                             |

Rules: bots must be **invited** to every target channel (mandatory for private ones); channel IDs are
stored per account on `accounts.*_slack_channel` (analytics field may be comma-separated). Signature
verification: `v0=HMAC-SHA256(secret, "v0:{ts}:{body}")` compared with `timingSafeEqual`; replay window
5 min (knowledge route also rejects NaN/future timestamps and fails closed without a secret).

`src/lib/slack.ts` exports: `sendSlackNotification` (webhook, never throws, dev-mode aware),
`sendSlackSuggestionNotification`, `sendSlackIdeaNotification`, `resolveSlackUserId` (cached on
`users.slackUserId`), `sendSlackDM`, `sendAnalyticsSlackMessage` (returns `ts`; `thread_ts` option),
`sendKnowledgeSlackDM`, `sendSlackFile` (3-step external upload). Card builders: `buildPostCard`
(`lib/linkedin-engagement-bot.ts`), `sendTweetToSlack` (`lib/twitter-engagement-bot.ts`),
`buildAnalyticsSlackMessage` (`lib/analytics-slack.ts`), `buildAlphaFeedCard` (`lib/alpha-feed-core.ts`).
Dev simulator: `lib/slack-dev.ts` + `slack_outbox` + `/dev/slack`.

---

## 19. Google integration

- **Sign-in**: NextAuth Google provider, domain-locked.
- **Service account JWT** (`lib/google-auth.ts`): RS256-sign `{iss, scope, aud, exp:+1h, iat, sub?}`
  with `crypto.subtle`, exchange at `oauth2.googleapis.com/token` (`jwt-bearer`). `sub` = impersonated
  user for Calendar (domain-wide delegation).
- **Drive** (`lib/gdrive.ts`, scope `auth/drive`, all calls `supportsAllDrives=true`):
  `getGeneratedMaterialsFolderId()` (dev vs prod env var), `createFolder`, `findOrCreateFolder(name,
parent)`, `listFiles`, `getFile`, `exportFileContent` (text/plain), `uploadFile` (multipart/related,
  base64), `createGoogleDoc(name, content, folder, mime)`, `markdownToGoogleDocHtml`, `getPreviewUrl`.
  Folder structure: `<Generated Materials>/<Account name>/MVRX | <subject> | <Report>.docx`.
- **Calendar** (`lib/gcalendar.ts`, scope `calendar.readonly`): `fullCalendarSync(email, timeMin,
timeMax)` (`singleEvents=true`, `maxResults=250`, paginated, captures `nextSyncToken`),
  `incrementalCalendarSync(email, token)` (410 → `SyncTokenExpiredError`), external-attendee helpers.
- **Docs/Sheets** (`lib/knowledge/drive-resolver.ts`): fetch document text for links found in Slack.

---

## 20. Documents: DOCX builders & Drive output

One builder per deliverable, all using the `docx` package with shared style helpers:
`lib/linkedin-audit-docx/{builder,sections,styles}.ts` (schema `lib/audit-schema.ts`),
`lib/twitter-audit-docx/*`, `lib/geo-audit-docx/{builder,schema,sections,styles}.ts`,
`lib/growth-report/{builder,styles,schema}.ts` (embeds screenshots), `lib/outbound-sequence/{builder,schema}.ts`,
`lib/gtm-docx-builder.ts` + `gtm-schema.ts`, `lib/seo-audit-docx-builder.ts` + `seo-audit-schema.ts`,
`lib/sentiment-docx-builder.ts`. Post generators write **Google Docs** instead. Filenames follow
`MVRX | <subject> | <Deliverable>.docx`; MIME
`application/vnd.openxmlformats-officedocument.wordprocessingml.document`.

---

## 21. Conventions & quality gates

- Pre-commit (`.pre-commit-config.yaml`): Prettier on staged files, `tsc --noEmit`, `scripts/lint-architecture.sh`.
- `.file-length-allowlist`: 300-line cap per file except listed files (schema, tool-form, big pages…).
- Zod schemas for every request/response in `src/lib/api-schemas/`; UI parses responses with them
  (`apiFetch`) so schema drift surfaces as a toast.
- Prefixed CUID2 ids; `isObjectId(id, "acct")` lets routes accept id **or** slug.
- Every task: Trigger `logger`, `metadata.progress`, Slack on failure, tmp dir cleanup, per-item
  try/catch so one bad sage/keyword/post doesn't fail the run.
- `NOTES.md` records every mistake/wrong path (project rule); plans in `docs/plans/active` →
  `completed`.
- Data caveat: never assume accounts/contacts are complete; profile URLs may be stale.
- No automated tests; `scripts/test-*.ts` are manual.

---

## 22. Deployment

- **Next.js** → Vercel (auto on push). Env vars in Vercel. `/api/version` + `VersionRefreshNotice`
  prompt users to refresh on new builds.
- **DB** → Neon. `npm run db:generate` locally → commit SQL → `npm run db:migrate-prod`
  (`drizzle-prod.config.ts`). If prod was built with `db:push`, run `npm run db:fix-prod-journal` once.
- **Trigger.dev worker** → `npx trigger.dev@latest deploy` (`npm run deploy:prod` does migrate + deploy).
  Env vars in the Trigger dashboard. Schedules only run for tasks in the **latest** deployment.
- **Temporal worker** → currently local only (`npm run temporal:worker`); prod cutover pending
  (`docs/plans/active/temporal-migration.md`): Temporal Cloud/self-hosted with `TEMPORAL_TLS_*`,
  a long-running worker host, `npm run temporal:schedules` then unpause schedules.
- **Slack apps**: update Request URLs to the deployed domain (`/api/linkedin-engagement-slack`,
  `/api/twitter-engagement-slack`, `/api/knowledge/slack-events`, `/api/slack/analytics-events`).
- **Google OAuth**: add the deployed domain's callback URL.

---

## 23. Rebuild order (milestones)

1. **Skeleton**: Next.js 16 + TS + Tailwind 4; `docker-compose.yml` (Postgres 5433, Temporal);
   `.env.example`; Prettier/ESLint/pre-commit; `lint-architecture.sh`; `src/lib/ids.ts`.
2. **Schema & DB**: `src/lib/schema.ts` (§9), `db.ts`, drizzle configs, `db:push`, `seed.ts`.
3. **Auth**: `auth-config.ts`, middleware (deny-by-default this time — see §24), `x-api-key` path.
4. **CRM core**: accounts/contacts/actions/users/secrets routes + pages, `AccountProvider`, sidebar,
   `api-client.ts` + toaster, `/api/version`.
5. **Google**: service-account auth, Drive folders per account, `/resources`.
6. **Slack lib**: `slack.ts`, `slack-dev.ts`, `slack_outbox`, `/dev/slack`, failure notifications.
7. **Apify client + cache**; **LinkedIn profile registry** and sync core; engagement cards +
   interactivity route + action workflow; comment alerts; snapshots.
8. **Leads**: lead upsert, CSVs, ICP definitions, scoring, leads pages/export.
9. **Weekly analytics** + post tracking bot.
10. **Alpha feed** (spec generation, collection, Slack delivery, schedule).
11. **AI tools**: `runClaudeAgent`, `audit-utils`, humanisation module, `ToolForm` + `TOOLS`, then
    tools in this order: LinkedIn audit → post generator → cross-posters → GTM → sentiment → SEO →
    GEO → outbound sequence → growth report (heaviest). Each = route + task + DOCX builder.
12. **Twitter mirror** of 7–10.
13. **Calendar** sync + notifier + account enrichment.
14. **Knowledge Hub** (ingest → resolve → normalise → state → digest → ✅ events).
15. **PR bots** (suggestion, skill ingestion, idea generator, doc gardening).
16. **Orchestration**: pick **one** runner (Temporal recommended given the migration) for all jobs;
    define schedules; add the run-status polling route/indicator.
17. **Tests** for sync core, dedupe, lead upsert, Slack signature verification, API schemas.

---

## 24. Known issues to fix in a rebuild

- Middleware is an **allow-list**; unprotected routes today: `/api/dashboard` (leaks MRR),
  `/api/debug-auth` (leaks session), `/api/categorise-posts`, `/api/linkedin-posts/[postId]`,
  `/api/temporal-runs/[workflowId]`, `/api/slack/analytics-events` (**no Slack signature check**).
  Rebuild as deny-by-default with explicit public exceptions.
- API-key comparison is `!==`, not timing-safe.
- `sendAnalyticsSlackMessage` silently returns when the token is missing → tasks report success while
  nothing is sent; `analytics-pipeline.ts` sets `slackSent=true` unconditionally.
- Comma-separated `analyticsSlackChannel` is not deduped → possible duplicate sends.
- LinkedIn and Twitter halves are near-duplicates (sync, lead upsert, categoriser, analytics, engagement
  routes) and drift (e.g. replay-window guard only hardened on the knowledge route; Twitter alpha feed
  has no core module/Slack delivery; Twitter lead upsert always passes `scrapeWindow:"early"`).
- Two orchestrators overlap (7 jobs exist in both Trigger.dev and Temporal); `leads/scrape` and
  `twitter-sync` routes still use Trigger while engagement/alpha-feed use Temporal.
- `apifyRunId` is always `""`; `scrapeRecentPosts` is dead code; `track-tweet`, `twitter-post-categoriser`,
  `screenshot-test` have no callers; `implement-suggestion` references a non-existent
  `linkedin-humanizer.ts`; `.file-length-allowlist` references a moved file.
- Retired model id `claude-sonnet-4-20250514` in `generateComment`.
- `secrets.value` stored in plaintext.
- Knowledge digest recipients and MVRX Slack team ids are hard-coded; `org-dashboard-data.ts` hard-codes
  `danny@mvrxlabs.com`.
- `runApifyActorPaginated` has a hard-coded "500 results" Slack ping.
- All crons disabled since 2026-05-12 (cost control); re-enable deliberately per job.
