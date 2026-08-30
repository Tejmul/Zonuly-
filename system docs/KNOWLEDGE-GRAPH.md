# ZoNuLy — Knowledge Graph

> **Status: [BUILT]** 2026-08-30. Code in `jobhunter/kg/`, seed in `knowledge/context.yaml`,
> output in `knowledge/BRIEF.md`. Settled as **D10** in the decision log.

## 1. Why it exists

Two problems, one store.

1. **Context was being lost.** The project has six architecture documents that disagree with
   each other, a reconciliation document, a config file full of hard-won constants, and a
   database. Every new session — a person after a week away, or a model in a fresh window —
   had to re-read all of it to know *why* qwen3:4b, *why* no SMTP probe, *what* is still a gap.
   That re-derivation is expensive and lossy.
2. **The data was relational but the questions were graph-shaped.** "Which of my high-match
   companies has a verified contact I haven't drafted for?" "How does this contact connect to
   the 25/day constraint?" "Which feature did three drafts independently propose that we never
   built?" — these are path and neighbourhood queries, not joins.

The knowledge graph answers both by putting the pipeline's **data** and the project's
**context** in one node/edge store, with edges that cross between them.

## 2. Shape

```
                      CONTEXT LAYER (from knowledge/context.yaml)
   problem ──PART_OF── subproblems
   arch ──PROPOSES──► feature ──AT_STAGE──► stage ──THEN──► stage
                      feature ──SERVES──► constraint | guarantee
                      feature ──IMPLEMENTED_IN──► module ──DEPENDS_ON──► module
   decision ──ADOPTS / REJECTS──► feature        decision ──RECORDED_IN──► arch
   gap ──WOULD_BUILD──► feature   gap ──PROTECTS──► guarantee
   failure ──MITIGATED_BY──► feature
   question ──ABOUT──► anything   note ──ABOUT──► anything
   source ──PART_OF──► feature    source ──AT_STAGE──► stage:scrape

                      BRIDGES (data ↔ context)
   job ──SOURCED_FROM──► source            channel ──PROVIDED_BY──► feature

                      DATA LAYER (synced from the tables)
   profile:me ──HAS_SKILL──► skill
   profile:me ──HIGH_MATCH──► job ──POSTED_BY──► company ──USES_ATS──► ats
   contact ──WORKS_AT──► company     contact ──FOUND_VIA──► channel
   email ──SENT_TO──► contact   email ──ABOUT_JOB──► job   email ──TARGETS──► company
   email ──FOLLOWS_UP──► email  reply ──REPLIES_TO──► email
```

Because of the bridges, a path exists from a real person in the database to the design
decision that found them:

```
contact:1 --FOUND_VIA--> channel:github --PROVIDED_BY--> feature:github-commit-mining
          --SERVES--> guarantee:confidence-labels <--SERVES-- feature:three-confidence-tiers
          --SERVES--> constraint:send-cap-25
```

## 3. Storage — D10

Three tables inside `jobhunter.db`, next to the six pipeline tables:

| Table | Holds |
|---|---|
| `kg_node` | `id` (`kind:slug`), `kind`, `label`, `summary`, `props` (JSON), `layer` (`data` \| `context`), `ref_table`/`ref_id` back to the mirrored row |
| `kg_edge` | `(src, rel, dst)` primary key, `props` JSON, `layer` |
| `kg_fts` | FTS5 index over label + summary + a flattened body — porter-stemmed full-text search |

**Why not a graph database.** Same reasoning as D9 (no `sqlite-vec`): Neo4j needs a daemon
the 8 GB machine can't spare; Kùzu — the obvious embedded choice — was archived in late 2025;
the LLM-memory frameworks (Graphiti, Cognee, mem0) want a server-class backend and a model in
the loop. At a few thousand nodes a BFS over an indexed edge table is instant, and keeping the
graph in the one file that already gets backed up is worth more than Cypher.

**NetworkX** is the open-source graph engine on top: `analyze.to_networkx()` loads the whole
graph into a `MultiDiGraph` for centrality (`kg hubs`), community detection, and GraphML export
for Gephi / yEd / Obsidian.

## 4. Node kinds

| Layer | Kind | One per | Notes |
|---|---|---|---|
| context | `problem` | the brief + 4 sub-problems | from IDEA.md |
| context | `arch` | architecture document (7) | `file`, `date`, `stance` props |
| context | `feature` | idea any draft proposed (73) | `status`: built \| partial \| gap \| open \| dropped |
| context | `decision` | D1–D10 | adopts / rejects features |
| context | `constraint` | chosen limit (9) | 25/day, human review, local-only, 8 GB, free tier … |
| context | `guarantee` | product promise (7) | human gate, no fabrication, confidence labels … |
| context | `stage` | pipeline stage (13) | `order` prop; `THEN` chains them |
| context | `module` | code module (15) | `path`, `layer_order`; `DEPENDS_ON` encodes the layering rule |
| context | `source` | job source (10) | id matches `Job.source`; bridges to jobs |
| context | `gap` | known gap in build order (9) | `priority` prop |
| context | `failure` | failure mode (7) | `likelihood` prop |
| context | `question` | open question (5) | |
| context | `note` | dated session note | written by `kg note`; the session memory |
| data | `profile` | the candidate (`profile:me`) | from profile.json |
| data | `skill` | resume skill (38) | |
| data | `company` / `job` / `contact` / `email` / `reply` | one per row | `ref_table`/`ref_id` |
| data | `ats` / `channel` | Greenhouse/Lever/Ashby; github/site/pattern/hunter | |

