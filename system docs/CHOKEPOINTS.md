# CHOKEPOINTS.md - the rebuild manual

> **What this document is.** A from-scratch build specification for this codebase. If the repo
> were deleted tomorrow, this file plus a blank directory is enough to rebuild it: the problem
> it solves, every tool and API it uses, how the scraping works end to end, in what order to
> build the pieces, and what "done" looks like at each stage.
>
> **Status:** internal. It names the two proprietary browser-driven data sources by name.
> Those names must never appear on any public surface (site copy, HTML, OG text, commits).
> The public sourcing voice is *"expert calls, broker research and public filings"*.
>
> **House style throughout:** British English, no em dashes, no fabrication.

---

## Table of contents

1. [The problem statement](#1-the-problem-statement)
2. [The shape of the answer](#2-the-shape-of-the-answer)
3. [Non-negotiable rules](#3-non-negotiable-rules)
4. [Complete tool inventory](#4-complete-tool-inventory)
5. [Build order](#5-build-order)
6. [Phase 0 - repo skeleton and environment](#6-phase-0---repo-skeleton-and-environment)
7. [Phase 1 - the taxonomy](#7-phase-1---the-taxonomy)
8. [Phase 2 - the dataset and its gate](#8-phase-2---the-dataset-and-its-gate)
9. [Phase 3 - SCRAPING, start to end](#9-phase-3---scraping-start-to-end)
10. [Phase 4 - the judging layer](#10-phase-4---the-judging-layer)
11. [Phase 5 - the knowledge loop](#11-phase-5---the-knowledge-loop)
12. [Phase 6 - the research engine and deep dives](#12-phase-6---the-research-engine-and-deep-dives)
13. [Phase 7 - the website](#13-phase-7---the-website)
14. [Phase 8 - publishing and imagery](#14-phase-8---publishing-and-imagery)
15. [Phase 9 - unattended automation](#15-phase-9---unattended-automation)
16. [Secrets and environment](#16-secrets-and-environment)
17. [Acceptance checks per phase](#17-acceptance-checks-per-phase)
18. [Bugs already paid for - do not repeat them](#18-bugs-already-paid-for---do-not-repeat-them)
19. [Known gaps in the current build](#19-known-gaps-in-the-current-build)
20. [Appendix - live counts and glossary](#20-appendix---live-counts-and-glossary)

---

## 1. The problem statement

### 1.1 The question

**Everyone can name the winners at the top of the AI stack. Nobody can name the companies the
whole thing rests on.** An AI model answering a request is the last step of a physical chain that
starts with ore in the ground and runs through power stations, transformers, substations, data
centre shells, cooling plant, chip fabs and packaging lines. Most of that chain is owned by
private, regional, unglamorous businesses that no index tracks and no screen surfaces.

Two things follow, and they are the product:

1. **Where does the chain actually constrain?** Not "which markets are big", but which steps
   have no route around them. If this step stalls, the AI buildout stalls.
2. **Who owns those steps, and which of them are buyable?** Specifically the fragmented,
   critical, capex-pulled sub-markets full of private firms - the roll-up and carve-out surface.

### 1.2 The lens

Bottom-up, **through an energy and physical-infrastructure lens, built for private-equity deal
sourcing.** That lens dictates the shape of everything downstream:

- Depth is deliberately uneven. Raw materials through to the data centre floor are mapped deep;
  models and applications are kept shallow, present only as the demand side that pays for
  everything beneath.
- The emphasis is the private regional long tail, not the household names.
- The unglamorous niches are the point: spares, refurb, O&M, consumables, testing, permitting,
  commissioning, heavy transport. That is where the buyable businesses hide.

### 1.3 The two deliverables

| Deliverable | Audience | Form |
|---|---|---|
| **The atlas** | PE and finance professionals, public | An interactive map of the chain at `www.chokepoints.ai`, with a page per chokepoint and bottleneck |
| **The desk** | Internal | A scored, sourced dataset plus a validated thesis per opportunity, and a deep-dive newsletter |

### 1.4 What makes it credible, and therefore hard

Every row carries a **source** and a **confidence**. Every claim is dated and cited. Nothing is
asserted until adversarial validation has tried to kill it and failed. That single commitment
is what forces most of the machinery in this repo to exist: the audit gate, the two-tier
provenance model, the publish gate, the fit scorer, the validation files. **Remove the
no-fabrication rule and 70% of the code has no reason to exist.**

---

## 2. The shape of the answer

The system is **two machines sharing one dataset**. Almost every confusion comes from not
knowing which machine you are standing in.

```
 THE RESEARCH MACHINE (Python, local)          THE PUBLISHING MACHINE (Next.js, Vercel)
 ------------------------------------          ----------------------------------------
 hand-written YAML                             frozen JSON snapshots
   -> taxonomy.yaml, segments.csv                site/content/*.json
   -> companies.csv  (scraped, audited)   ==>    -> static HTML at build time
   -> opportunities.csv (judged)                 -> www.chokepoints.ai
   -> knowledge/theses (validated)
```

The seam is deliberate and one-way. The site reads **static committed JSON**, never a CSV,
never a database, never an API on your laptop. Editing `companies.csv` changes nothing on the
site until someone regenerates `site/content/*.json` and commits it. That is why the site
cannot break when the research machine is off, and why "my data change is not showing" is
almost always correct behaviour rather than a bug.

Within the research machine, data flows one way and nothing reads backwards:

```
build/nodes_L*.yaml  +  build/ratings.yaml         (hand-written, the only structural truth)
        |
        v  build/build.py  (validate + merge)
taxonomy.yaml · segments.csv · archetype-matrix.csv · signals.csv     (generated, never edited)
        |
        v  scraping and enrichment (Phase 3)
companies.csv        (the dataset, 12 columns, gated by audit.py)
        |
        +--> data/index.json + data/nodes/<nid>.json   (cheap query slices for agents)
        +--> opportunities.csv / .md                   (the PE read)
        +--> knowledge/theses/*.md + *.validation.md   (the opinion layer)
        +--> site/content/*.json                       (the publishing contract)
```

---

## 3. Non-negotiable rules

Copy these into the new repo before writing any code. They are load bearing.

| Rule | Why |
|---|---|
| **No fabrication, ever.** Every company row carries `source` and `confidence`; every claim is sourced and dated; unverified items are flagged, not asserted. | The dataset's only asset is that it can be trusted and re-checked. |
| **Refute first.** No opportunity is asserted until adversarial validation has tried and failed to kill it. | Several theses have not survived. That is the system working. |
| **Describe market structure. Never give investment advice or value a specific deal.** | Editorial and legal posture. |
| **The audit gate must return 0 hard issues before any commit touching data.** | The credibility gate, enforced mechanically. |
| **Never read `companies.csv` wholesale into an agent context.** Query through `chain.py` or `data/nodes/<nid>.json`. | It is now ~6.8 MB. It will destroy a context window. |
| **Agents write files. The orchestrator parses files, never agent transcripts.** | Transcripts overflow the orchestrator. This one rule is what makes large fan-outs survivable. |
| **The proprietary browser sources are read-only, screen-read only. Never export.** | Exports consume credits and breach the usage posture. |
| **Never name those sources on a public surface.** Public voice: "expert calls, broker research and public filings". | Contractual and competitive. |
| **Never publish the desk's internal scores, shares, owner rosters or rationale.** The public site shows evidence, never the verdict machinery. | Repeated verbatim across every generator script. |
| **British English, no em dashes.** Em-dash density is the single biggest AI tell in prose. | House voice, applied to code comments too. |
| **Reject, do not fake.** A figure that cannot be traced to a source is removed, not softened. A weak deep dive is killed, not published. | The pop comes from a genuinely good idea, never from spin. |
| **Never regenerate the slow poster visual in routine work.** | It is the slow path, for the shareable render only. |

---

## 4. Complete tool inventory

Everything the system touches, grouped by job. Anything marked *keyless* needs no account.

### 4.1 Languages and runtimes

| Tool | Version used | Job |
|---|---|---|
| Python | 3.14 (Homebrew), in a mandatory `.venv` | The whole research machine |
| Node.js / npm | 26 / 11 | The website |
| TypeScript | 5 | Site source language |
| SQLite (stdlib `sqlite3`) | - | Durable harvest state |
| launchd (macOS) | - | Unattended scheduling. Chosen over cron because a run missed while the Mac sleeps fires on wake |

Python dependencies are deliberately tiny: `pyyaml`, `requests`, `posthog`, `python-dotenv`.
Everything else, including all HTTP in the scrapers, uses the standard library (`urllib`,
`html.parser`, `csv`, `json`, `hashlib`, `fcntl`, `concurrent.futures`). That is a choice: fewer
dependencies means the scraper still runs in five years.

### 4.2 Data sources for scraping

| Source | Keyless? | What it gives | Constraint |
|---|---|---|---|
| **DBpedia SPARQL** (`dbpedia.org/sparql`) | yes | Wikipedia infoboxes as structured records: name, description, homepage, employees, founding year, location. **1,000 complete records per request.** 117,631 entities typed `dbo:Company`. | `robots.txt` publishes `Crawl-delay: 10`. Honour it. |
| **Wikimedia REST API** (`api.wikimedia.org/core/v1/wikipedia/en`) | yes | Title, one-line description, article excerpt, category listings | **500 requests/hour documented.** This is the binding budget for the live harvest. No business metadata at all. |
| **SEC EDGAR full-text search** (`efts.sec.gov`) | yes | Real, current, unambiguous US public company names from filings. Zero noise. | US public only |
| **The company's own website** | yes | About/history pages for founded year, headcount, HQ, ownership sentence | Subject to each site's own `robots.txt` |
| **Brave Search API** | key | Web evidence gathering: queries to URLs, for deep dives and node prose | Rate limited, key in `.brave_key` or `BRAVE_API_KEY` |
| **Yahoo Finance via `yfinance`** | keyless | Price, market cap, multiples, targets, revenue/EBIT/FCF history for listed subjects | Unofficial |
| **Museum open APIs** - Art Institute of Chicago, Cleveland Museum of Art, The Met | yes | CC0 public-domain art for editorial imagery | Chicago needs a `Referer: https://www.artic.edu/` header to download |
| **Private-company database** (browser, read-only) | session | The richest seam for the private regional long tail: name, website, country, founded, headcount, ownership | **Screen-read only. Never export - exports burn credits.** ~450 rendered rows per query. |
| **Broker and expert research platform** (browser, read-only) | session | Generative search over broker notes, expert transcripts and filings. Lead times, pricing, margins, capacity, named private and PE-backed companies | Read-only. Short attributed summaries only, never long verbatim excerpts. Facts from it are permanently `source_tier: restricted` |

### 4.3 Models, and the cost rule

The division of labour exists because the strong model and the cheap models are billed
separately, and because a spend limit on one must never be able to kill a run.

| Model | Access | Used for |
|---|---|---|
| **Strong reasoning model** (Claude Opus class) | Agent harness | Orchestration, primary-source verification, spec writing, the publish gate, final polish. Never the grunt work |
| **MiniMax-M3** | `api.minimax.io/v1`, OpenAI-compatible | Long-form generation, corpus synthesis, fact extraction, independent fact audit |
| **Kimi / Moonshot** (`kimi-k2.5/k2.6/k2.7-code`, `moonshot-v1-{8k,32k,128k}`) | `api.moonshot.ai/v1` | Screen-read extraction, triage, dependency proposals, description compression, humanisation critique |
| **OpenRouter** (`deepseek/deepseek-v4-flash` default, `:online` variants) | `openrouter.ai/api/v1` | Web-grounded research and drafting with URL citations; one key, many cheap models |

`scripts/ask_llm.py` is the single OpenAI-compatible CLI that fronts all three cheap providers
(`--model minimax|kimi|openrouter`, `--system`, `--file`, `--max-tokens`, `--temperature`).
Everything else shells out to it, so provider changes happen in one file.

**Cheap-model gotchas, learned the hard way and worth carrying over verbatim:**

- MiniMax-M3 burns roughly 12k tokens on hidden `<think>` reasoning. A `max_tokens` of 8-16k
  truncates the answer to near-empty with `finish_reason: length`. **Set `max_tokens` around
  40000.** Always strip `<think>...</think>`; if the content opens with an unclosed `<think>`,
  discard it as unusable.
- M3 long-note generation takes 3 to 5 minutes. Run it as a background job and be notified;
  never poll.
- `kimi-k2.6` requires `temperature=1`. `kimi-k2-0711-preview` 404s.
- For a direct critique with no reasoning blow-up, `moonshot-v1-128k` is fast and reliable.
- Assemble model context packs from on-disk files with `cat`, never by re-emitting text from
  the orchestrator's context. It saves the expensive tokens.

### 4.4 Browser automation

A managed persistent browser (`dev-browser`) driving logged-in profiles, addressed by page
name, with per-profile sessions (`inven`, `alphasense`, `substack`, `research`, `nebius`).
Scripts are injected as JavaScript files and evaluated in the page.

Hard-won operational rules:

- **Scripts are capped at 30 seconds.** Long captures must be many short passes that append to
  a shared file, not one long run.
- **Bring the page to front before running.** Background tabs freeze timers and the capture
  silently returns nothing.
- **Run captures on the research platform solo.** Two concurrent submits time out on the
  composer; more than two concurrent tabs hang the daemon.
- **Never run screenshots or a cheap-model call during a capture.** Daemon and network
  contention makes both fail.
- Use the React native value setter to fill search boxes, not simulated typing.
- Click the actual primary Search button, not an incidental sidebar control.

### 4.5 Website stack

| Tool | Version | Job |
|---|---|---|
| Next.js (App Router, Turbopack) | 16.2.9 | Framework. **Note: this version has breaking changes versus most model training data. Read `node_modules/next/dist/docs/` before writing framework code.** |
| React | 19.2.4 | UI |
| `d3-force` / `d3-zoom` / `d3-drag` / `d3-quadtree` | 3 | Graph physics and pan/zoom maths only. Drawing is manual canvas, not d3's DOM renderer |
| Zod | 4 | Runtime validation of the committed JSON at load |
| framer-motion | 12 | Animation |
| MDX (`@next/mdx`, `@mdx-js/*`) | 3 | Content pages |
| `isomorphic-dompurify` | 3 | **Security critical.** Strips scripts from remote newsletter HTML before injection |
| `posthog-js`, `@vercel/analytics` | - | Analytics, both no-op without a token |
| Vitest + jsdom + `@testing-library/react` | 4 | 206 tests over the real committed data, no mocks |

### 4.6 Services

Vercel (hosting, root directory `site/`), GitHub, Substack (newsletter, its public archive JSON
is fetched by the site), beehiiv (second newsletter channel), PostHog, IndexNow (Bing, Yandex,
Seznam, Naver - Google ignores it).

---

## 5. Build order

Build in this order. Each phase is usable on its own and each depends only on what came before.

```
0  skeleton + venv            .venv, requirements, .gitignore, house rules
1  taxonomy                   build/nodes_L*.yaml -> build.py -> taxonomy.yaml + 3 CSVs
2  dataset + gate             companies.csv schema, audit.py, chain.py
3  scraping                   keyless harvest, browser capture, evidence gathering   <-- the engine
4  judging                    gen_opp_inputs -> judge -> parse_opp -> opportunities.csv
5  knowledge loop             theses + adversarial validation + reflections
6  research engine            asks -> captures -> facts -> briefs; deep dives; autodive
7  website                    content contract JSON -> Next.js atlas
8  publishing                 Substack/beehiiv drafts, art library
9  automation                 launchd ticks, daily reports, freshness watch
```

A minimum viable version is phases 0, 1, 2, 3 and 7. Everything else is leverage on top.

---

## 6. Phase 0 - repo skeleton and environment

```
mkdir ai-compute-value-chain && cd $_ && git init
python3 -m venv .venv
.venv/bin/pip install pyyaml requests posthog python-dotenv
mkdir -p build scripts/harvest scripts/tests data/nodes knowledge/theses research agents publish site
```

**The virtualenv is mandatory.** Homebrew Python is externally managed and refuses
`pip install` into the system directory. Always call `.venv/bin/python`, never bare `python3`,
or you will get `ModuleNotFoundError: No module named 'yaml'`.

`.gitignore` must exclude, from day one:

```
.*_key            # every provider key file, at any depth
.env
site/.env*.local
site/.next
site/node_modules
__pycache__/
.venv/
data/harvest_cache/
data/harvest_staging/*.log
companies.csv.bak
```

Write `AGENTS.md` (the token-efficiency contract for agents), `METHODOLOGY.md` (how the research
is done and what has already gone wrong) and `build/SCHEMA.md` (the node schema) before writing
code. They are the specifications the code is written against, not documentation of it
afterwards.

---

## 7. Phase 1 - the taxonomy

### 7.1 Layers

Nine vertical layers plus one horizontal. Node counts are the current build.

| Code | Layer | Covers | Nodes |
|---|---|---|---|
| `L0` | Raw materials and extraction | Ore, silicon, rare earths, uranium, industrial gases | 55 |
| `L1` | Power generation | Turbines, nuclear, solar, wind, storage and their supply chains | 67 |
| `L2` | Transmission, grid, interconnection | Transformers, switchgear, HVDC, substations | 92 |
| `L3` | Data centre physical | Land, shell, cooling, UPS, fire, commissioning | 105 |
| `L4` | Compute hardware | Accelerators, memory, networking, servers, racks | 52 |
| `L5` | Semiconductor manufacturing | Litho, etch, deposition, packaging, consumables | 103 |
| `L6` | Cloud and infrastructure software | Orchestration, virtualisation, observability | 28 |
| `L7` | Models and foundation labs | Frontier and open models, training, evaluation | 21 |
| `L8` | Applications and inference | Vertical AI, agents, embedded AI (the demand side) | 17 |
| `LX` | Cross-cutting enablers | Capital, permitting, advisory, logistics, labour, standards | 40 |

The layer DAG is encoded in code (`LAYER_DAG` in `chain.py`) and drives dependency reads:
`L0 -> L1 -> L2 -> L3`, `L0 -> L5 -> L4 -> L3`, `L4/L3 -> L6 -> L7 -> L8`. `LX` serves the
whole `L1`-`L5` buildout.

### 7.2 The ID scheme

Hierarchical and stable, so the tree can be rebuilt from a flat list:

```
L5 . 2 . 3 . 2
|    |   |   +-- level 3: sub-sub-segment   "Atomic layer etch"
|    |   +------ level 2: sub-segment       "Etch equipment"
|    +---------- level 1: segment           "Front-end wafer fab equipment"
+--------------- level 0: layer root        "Semiconductor manufacturing"
```

- The `id` prefix **must** match the `layer` field; `parent_id` must be an exact existing id.
- **New nodes take the next free number. Never renumber.** Company rows, theses and public URLs
  all reference ids.

### 7.3 The node schema

Every node carries: `id`, `parent_id`, `layer`, `level`, `name`, `definition`, `role_in`,
`role_out`, `criticality` (`bottleneck` | `choke_point` | `commoditised` | `normal`),
`market_structure` (`fragmented` | `consolidated` | `oligopoly` | `near_monopoly`), `maturity`
(`legacy` | `scaling` | `emerging`), `geo`, `regulatory_exposure`, `value_capture`,
`archetypes` (ints 1-14), `upstream` / `downstream` id lists, `long_tail_niches`,
`cross_segment` + `cross_segment_tags`, and `notes`.

**`long_tail_niches` is the most valuable field in the schema.** It is where the investable
long tail is recorded without creating a node for every tiny niche - and, later, it turns out to
be the richest input to the scraper's query builder, because each entry already describes *a kind
of company*.

**Opinion lives in a separate file.** `build/ratings.yaml` adds `pe_attractiveness`,
`ai_transformation_potential`, `virtuous_cycle` and `signal_flags`. Keeping it out of the
structural files means the structure stays neutral and re-ratable.

### 7.4 The 14 archetypes

Run as a checklist against every segment - "who are all the kinds of business that make money
here?" They become the columns of `archetype-matrix.csv`.

1 owners and operators · 2 equipment and hardware OEMs · 3 EPC and developers · 4 O&M, repair,
decommissioning, spares · 5 inputs and consumables · 6 technology and software vendors ·
7 distributors, resellers, integrators · 8 capital and finance · 9 government, regulators,
policy · 10 professional and advisory services · 11 labour, trades, staffing · 12 logistics,
heavy transport, commissioning · 13 standards, certification, industry bodies · 14 research,
national labs, academia.

### 7.5 MECE discipline

Mutually Exclusive, Collectively Exhaustive: everything has exactly one home and nothing is
missing. Fix the hard cases in `SCHEMA.md` so the same thing never lives twice:

- Battery **cells** -> L0. Grid-scale **BESS** as a dispatchable asset -> L1. In-building
  **UPS** -> L3. In-rack **BBU** -> L4.
- Power semiconductors: **designed** L4, **fabricated** L5, **applied to the grid** L2.
- Neocloud: the **facility** is L3, the **platform business** is L6, cross-tagged.
- IDMs: **design** L4, **fab and packaging** L5, cross-tagged.

Genuinely cross-layer things set `cross_segment: true` and list ids in `cross_segment_tags`
rather than being duplicated. 24 nodes do this. Describe the result honestly as **near-MECE**.

### 7.6 `build/build.py`

Reads the ten `nodes_L*.yaml` files plus `ratings.yaml`, validates, and emits four root
artefacts in one pass: `taxonomy.yaml` (nested), `segments.csv` (flat), `archetype-matrix.csv`,
`signals.csv`.

Validation is the point: unique ids, resolvable parents, controlled vocabularies, archetype
numbers within 1-14, id prefix matching layer. **It exits non-zero on hard errors** so a broken
taxonomy cannot ship. Because all four outputs come from one pass, they can never drift apart.

> **Trap to design against:** the four outputs sit at the repo root as plain text and look
> editable. They are build output. This has already gone wrong once - a dependency was fixed in
> the source YAML but never rebuilt, so the committed taxonomy disagreed with its own source for
> weeks. Say so loudly in the README.

---

## 8. Phase 2 - the dataset and its gate

### 8.1 `companies.csv`

Twelve columns, flat, one row per company-node pairing (the same company may legitimately appear
under more than one node):

```
name, node_id, node_name, hq_country, size_band, ownership,
founded, website, description, source, source_url, confidence
```

Controlled vocabularies, enforced mechanically:

| Column | Allowed |
|---|---|
| `size_band` | `large` (>1000 staff), `mid` (200-1000), `small` (50-200), `SME` (<50), `startup` (early or VC-backed). Blank if genuinely undeterminable |
| `ownership` | **Leading token only is validated:** `Public`, `Private`, `PE`, `VC`, `State`, `Corporate`, `Subsidiary`, `Non-profit`. A qualifier may follow, so `Private (KKR)` and `Subsidiary (Vertiv)` are legal |
| `source` | `web`, `inven`, `alphasense` |
| `confidence` | `high`, `medium`, `low` |

> `Non-profit` exists because RTOs and ISOs (PJM, MISO, ERCOT) genuinely are non-profit and were
> being mislabelled. **The vocabulary was widened rather than the data bent.** Copy that instinct.

### 8.2 `audit.py` - the quality gate

Read-only, run before and after every append, must print PASS before any commit. It checks:

- schema integrity and column count
- controlled-vocabulary compliance (splitting `ownership` on space, `(` or `/` and validating
  only the leading token)
- exact duplicates and key duplicates (name + node)
- blank required fields
- dead or junk websites
- `node_id` values that do not exist in the taxonomy
- **fabrication risk**: low confidence with no source URL and no website
- founded-year sanity
- description hygiene

`audit_fix.py` applies only **safe deterministic** normalisations: prepend `https://` to bare
domains, extract a four-digit year from `"1990s"`, correct vocabulary casing. It never guesses a
fact.

### 8.3 `chain.py` - the canonical interface

The front door for humans and agents alike. It exists because the dataset is far too large to
read wholesale into an agent context.

```
chain.py stats                        global summary
chain.py node <nid> --json            one node: mix, opportunity, thesis, deps, value capture
chain.py companies <nid> [--own Private] [--size SME] [--limit N] [--json]
chain.py search <q> [--field name|hq|desc]
chain.py layer <L>                    rollup plus upstream layers
chain.py deps <nid>                   upstream/downstream plus value-capture read
chain.py opp [--min 4] [--angle buy-and-build]
chain.py add --node <nid> --name ...  refuses duplicates within the node
chain.py rm  --node <nid> --name ...
chain.py audit                        the gate
chain.py index                        rebuild data/index.json + data/nodes/*.json
chain.py refresh                      index + value-map + dashboard (fast)
chain.py spider                       the slow poster render only
```

It also emits the two cheap read surfaces that agents should use instead of the CSV:
`data/index.json` (one compact record per node for the whole map) and `data/nodes/<nid>.json`
(full per-node slice). Node-level dependency and value-capture overrides are hand-curated in
`data/deps.csv` and read as overrides on top of the layer DAG default.

---

## 9. Phase 3 - SCRAPING, start to end

This is the engine. It has **four independent channels** feeding one staging area behind one
gate. Build them in the order given; each is useful alone.

```
                         CHANNEL A - keyless bulk + live harvest (Python, no accounts)
                         CHANNEL B - browser screen-read capture (private DB, read-only)
                         CHANNEL C - broker/expert generative search (browser, read-only)
                         CHANNEL D - search-API evidence gathering (Brave + cheap model)
                                  |
                                  v
                       data/harvest_staging/<tag>.staging.csv     (never companies.csv)
                                  |
                          promote.py  (preview by default)
                                  |
                            audit.py PASS?  --no--> restore backup, abort
                                  | yes
                                  v
                            companies.csv
```

**The invariant that makes all of this safe: no scraper ever writes `companies.csv`.** Every
channel writes staging. Promotion is a separate, reviewed step gated on the audit.

---

### 9.1 Channel A - the keyless harvest

Nine small modules under `scripts/harvest/`, each with one job.

#### 9.1.1 `fetch.py` - the politeness core

**Nothing else in the harvest is allowed to call `urllib` directly.** Everything goes through
here, so caching and politeness cannot be bypassed by accident. Every fetch is:

- **robots-checked** - but only when a `robots.txt` actually exists. Some hosts redirect
  `/robots.txt` to an HTML documentation page, and a naive parser then reports disallow-all
  against a policy nobody wrote. So check the body for a real directive line first; no published
  policy means allowed, which is what RFC 9309 says.
- **rate-limited per host** - 1.5s default, with explicit per-host overrides where the publisher
  documents a rate. The Wikimedia REST API documents 500 requests/hour, i.e. one per 7.2s.
  *We were running at 1.5s, four times over their stated limit. They were not returning 429s,
  which is exactly why this has to be set deliberately rather than by waiting to be told off.*
- **cached on disk by URL hash** under `data/harvest_cache/` (gitignored, currently ~8,000 files)
- **identified** with a real User-Agent naming the project, the site and a contact address
- **bounded** - 20s timeout, 2 MB maximum response

#### 9.1.2 `nodes.py` - queries built from the taxonomy itself

Loads the taxonomy and builds discovery queries **only from a node's own public fields**: name,
definition, `role_in`, `role_out`, and above all `long_tail_niches`, because each entry there is
already a description of a kind of company. No hand-written query lists to maintain.

#### 9.1.3 `discover.py` - two deliberately different sources

| Source | Bias | Use |
|---|---|---|
| Wikimedia search | broad; catches private and foreign firms; **noisy** | The one-line `description` field ("American industrial rigging company") is a free company / not-company filter. Use it |
| SEC EDGAR full-text search | US public only; **zero noise** | Real, current, unambiguous names |

Neither is trusted. Both emit candidate dicts that still have to survive enrichment and node-fit
scoring. Two regex filters do the first cut: one matching words that mean "this is an operating
company" (company, manufacturer, conglomerate, supplier, contractor...), one matching words that
mean it is not (disambiguation, list of, album, village, species, protocol, software, footballer,
defunct...). A third catches titles that are structurally not company names (`List of`,
`Glossary`, `Comparison of`, `History of`, `in the United States`), because concept articles
survive a description filter - "Environmental, social, and governance" reads company-ish.

#### 9.1.4 `dbpedia.py` and `dbpedia2.py` - the bulk seam

This is the single biggest yield decision in the scraper, and the reasoning is worth repeating:

- The Wikimedia API is capped at 500 requests/hour and returns **no business metadata at all** -
  no website, no headcount, no founding year. Each of those then costs three to four more
  requests against the same budget.
- DBpedia is **the same Wikipedia content, already parsed out of the infoboxes**, served over
  SPARQL. **One request returns 1,000 complete records.** Free, no key, and `robots.txt` permits
  `/sparql` with `Crawl-delay: 10`.
- Paging 117,631 `dbo:Company` entities at 1,000 a time is about 120 requests - roughly twenty
  minutes at the published crawl delay, versus weeks through the rate-limited API.

**Pass 1 (`dbpedia.py`) sweeps by industry, not across everything.** DBpedia's company set is
dominated by industries with nothing to do with the compute chain: Airline 9,057, Financial
services 6,372, Retail 6,335, Video games 4,765. Sweeping everything and asking "which node fits
best?" forces a bookstore onto a transmission node, because *some* node is always the best of a
bad set. Restricting the query to 40 chain-relevant industries (17,457 companies) removes the
problem at source instead of filtering it afterwards.

**Pass 2 (`dbpedia2.py`) reaches what the industry sweep cannot see.** Only 54,787 of 117,631
companies set `dbo:industry` at all; 62,844 set none. Those are invisible to an industry query
but often say exactly what they do in their description ("Chinese semiconductor company",
"manufacturer of power transformers"). So pass 2 matches on **description text**, using terms
drawn from the chain itself, kept deliberately narrow - a loose term like "systems" pulls in the
whole corpus.

`bulk.py` is the same idea against Wikipedia categories: category search returns 100 per request
with offset pagination, roughly two orders of magnitude more per unit of rate budget than
node-driven search, which returns a handful and exhausts fast.

#### 9.1.5 `fit.py` - the node-fit gate, with no model

**The failure this exists to stop:** a Wikipedia search for "Uranium milling" happily returns a
mining conglomerate and a machinery firm; "Aluminium" returns a bicycle manufacturer. All are
real companies. None belong on that node. Discovery precision was about **50% without this
check**.

The test: does the company's own description share the node's *distinctive* vocabulary? Terms
are weighted by how rare they are across the whole taxonomy, so "systems" and "services" count
for nothing and "uranium" counts for a lot. A crude suffix stemmer collapses mining/mined/mines
and battery/batteries. A large stop list strips the marketing vocabulary that every company
description contains.

This is pure local computation - no API call, no key, no model. That matters: it means the
precision gate costs nothing and can run over every candidate.

#### 9.1.6 `enrich.py` and `extract.py` - candidate to full row

Sources are constrained by what `robots.txt` actually permits:

```
ALLOWED   api.wikimedia.org        (the endpoint Wikimedia publishes for programmatic use)
ALLOWED   the company's own site   (subject to its own robots.txt)
BLOCKED   wikidata.org             (/w/ and /api/ disallowed)
BLOCKED   query.wikidata.org       (/sparql disallowed)
BLOCKED   en.wikipedia.org         (/w/ and /api/ disallowed)
```

Losing Wikidata means founded / employees / ownership are no longer available as structured
statements. They are recovered from prose instead - the Wikipedia excerpt and the company's own
about page (`/about`, `/about-us`, `/company`, `/our-story`, `/history`, `/who-we-are`) - and
**every extracted value carries the sentence it came from**, so a reviewer can check it.

`extract.py` is rule-based, no LLM, no key: a small `HTMLParser` subclass that skips
script/style/svg, captures the title and meta description, and flattens text; then regexes for
country, founding year, headcount and ownership signals. **Everything returned carries the URL
it came from, so provenance is per-field rather than per-row. An empty result is a correct
answer** - pages often say nothing usable.

#### 9.1.7 `pipeline.py` - the batch runner

Walks the deficit queue (nodes with fewest companies first), discovers, enriches, fit-scores and
stages, concurrently, with a provenance sidecar recording per-field origins.

```
python3 scripts/harvest/pipeline.py --nodes 10 --per-node 8
python3 scripts/harvest/pipeline.py --node L5.8.3 --per-node 12
python3 scripts/harvest/pipeline.py --layer L3 --nodes 20
```

Deduplication runs on normalised name plus node, and on domain root plus node, against both the
existing CSV and within the new batch.

#### 9.1.8 `state.py` and `tick.py` - the 24/7 slice

**The governing constraint is a rate budget, not a machine.** Running on a bigger box does not
help; the ceiling is the source's rate limit, and every hour not spent is lost forever. A full
462-node sweep at ~30 queries per node needs ~14,000 requests, which at 500/hour is
**~28 hours of continuous running**. Running eight hours a day throws away two thirds of the
allowance. That is the entire argument for unattended operation: *spend exactly this hour's
allowance, every hour, forever.*

A CSV cannot express "this node failed twice, back off", "this node was swept 30 days ago,
re-check it", or "I have used 340 of this hour's 500 requests". So state is SQLite
(`data/harvest.db`): `node_state` (last swept, sweeps, failures, backoff gate, found, staged,
last error), `requests` (one row per outbound request, for the trailing-hour budget), and `runs`.

`tick.py` is **one bounded slice**, minutes long, fired hourly by launchd:

- take an `fcntl` lock on a lockfile so two ticks never double-spend the budget (macOS has no
  `flock(1)`, so take it from Python)
- read the remaining budget from SQLite: 500 minus used-in-trailing-hour minus a reserve
- pull the next nodes: never-swept first, then longest-stale
- scrape until the budget is spent
- append to `data/harvest_staging/auto.staging.csv`
- update per-node state, apply backoff to broken nodes so they stop eating the budget
- exit

A kill mid-tick loses one node, not the sweep. **It never writes `companies.csv`.**

**Honest yield, so nobody is surprised:** at roughly one aligned company per node, a 28-hour
sweep produces about 300 to 500 companies, then cycles to re-check the oldest nodes. Automation
makes that steady and unattended. It does not make it thousands.

#### 9.1.9 `backlog.py` - re-placing what was already captured

A subtle and high-yield idea. Earlier capture runs produced thousands of companies with full
fields, most of which a triage pass rejected at ~87%. But that triage only ever asked *"does
this belong on the ONE node this run targeted?"* - "traditional BPO, no AI-native model" is a
rejection from one node, not a judgement that the company is irrelevant to the map.

So `backlog.py` scores every backlogged company against **every** node with the same fit scorer
and places it where it actually fits. Pure local computation, no network, no key. Before
discarding any rejected pile, ask what question the rejection actually answered.

#### 9.1.10 `promote.py` - the only writer

```
python3 scripts/harvest/promote.py --tag run2                                  # preview
python3 scripts/harvest/promote.py --tag run2 --min-confidence medium --apply  # write
```

Default is a **preview**. Nothing is written without `--apply`, and `--apply` refuses to proceed
unless `audit.py` returns PASS afterwards, restoring the backup if it does not. Boilerplate
descriptions ("leading provider of solutions", "your one-stop", "world-class solutions") are
filtered. Rows without a website are held back unless `--keep-all` is passed.

---

### 9.2 Channel B - browser screen-read capture

For the private-company database. The richest seam for the private regional long tail, and the
only channel that needs a human-authenticated session.

**The posture:** read-only, screen-read only. Never export, never download, never click a
control that consumes credits. Results are read from the rendered screen.

**The mechanics**, which took real work to get right:

1. `inven_setfocus.js` sets the search text using the React native value setter (not simulated
   typing, which is slow and flaky) and clicks the correct primary Search button. It aborts
   loudly with `NOTEXTAREA` / `NOSEARCHBTN` rather than silently capturing an empty page.
2. `inven_scrollgrab.js` runs **one sub-30-second scroll pass** over the virtualised results
   table. It finds the scroller by looking for the tallest scrollable element containing company
   links, scrolls in ~80%-of-viewport steps, and appends each window's `innerText` to a shared
   JSON file. Scroll position persists between calls on the live page, so repeated passes cover
   the whole table. It stops on `ATBOTTOM` or after a stale-scroll threshold.
3. `capture_inven.sh` orchestrates: set focus once, then N scroll passes, then parse. It lives
   behind an allowlisted `bash scripts/*` interface so cheap background agents can drive the
   browser without inline-heredoc permission prompts.
4. `parse_inven_scroll_capture.py` turns the accumulated text windows into the 15-column
   candidate schema, as a real CSV writer, never string concatenation.

**Expect roughly 450 rendered rows per query. Breadth comes from unioning many queries**, sliced
by business focus, geography, ownership and size. If the tool reports "500 of 10,000+", capture
the exposed 500 and then split the universe into narrower slices. **Do not confuse
exposed-table capture with full-universe capture** - record in the run summary which one you
achieved, the result count the tool displayed, the rank range captured, and any missing rank
gaps.

Names reconstructed from URL slugs are `to_verify` until the website and legal name are
confirmed.

---

### 9.3 Channel C - broker and expert generative search

For market colour and validation rather than company enumeration. Run modes:
node validation, layer scan, dependency scan, emerging nodes.

It answers questions the company data cannot: is this node real and distinct, which upstream
constraints bind it, which downstream workloads drive demand, what lead-time / pricing / margin /
capacity figures support it, what is missing from the taxonomy, which named companies deserve
follow-up.

Then `kimi_layer_signals.py` asks a cheap model to do two things per capture: extract the four
strongest concrete datapoints with their inline broker/expert/filing attribution, **and
cross-check the datapoints currently shipped on the site, flagging any the research contradicts
or fails to support.** The strong model audits the compact JSON and integrates. This verify gate
has earned its keep - it flagged a shipped "$8-10/GB" claim as uncorroborated, which was then
replaced with broker-cited signals.

**Two traps:**

- Deep "research plan" modes attribute claims to generic labels like "Research Plan" or "Cited
  Research Answer". **Never ship those.** Audit and re-attribute to the real publisher. Focused
  asks yield proper names.
- Anchor answer extraction on **the query's own keywords**, not on a generic word like
  "Results" - that hits the sidebar thread history rather than the answer body.

---

### 9.4 Channel D - search API plus cheap-model synthesis

`research_brave.py` is the pattern that all later evidence gathering copies. Per dimension:

```
run Brave queries -> dedupe URLs -> fetch top pages (crude HTML to text)
   -> hand the corpus to a cheap model -> {capture, facts[]}
```

It writes an analyst prose capture and, separately, a list of facts in the schema the publish
gate understands:

```json
{"field": "...", "claim": "<=140 chars, includes the exact figure",
 "stat": {"value": "<exact figure string>", "label": "short label"},
 "companies": ["..."],
 "source": {"publisher": "...", "date": "YYYY-MM-DD", "url": "..."},
 "source_tier": "public", "stance": "bull|bear|neutral", "verdict": "confirmed"}
```

The system prompt is the safeguard: *"You work ONLY from the source excerpts provided. You never
invent figures, dates, URLs or quotes. If a number is not in the sources, you do not state it.
Every figure you cite must be traceable to one of the provided source URLs."*

Variants of the same rig:

- `web_teardown.py` crawls a company's own site with the managed browser as a JS-aware renderer
  and produces a product/BOM teardown from the rendered corpus.
- `gather_node_evidence.py` tops up evidence for public node pages. It builds ten short,
  specific noun-phrase queries per node **only from that node's own public fields**, searches,
  fetches, and extracts grounded per-page factual notes - never inferred, never general
  knowledge, never from any desk-internal field. A failed query yields `[]` and does not kill
  the node.
- `source_quality.py` is the safeguard nobody expects to need. Measured across the whole
  evidence pool, **17.6% of gathered sources were market-report or press-release content farms**;
  the median node drew 15% of its evidence from them and 17 nodes drew over half. That matters
  because sources are rendered as a **visible bibliography on a public page**. And the
  adversarial verify pass does not protect against it: verify asks whether a paragraph is
  supported by the cited note, not whether the note is *true*. A fabricated market-share figure
  in a farm's note produces a paragraph that verifies cleanly. **Garbage in, verified garbage
  out.** Classify and down-weight sources explicitly.

---

### 9.5 The family-agent fan-out method

When a channel needs many parallel workers, this is the pattern that proved robust:

1. A capture or recovery script produces a **per-node input file** (tab-separated name, website,
   raw snippet), split into batches of about 55 candidates.
2. Shared instruction files (`INSTRUCTIONS.md`) and per-node scope files (`SCOPES.md`) let each
   agent prompt be a **single line**: read the instructions, look up your node scope, process
   your input, write your output table.
3. Each agent verifies every candidate on the web, drops out-of-scope entries and non-companies,
   fills the fields without fabricating, and **writes a markdown table to its own output file**.
   Its chat reply is just a count.
4. **The orchestrator parses the output files, never the agent transcripts.** Agent transcripts
   are never read into the orchestrator context; they overflow it. This single rule is what makes
   large fan-outs manageable.

Parsing, dedup and append are handled by dedicated scripts (`companies_enrich.py`) so the same
logic runs identically every time.

**Detect frozen agents by stat-ing their output files' modification times**, then re-dispatch the
missing batches. Re-authenticating mid-fan-out froze 23 running agents at the same second with no
completion notification. Do not re-authenticate while a fan-out is running.

### 9.6 Name cleaning and deduplication

Database scrapes arrive garbled and doubled ("Greentek Inc. Greentek Inc"). The cleaner
de-duplicates repeated token runs, drops CJK when an ASCII name is present, and caps name length.

**The website is the reliable identity key**, not the name. Deduplication runs on normalised
name plus node *and* on domain root plus node, against both the existing CSV and the new batch,
so the same company can still legitimately appear under more than one node.

### 9.7 Evidence tiers

Every candidate row gets a maximum confidence from how it was evidenced:

| Tier | Requirement | Max confidence |
|---|---|---|
| Private DB only | Seen on the tool with basic metadata, no public verification | medium |
| Private DB + company website | Lead plus official site confirms the activity | high |
| Web only | Official site or authoritative source confirms activity | high |
| Broker/expert only | Analyst source mentions it, public verification missing | medium |
| Weak web | Directory or profile page, no canonical site confirmation | low |

And a **node fit test** every retained company must pass all four of:

1. It is a real operating business or identifiable operating unit.
2. It sells, owns, develops, finances, services or supplies the node function.
3. It is **not merely a customer** of the node's product.
4. It is not already represented by the same parent in the same node, unless the subsidiary has a
   distinct market identity.

---

## 10. Phase 4 - the judging layer

Data alone is not a view. This pass turns each populated sub-market into a PE read.

```
companies.csv + signals.csv
   -> gen_opp_inputs.py    node aggregates: company count, ownership mix, size mix,
                           HQ spread, sample target firms
   -> judging agents       JUDGE_INSTRUCTIONS.md
   -> parse_opp.py
   -> opportunities.csv + a ranked opportunities.md
```

Each node gets a **score 1 to 5**, a best-fit **angle** (`buy-and-build`, `platform`,
`carve-out`, `growth-equity`, `niche-bottleneck`, `pass`), a one-line thesis grounded in the
evidence, the single biggest risk, and two to four **named example targets drawn from the mapped
set**, never invented.

The rubric weighs fragmentation, criticality, demand tailwind, revenue stickiness, buyability and
consolidation stage.

> Current distribution: `pass` 87 · `buy-and-build` 72 · `growth-equity` 18 ·
> `niche-bottleneck` 18 · `platform` 7 · `carve-out` 1. **`pass` being the most common verdict is
> a feature.** The rubric is allowed to say no. If your rebuild never says no, the rubric is
> broken.

This layer is valuable specifically because the taxonomy's hand-written PE rating was blank for
most nodes. The judge grounds a fresh read in the companies actually found.

---

## 11. Phase 5 - the knowledge loop

The map is the substrate, not the product. The loop turns it into a view and is designed to
improve each pass.

```
0 MAP            companies.csv + signals.csv                the substrate
1 SCORE          judge every populated sub-market       ->  opportunities.csv
2 SELECT         top scores + whitespaces from prior reflections
3 DEEP-DIVE      one research agent per target develops a full thesis
4 VALIDATE       adversarial agents try to REFUTE each thesis; survivors kept with a confidence
5 REFLECT        cross-cutting learnings; new whitespaces and adjacencies to chase
6 DOCUMENT       theses/ · whitespace.md · regions.md · reflections.md
7 RE-PRIORITISE  reflections update the target list -> back to 2
```

**Step 4 is the load-bearing one.** Every thesis has a paired `<name>.validation.md` in which
adversarial agents try to kill it. Nothing is asserted until refutation has been attempted and
failed. The loop log records the failures plainly ("Consumables scout does NOT clear: TAM
overstated 3-6x"). A loop that never kills a thesis is not validating, it is rubber-stamping.

**What counts as a good target:** fragmented, critical, AI-capex-pulled sub-markets full of
buyable private firms, plus the whitespaces and adjacencies around them - an underserved
capability, a service layer missing from a hardware niche, a regional consolidation nobody has
run, or a classic physical business where applying AI creates outsized operating leverage.
**Every thesis must name the AI-transformation lever explicitly**, not just the roll-up
arithmetic.

Layout: `knowledge/theses/<nid>-<slug>.md` plus `.validation.md`, `whitespace.md`, `regions.md`,
`reflections.md`, and an append-only `loop-log.md`.

---

## 12. Phase 6 - the research engine and deep dives

### 12.1 The research engine

A read-only, resumable engine turning a manifest of asks into cited, source-verified research
packets:

```
make plan      manifest.jsonl -> plan/<id>.json   (templates; discovery for company asks)
make capture   plan/ -> captures/                 (read-only, resumable, deduped, capped)
make build     captures/ -> facts/ -> out/<id>/brief.md + facts.json + out/INDEX.md
```

`out/` is committed; everything else is gitignored. Re-running any stage is safe and resumes.
Guardrails: read-only, no exports anywhere, dedupe before the API, `max_queries` caps new
submissions, every fact passes a **grep provenance gate**, and a second cheap model
**independently audits each fact**.

### 12.2 The deep-dive pipeline

The flagship investment notes. The core idea: find a **listed company that owns an AI-compute
chokepoint and is undervalued**. A company that owns no chokepoint, or a HOLD, does not travel.

```
M0  Screen        rubric over curated chokepoints; weights ownership .4 / mispricing .4 /
                  asymmetry .2; min market cap $300m. HARD gate: scarcity_position == "owns",
                  else rejected however cheap it looks
M1  Accumulate    one pass per chokepoint over the public web -> candidate owners
M1.5 Validate     broker/expert validation of the top 5 (read-only). This pass overturned the
                  screen's own number one: a real inspection monopoly priced at a peer's
                  multiple, i.e. a value trap
M2  Evidence      cheap model extracts -> grep provenance gate -> second cheap model audits.
                  Broker/expert facts are ALWAYS source_tier="restricted"
M3  Valuation     reverse-DCF, relative value, bear/base/bull scenarios, football field,
                  probability-weighted target
M4/M5 Write-up    internal full-rigour note (all tiers) -> derived public note (publish-gated)
```

### 12.3 Two-tier provenance and the publish gate

- Every fact carries **`source_tier`** (`public` = publishable and URL-cited; `restricted` =
  broker or expert, internal only) and **`stance`** (bull / bear / neutral).
- `public_view()` filters to public tier; `check_two_sided()` flags a one-sided note, because a
  bear case is mandatory.
- **`publish_gate.py`: every `$` and `%` figure in the public draft must appear in a public-tier
  fact's claim or stat blob, or publication is blocked.** To publish a new figure you must first
  add a verified public fact with a URL.
- **Defence in depth:** after writing the public note, grep it for restricted broker names. None
  may appear.

### 12.4 Research-first discipline

Gather online, then **verify against primary sources before drafting**. On one note this caught
and killed two headline figures that the secondary coverage had garbled, plus an unsourced
multiplier claim. Token-cheap page fetching (a small model answering a prompt against the page)
is the right tool for pulling verbatim quotes and exact figures out of transcripts and filings.

### 12.5 Worldview-driven valuation

A deliberate methodological stance worth carrying over: **the house worldview must drive what
counts as undervalued.** Defaulting a target to a consensus mean-reversion multiple smuggles the
sceptic's prior in and will mechanically produce HOLDs. Instead lead with a multi-stage DCF and
put the worldview into the **demand path and duration**, not into hand-waving about the price.
Disclose the present-value step explicitly - it is material, and it is what keeps a base case
honest rather than flattering.

### 12.6 Autodive - the fully automated daily note

One scheduled command that does by machine what the deep dives do by hand, and **publishes
nothing**:

```
06:15 launchd
  1 pick          pool = listed companies x chokepoint/bottleneck nodes, minus covered subjects;
                  tickers resolved and cached; hard gates listed + market cap >= $300m;
                  rank = 2 x criticality + 3m/1m momentum
  2 marketdata    keyless market spine: price, cap, multiples, targets, revenue/EBIT/FCF history.
                  Every number becomes a sourced public fact
  3 gather        6 dimensions (mechanism, market, financials, moat, catalysts, tape) on a
                  web-grounded cheap model; every extracted figure is re-fetched from its cited
                  URL and digit-grep-verified; unverified facts demote to colour, with numbers
                  banned from the draft
  4 valuation     reverse-DCF + bear/base/bull (30/45/25), one-year PV at 9% WACC ->
                  valuation.json, the locked spine
  5 draft         pack (facts + spine + colour + voice exemplar) -> cheap model writes the
                  13-section house note; figures only from facts and spine
  6 gate          digit-tolerant publish gate, banned lexicon, no dashes, restricted-broker
                  scan, two-sided check; unverifiable figures are stripped, not softened
  7 review        review.html in the real site look, for a human
```

Publishing is a **separate pipeline**, on demand, and only ever creates drafts. Approval is a
state change on the site, never a publish.

**Safety posture:** valuation is code - the model narrates the numbers, it never chooses them or
the verdict; the suggested signal is capped and the actual call is set by a human; every note
carries the automated-draft disclosure.

---

## 13. Phase 7 - the website

### 13.1 The content contract

The site reads only static committed JSON. This is enforced by convention and restated in the
comments of nearly every `lib/` module, for one reason: *so a node page can never show a fact the
map itself disagrees with.*

| File | Written by | Contains |
|---|---|---|
| `content/network.json` | curated, committed | 580 nodes + 562 links, the graph the map draws |
| `content/criticality-v2.json` | `build_criticality_v2.py` | Per-node label, owners, why-line, signals |
| `content/network-meta.json` | `build_network_meta.py` | Per-node description + upstream dependencies |
| `content/node-depth.json` | `build_node_depth.py` | Long-form prose plus citations for the node pages |
| `content/layers.json` | `kimi_layer_signals.py` | The ten layer pages: lede, thesis, key facts, players |
| `content/story-nodes.json` | `structure_story_nodes.py` | The nodes used by the guided tours |
| `content/issues/*.body.html` | `publish/build_*.py` | Locally authored deep dives, as HTML |

`build_network_meta.py` runs in **resumable cached stages** - `harvest -> fill -> check -> desc
-> humanize -> emit` - each cached to disk, so a failure halfway does not cost the whole run.
The `humanize` stage is a deterministic AI-tell lint plus a critic loop, capped at three rounds.

`gen_node_depth.py` writes five prose blocks per node - **mechanism** (why the concentration
exists: capital intensity, qualification cycles, IP, physics or policy), **suppliers** (with
share where a source states it), **position** (what it depends on and what depends on it),
**fragility** (what would break it), **watch** (what to watch, dated). Every paragraph cites
numbered sources from that node's own evidence packet and is then **adversarially verified
against the notes of the sources it cites. Unverified paragraphs never reach the site.**

Every generator is kill-hardened: results are appended to the output file with flush and fsync
the moment each node completes, and on startup any id already present is skipped, so a relaunch
resumes rather than re-spending a paid call.

### 13.2 Routes

| Route | Rendering | What |
|---|---|---|
| `/` | Static | **The network map**, the centrepiece |
| `/stack`, `/stack/[layer]` | Static, SSG x10 | The ten layers |
| `/stack/[layer]/[node]` | SSG x121 | **The SEO centrepiece**, one page per chokepoint/bottleneck |
| `/chokepoints`, `/bottlenecks` | Static | Hubs |
| `/deepdives`, `/deepdives/[slug]` | ISR 60s | Newsletter archive, mirrored from the public archive JSON |
| `/deepdives/{named}` | Static | Locally authored premium deep dives |
| `/anatomy`, `/energy`, `/methodology`, `/collaborate` | Static | Editorial surfaces |
| `/drafts`, `/drafts/[slug]` | Dynamic, noindex | Team review of automated drafts |
| `/api/revalidate` | Dynamic | Secret-guarded cache buster |
| `/sitemap.xml`, `/robots.txt`, `/llms.txt`, `/opengraph-image` | Generated | SEO surfaces |

`dynamicParams = false` on the node route means any URL outside the enumerated list is a hard
404, never rendered on demand.

### 13.3 The map

Drawn to a **canvas, not the DOM** - 580 nodes and 562 links as SVG elements would crawl. d3
supplies force simulation and zoom maths; every pixel is painted by hand. Consequence: **you
cannot inspect a node in devtools.** Screenshot headlessly to check a change.

- **All visual difference funnels through one pure function**, `styleForNode()`, about 40 lines
  deciding fill, alpha, ring, ring width, halo and size boost. Change the look there, not in the
  render loop, so the canvas and the legend can never disagree.
- **Level of detail:** at default zoom only hubs and sublayers draw; leaf dots fade in past a
  zoom threshold. Without this the map reads as noise.
- **The roll-up ring:** chokepoints are deep leaves, invisible at overview zoom, so each one's
  ancestors are marked to say "look under here". This works because only 3 of 10 hubs contain a
  chokepoint. It is deliberately **not** applied to bottlenecks - 112 of them reach 9 of 10 hubs,
  so the mark would fire everywhere and mean nothing.
- **URL state:** active view syncs to `?view=`, selection to `?node=`, so any map state is
  linkable.

### 13.4 `lib/` - pure data shaping, no UI

Components stay dumb and the logic is unit-testable without a browser. The biggest pieces:
`node-page.ts` (assembles every node page), `issues.ts` (deep-dive registry and canonical URLs),
`node-depth.ts` (**owns the block headings so the prose files cannot drift**), `criticality-v2.ts`
(the classification plus the approved public definitions), `sanitize-html.ts` (security),
`seo.ts` (**one spelling of every URL**), `netstyle.ts` (the visual contract), `schema.ts` (Zod).

### 13.5 Theming

All colour lives in CSS custom properties, defined twice: once under `:root` for light and once
under `[data-theme="dark"]`. Cream "Blueprint" light, ink dark, copper accent.

**The canvas cannot read CSS variables directly**, so a `readColors()` helper reads them through
`getComputedStyle` at render time. Add a token to the CSS *and* to `readColors()`, or the canvas
silently falls back to a hard-coded default.

### 13.6 SEO

- One module owns canonical URLs. The apex domain redirects to `www`, so every absolute URL must
  use the `www` host; a canonical pointing at a redirect is a wasted signal.
- **Thin-content guard:** a node page whose unique text falls under 120 words ships `noindex`,
  and the sitemap reads the *same* flag, so the sitemap can never advertise a page the route
  noindexes.
- `llms.txt` is a machine-readable summary for AI crawlers, generated from live classification
  data.
- IndexNow pings Bing, Yandex, Seznam and Naver **after the deploy is live**, never at build
  time. Google ignores it.
- JSON-LD structured data per route.

### 13.7 Tests

206 tests across 24 files, **pure-function tests over the real committed data, not mocks**. If a
content JSON changes shape, the suite fails immediately. Weight tells you what is considered
fragile: the node pages (58 tests, including that titles stay unique), the prose corpus and its
citations, the hubs, every map view's visual contract, canonicals, and sitemap/noindex agreement.

---

## 14. Phase 8 - publishing and imagery

**Publishing tooling creates drafts only. It never auto-publishes and never runs on the host.**

- Substack drafts via cookie-authenticated API from issue markdown. Markers: a table marker
  becomes a monospace block, an image marker becomes a placeholder for a later upload pass,
  web-only tags are dropped but their content kept. Every draft gets a site backlink footer.
- Mirroring a site deep dive with charts: screenshot each chart block from the live page in
  document order, parse the body HTML and replace each chart with a token, convert to markdown,
  swap tokens for the chart images, fence markdown tables as code blocks (the Substack markdown
  importer cannot build tables), then create the draft with the local images.
- beehiiv is the second channel, packaged as a JSON draft package.

**Art library.** CC0 public-domain old-master art from three keyless museum APIs, for the
editorial register. `manifest.json` records source, title, artist, date, medium, credit line,
licence and the exact download URL, so **the whole library is reproducible from that one file**.
Image binaries are gitignored and regenerate from the manifest; only images actually used on the
site are committed, into the site's public folder. Themed groups: forge-industry, chokepoint,
infrastructure, cosmos, machinery, cartography, allegory, sublime.

---

## 15. Phase 9 - unattended automation

Three scheduled jobs, all launchd, all locked, none of which can publish:

| Job | Cadence | Does |
|---|---|---|
| Harvest tick | hourly | One bounded slice of the scrape, inside the rate budget, into staging |
| Autodive | daily 06:15 | Generates one reviewed draft deep dive |
| Freshness watch | daily 07:00 | Re-gates every wired issue, re-pulls live prices, attempts mechanical re-anchoring, writes one report |

The freshness watch encodes a distinction worth stealing. A stale price produces three kinds of
sentence and only one of them is a machine's job:

```
mechanical   "we accumulate at NT$266.5"        -> rewritten automatically
historical   "fell to NT$266.5 by 20 July"      -> left alone, it is still true
analytical   "every lens sits above spot"       -> ESCALATED: at the new price the claim
                                                   itself changed and needs a human to
                                                   re-underwrite
```

Nothing is applied automatically to a published fragment. The job reports; a human decides.

**Why launchd and not cron:** a run missed while the machine sleeps fires on wake. Every entry
script takes an `fcntl` lock so two runs can never overlap and double-spend an API budget.

---

## 16. Secrets and environment

Nothing secret is committed. `.gitignore` excludes `.*_key` at any depth, `.env`, and
`site/.env*.local`.

| Variable / file | Used by |
|---|---|
| `.env` (repo root) | Loaded by `ask_llm.py`; values already in the environment win, so an explicit export or a CI secret still overrides |
| `OPENROUTER_API_KEY` | Web-grounded research and drafting |
| `MINIMAX_API_KEY` / `research/engine/.minimax_key` | Long-form generation, corpus synthesis, fact audit |
| `MOONSHOT_API_KEY` / `.kimi_key` | Extraction, triage, critique |
| `BRAVE_API_KEY` / `.brave_key` | Web evidence gathering |
| `POSTHOG_PROJECT_TOKEN`, `POSTHOG_HOST` | Python CLI analytics (no-ops without a token) |
| `NEXT_PUBLIC_POSTHOG_KEY`, `NEXT_PUBLIC_POSTHOG_HOST` | Browser analytics, in `site/.env.local` and the host's env vars |
| `REVALIDATE_SECRET` | Guards the revalidate endpoint |
| `SUBSTACK_COOKIES_STRING`, `SUBSTACK_PUBLICATION_URL` | `publish/.env`, for draft creation |
| Browser profiles | Logged-in sessions for the two proprietary sources, plus substack and a general research profile |

> `NEXT_PUBLIC_` is a framework convention meaning **the value is embedded in the browser bundle
> and is publicly visible.** Never put a real secret behind it.

---

## 17. Acceptance checks per phase

| Phase | The check |
|---|---|
| 0 | `.venv/bin/python -c "import yaml, requests"` succeeds |
| 1 | `build/build.py` exits 0 and emits four artefacts; re-running produces no diff |
| 2 | `chain.py stats` reports sensible counts; `chain.py audit` prints PASS with 0 hard issues |
| 3 | `harvest/pipeline.py --node <id>` writes a staging CSV plus a provenance sidecar and **does not touch `companies.csv`**; `promote.py --tag x` previews; `--apply` refuses on a failing audit and restores the backup |
| 3 | `tick.py --status` shows the queue; two concurrent ticks cannot both take the lock; the trailing-hour request count never exceeds the budget |
| 4 | `opportunities.csv` has one scored row per populated node, and `pass` appears frequently |
| 5 | Every thesis file has a paired `.validation.md`, and the loop log records at least one thesis that did not clear |
| 6 | The publish gate blocks a draft containing a figure with no public-tier backing; a grep for restricted broker names in the public note returns nothing |
| 7 | `npx tsc --noEmit` clean, `npm test` green, `rm -rf .next && npm run build` green, a case-insensitive grep for the proprietary source names across app, components, lib, content and public returns **0** |
| 8 | Draft creation is dry-runnable and creates a draft, never a publish |
| 9 | A missed scheduled run fires on wake; a killed run resumes without re-spending a paid call |

---

## 18. Bugs already paid for - do not repeat them

| What happened | The lesson |
|---|---|
| An early cap of 14 results per node kept 227 of about 2,055 available deduplicated companies, and only 18 of 245 nodes had had a pass at all | **Never cap a long-tail capture.** Verify capture completeness against the source's own displayed result count before trusting it |
| A six-character prefix match in dedup silently dropped about 275 valid distinct companies | Prefer exact plus substring matching on normalised names and domain roots. **Review the drop list, not just the keep list** |
| Re-authenticating froze 23 in-flight background agents at the same second, with no completion notification | Detect frozen agents by stat-ing output-file modification times, then re-dispatch. Do not re-authenticate during a fan-out |
| Legacy free-text size values ("201-500", "part of Vertiv") | Normalise from headcount, then revenue, then keywords. **Leave genuinely unknown values blank** rather than guessing |
| 801 websites stored as bare domains, 110 non-numeric founded values ("?", "1990s") | Normalise deterministically. Prepend the scheme, extract an embedded four-digit year or blank it |
| RTOs and ISOs did not fit the ownership vocabulary | **Widen the vocabulary, do not bend the data** |
| A curved-header loop referenced an uninitialised variable, so every header showed the same leftover count | Initialise per-iteration values explicitly |
| Answer extraction anchored on the word "Results" hit the sidebar thread history rather than the answer body | Anchor extraction on the query's own keywords |
| Running the scraper at 1.5s between requests was 2,400/hour against a documented 500/hour limit. No 429s were returned | **Read the publisher's documented rate and honour it deliberately.** Absence of pushback is not permission |
| A triage rejecting 87% of candidates was only ever asking "does this fit the ONE node this run targeted?" | Before discarding a rejected pile, ask what question the rejection actually answered |
| `max_tokens` of 8-16k on a reasoning model returned empty content with `finish_reason: length` | Budget for hidden reasoning tokens; strip and validate the reasoning block |
| A model attributed broker claims to generic labels like "Cited Research Answer" | Never ship a generic attribution. Re-attribute to the real publisher or drop the fact |
| 17.6% of gathered sources were content farms, and the adversarial verify pass could not catch it | Verify checks support, not truth. **Classify source quality separately** |
| A source YAML was edited without rebuilding, so committed output disagreed with its own source for weeks | Make generated files obviously generated, and check for drift in CI |

---

## 19. Known gaps in the current build

- **`hq_country` is not normalised.** `USA` and `United States` are separate values, as are `UK`
  and `United Kingdom`. Any country grouping must fold these first.
- **`ownership` free-texts its qualifier.** The raw column holds hundreds of distinct strings.
  Only the leading token is validated, so always filter on the prefix, never on the whole
  string, or `ownership == "Public"` will miss most public companies.
- **Five site generators depend on an external private repo** that is not present on this
  machine. The committed JSON is complete and the site builds, but those surfaces cannot
  currently be regenerated here. Related: the site's node ids predate the current taxonomy
  numbering, so one script joins the two **by normalised name, not by id** - a fragile join that
  a rename can silently break.
- **Depth is intentionally uneven.** L0-L3 deep, L6-L8 shallow. A choice, not an oversight.
- **Criticality flags are a snapshot** of an unusually supply-constrained market. They will date.
- **Near-MECE, not perfectly MECE.** 24 nodes genuinely span layers.
- **Documentation drift.** The main README still quotes 6,571 companies; the live file now holds
  17,222 after the harvest promotions. Regenerate counts from the data rather than repeating
  them in prose, or they will drift again.
- Some pre-existing lint errors and untriaged transitive dependency advisories on the site.
- Large generated files are committed on purpose: the dataset is the deliverable.

---

## 20. Appendix - live counts and glossary

### Counts, measured from the working tree

```
taxonomy nodes            580
  choke_point             127
  bottleneck              131
  normal                  309
  commoditised             13
companies.csv          17,222 rows
  populated nodes         474
  by source               inven 11,918 · web 5,304
  by confidence           medium 12,053 · high 3,032 · low 2,137
scored sub-markets        203
```

Regenerate with `chain.py stats` rather than trusting this block.

### Glossary

| Term | Meaning |
|---|---|
| **Node** | One box in the taxonomy: a layer, segment, sub-segment or sub-sub-segment |
| **Chokepoint** | A market a handful of firms control, defended by know-how or capital, with no route around it. If it stalls, the buildout stalls |
| **Bottleneck** | Supply strains here, but ownership is too spread out for anyone to durably set prices |
| **Commoditised** | Scored; several suppliers compete; nothing to squeeze |
| **Archetype** | One of 14 participant types checked against every segment |
| **Long tail** | The unglamorous sourceable niches - spares, refurb, O&M, consumables, testing, permitting. Where much of the investable opportunity hides |
| **MECE** | Mutually Exclusive, Collectively Exhaustive |
| **Virtuous cycle** | A node that both supplies the AI buildout and is itself an AI-transformation target |
| **Buy-and-build** | Acquiring many small firms in a fragmented market to build one larger one. The most common non-`pass` angle |
| **Thesis** | A deep argument for one node, always paired with an adversarial validation file |
| **Fit score** | The model-free test of whether a discovered company shares a node's distinctive vocabulary |
| **Staging** | The area every scraper writes to. Only the promote step, gated on the audit, writes the dataset |
| **Source tier** | `public` (URL-cited, publishable) or `restricted` (broker or expert, internal only) |
| **Neocloud** | A newer GPU-focused cloud provider. Facility L3, platform business L6 |
| **IDM** | Integrated Device Manufacturer. Design L4, fab and packaging L5 |
| **LOD** | Level of detail - hiding fine graph detail until you zoom in |