## 5. Commands

```
python scripts/run.py kg build                 # context.yaml → graph, tables → graph, BRIEF.md, graph.html, graph.graphml
python scripts/run.py kg sync                  # data layer only (runs after every scheduler cycle automatically)
python scripts/run.py kg context               # context layer only — after editing context.yaml
python scripts/run.py kg brief [--print]       # regenerate knowledge/BRIEF.md
python scripts/run.py kg stats

python scripts/run.py kg search "warmth" [--kind feature,gap] [--any]
python scripts/run.py kg show feature:warmth-tiers [--depth 2] [--json]
python scripts/run.py kg path contact:1 constraint:send-cap-25
python scripts/run.py kg hubs [--layer context|data|all] [--kind ...]
python scripts/run.py kg compose "problem statement" [--for constraint:x --for guarantee:y] [--top 2]
python scripts/run.py kg note "what changed" --about gap:1-send-ledger --tag build
python scripts/run.py kg export --fmt html|json|graphml [--all-jobs]
```

HTTP, when `serve` is running:

| Route | |
|---|---|
| `GET /api/kg/stats` | counts by kind / relation / layer |
| `GET /api/kg/search?q=&kind=&any=` | full-text search |
| `GET /api/kg/nodes/{id}?depth=` | node + neighbourhood |
| `GET /api/kg/path?a=&b=` | shortest path |
| `GET /api/kg/graph?layer=&all_jobs=` | whole graph for a viewer |
| `GET /api/kg/hubs` | centrality |
| `GET /api/kg/brief` | BRIEF.md as text |
| `POST /api/kg/compose` | `{statement, constraints, top}` |
| `POST /api/kg/notes` | `{text, about[], tags[]}` |
| `POST /api/kg/build` | background rebuild, returns `task_id` |

## 6. `compose` — the architecture-graph operation

The reason the context layer records *every* proposal, including the dropped ones, is so
that this question can be asked mechanically: *for this problem statement, what is the best
feature at each stage across all the drafts?*

Each non-dropped feature is scored:

| Term | Weight | Source |
|---|---|---|
| relevance | 0.40 | bm25 of the statement against the feature's text, OR-joined, normalised to the best hit |
| fit | 0.30 | share of the named constraints/guarantees the feature `SERVES` (all of them if none named) |
| status | 0.20 | built 1.0 · partial 0.85 · gap 0.75 · open 0.5 — evidence beats intention |
| consensus | 0.10 | how many drafts independently `PROPOSES` it, normalised |

Features are grouped by `AT_STAGE`, the top N per stage are returned with the breakdown and
the drafts they came from. It is deliberately deterministic — the same reasoning as D4: a
ten-line policy over data the graph already holds beats a model call.

A worked example (`kg compose "stop bounced emails damaging Gmail, nothing fabricated"
--for constraint:send-cap-25 --for guarantee:no-fabrication`) surfaces, per stage:
guessed-send cap (gap), draft expiry (gap), the cheap fabrication validator (gap),
skip-don't-guess (built), honest-hook research (built) — i.e. GAP-4 and GAP-2, which is
what FINAL-PLAN's build order says by hand.

## 7. Keeping it true

- **A feature moved from gap to built** → edit its `status:` in `knowledge/context.yaml`, run
  `kg context` (or `kg build`). The gap node's `WOULD_BUILD` edge now points at a built feature
  and BRIEF.md shows it.
- **A decision changed** → edit/add a `decisions:` entry; never delete history, add a note.
- **Something happened worth remembering** → `kg note "…" --about <ids>`. Notes are the only
  context nodes the CLI writes; `kg context` preserves them.
- **Tables changed** → `kg sync` (automatic after each scheduler cycle). Rows deleted upstream
  are pruned from the graph.
- **Dangling links** in the YAML are reported by `kg build` (`"dangling": [...]`); orphan nodes
  by `kg hubs`.

## 8. Files

```
jobhunter/kg/
  store.py      Graph — schema, upsert, neighbors, path, search, remember, stats
  context.py    context.yaml → context layer (SECTIONS, LINKS)
  sync.py       tables + profile.json → data layer (reads all rows first: one writer at a time)
  compose.py    best feature per stage for a problem statement
  brief.py      graph → knowledge/BRIEF.md
  analyze.py    NetworkX — hubs, orphans, communities, GraphML
  export.py     JSON + standalone HTML viewer (d3 force layout)
knowledge/
  context.yaml  the seed — edit this
  BRIEF.md      generated handoff — read this first
  graph.html    generated viewer
  graph.graphml generated, for Gephi etc.
```

## 9. Known limits

- The FTS body for jobs excludes descriptions on purpose (7 MB of text; search titles, reasons
  and gaps instead). Use `/api/jobs?q=` for description search.
- `compose` relevance is lexical. It ranks well when the statement uses the project's own
  vocabulary and poorly otherwise; the `--for` constraints are the reliable lever.
- One writer at a time: `sync` reads every table before opening the graph transaction, because
  a SQLAlchemy reader held open across the graph write deadlocks SQLite ("database is locked").
- Session notes are not versioned in git unless BRIEF.md is committed — commit it.
