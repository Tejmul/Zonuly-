#!/usr/bin/env python
"""JobHunter CLI.

    python scripts/run.py doctor         # check Ollama, Gmail, tokens, DB
    python scripts/run.py profile        # parse resume -> profile.json
    python scripts/run.py scrape         # run the scraper fleet
    python scripts/run.py score          # embed + rubric-score
    python scripts/run.py find-contacts  # discover contacts at high-match companies
    python scripts/run.py draft          # queue referral drafts for review
    python scripts/run.py gmail-auth     # one-time OAuth consent
    python scripts/run.py send           # send approved drafts (respects cap + window)
    python scripts/run.py poll           # check Gmail for replies
    python scripts/run.py daily          # the whole ingestion cycle
    python scripts/run.py serve          # FastAPI + scheduler on :8000

    python scripts/run.py kg build       # (re)build the knowledge graph: context + data + brief + viewer
    python scripts/run.py kg search "warmth"          # full-text search across data + context
    python scripts/run.py kg show feature:warmth-tiers
    python scripts/run.py kg path contact:3 constraint:send-cap-25
    python scripts/run.py kg compose "..."            # best feature per stage for a problem statement
    python scripts/run.py kg note "what changed" --about gap:1-send-ledger
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

app = typer.Typer(add_completion=False, help="JobHunter — AI job scraping & referral outreach")


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)


def _echo(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


@app.command()
def doctor() -> None:
    """Check every external dependency and report what's missing."""
    _setup_logging()
    from jobhunter import CONFIG, ROOT, llm, matcher
    from jobhunter.contacts import hunter
    from jobhunter.db import init_db
    from jobhunter.outreach import gmail

    init_db()
    health = llm.health()
    profile_path = ROOT / CONFIG["profile_path"]
    gh_token = bool((CONFIG.get("contacts") or {}).get("github_token"))

    checks = [
        ("Ollama reachable", health["ok"], f"run `ollama serve` ({llm.BASE_URL})"),
        ("Chat model pulled", health.get("model_present"), f"run `ollama pull {llm.MODEL}`"),
        ("Embedding model pulled", health.get("embed_present"), f"run `ollama pull {llm.EMBED_MODEL}`"),
        ("Resume parsed", profile_path.exists(), "run `python scripts/run.py profile`"),
        ("GitHub token", gh_token, "optional: set contacts.github_token (60/hr -> 5000/hr)"),
        ("Hunter.io key", hunter.available(), "optional: set contacts.hunter_api_key (25 lookups/mo)"),
        ("Gmail client JSON", gmail.configured(), gmail.status()["hint"]),
        ("Gmail authorized", gmail.authorized(), "run `python scripts/run.py gmail-auth`"),
    ]
    for name, ok, hint in checks:
        mark = "OK  " if ok else "MISS"
        typer.echo(f"[{mark}] {name}" + ("" if ok else f"  ->  {hint}"))

    typer.echo("")
    _echo(matcher.counts())


@app.command()
def profile(path: str = typer.Option(None, help="Path to resume PDF/MD/TXT")) -> None:
    """Parse the resume into profile.json."""
    _setup_logging()
    from jobhunter import resume

    data = resume.build_profile(Path(path) if path else None)
    _echo({k: v for k, v in data.items() if not k.startswith("_")})


@app.command()
def scrape(
    sources: str = typer.Option(None, help="Comma-separated subset, e.g. 'greenhouse,hn_hiring'"),
    verbose: bool = False,
) -> None:
    """Run the scraper fleet and persist new jobs."""
    _setup_logging(verbose)
    from jobhunter import pipeline

    names = [s.strip() for s in sources.split(",")] if sources else None
    _echo(pipeline.scrape(names).as_dict())


@app.command()
def score(
    limit: int = typer.Option(40, help="How many jobs to rubric-score this run"),
    salaries: int = typer.Option(0, help="Also run the LLM salary backfill on N jobs"),
    verbose: bool = False,
) -> None:
    """Embed unscored jobs, then rubric-score the most promising."""
    _setup_logging(verbose)
    from jobhunter import matcher, notify, pipeline

    if salaries:
        typer.echo(f"salary backfill: {pipeline.extract_salaries(limit=salaries)} resolved")
    typer.echo(f"threshold: {matcher.prefilter_threshold()}")
    typer.echo(f"embedded: {matcher.prefilter(limit=2000)}")
    result = matcher.score_pending(limit=limit)
    notify.notify_high_matches()
    _echo(result)


@app.command(name="find-contacts")
def find_contacts(
    company: int = typer.Option(None, help="Company id; omit to sweep high-match companies"),
    limit: int = typer.Option(5, help="How many companies to process"),
    verbose: bool = False,
) -> None:
    """Discover contactable people at high-match companies."""
    _setup_logging(verbose)
    from jobhunter import contacts

    _echo(contacts.discover(company) if company else contacts.discover_for_high_matches(limit=limit))


@app.command()
def draft(
    contact: int = typer.Option(None, help="Contact id; omit to draft for high-match companies"),
    job: int = typer.Option(None, help="Job id to reference"),
    limit: int = typer.Option(5, help="How many drafts to queue"),
    per_company: int = typer.Option(2, help="Max contacts per company"),
    verbose: bool = False,
) -> None:
    """Queue referral drafts in the review queue."""
    _setup_logging(verbose)
    from jobhunter.outreach import drafter

    if contact:
        _echo(drafter.draft_for(contact, job))
    else:
        _echo(drafter.draft_for_high_matches(limit=limit, per_company=per_company))


@app.command(name="gmail-auth")
def gmail_auth() -> None:
    """Run the one-time Gmail OAuth consent flow (opens a browser)."""
    _setup_logging()
    from jobhunter.outreach import gmail

    try:
        _echo(gmail.authorize())
    except gmail.GmailNotConfigured as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(1) from e


@app.command()
def send(
    email_id: int = typer.Option(None, help="Send one specific email"),
    limit: int = typer.Option(None, help="Max to send this run"),
    ignore_window: bool = typer.Option(False, help="Send outside the configured hours"),
    no_stagger: bool = typer.Option(False, help="Skip the delay between sends (testing only)"),
) -> None:
    """Send approved drafts, respecting the daily cap and send window."""
    _setup_logging()
    from jobhunter.outreach import sender

    typer.echo(json.dumps(sender.quota(), indent=2, default=str))
    if email_id:
        _echo(sender.send_email(email_id, ignore_window=ignore_window))
    else:
        _echo(sender.send_approved(limit=limit, ignore_window=ignore_window, stagger=not no_stagger))


@app.command()
def approve(email_id: int) -> None:
    """Approve a draft from the CLI (the dashboard is the usual place)."""
    _setup_logging()
    from jobhunter.outreach import sender

    _echo(sender.approve(email_id))


@app.command()
def poll(followups: bool = typer.Option(True, help="Also queue follow-ups for silent threads")) -> None:
    """Poll Gmail for replies and classify them."""
    _setup_logging()
    from jobhunter import notify
    from jobhunter.outreach import drafter, tracker

    _echo(tracker.poll())
    if followups:
        _echo(drafter.queue_followups())
    notify.notify_replies()


@app.command()
def daily() -> None:
    """Run the full ingestion cycle once: scrape -> salaries -> embed -> score -> notify."""
    _setup_logging()
    from jobhunter import scheduler

    _echo(scheduler.daily_cycle())


@app.command()
def discover(limit: int = typer.Option(60, help="How many YC companies to probe")) -> None:
    """Probe for new public ATS boards and append them to companies.yaml."""
    _setup_logging()
    import asyncio

    import yaml

    from jobhunter import ROOT
    from jobhunter.pipeline import load_companies
    from jobhunter.scrapers.base import make_client
    from jobhunter.scrapers.yc import discover_companies

    async def go():
        async with make_client() as http:
            return await discover_companies(http, limit=limit)

    found = asyncio.run(go())
    existing = load_companies()
    known = {(c.get("ats"), c.get("ats_slug")) for c in existing}
    fresh = [c for c in found if (c["ats"], c["ats_slug"]) not in known]

    for c in fresh:
        website = c.get("website") or ""
        existing.append(
            {
                "name": c["name"],
                "website": website,
                "domain": website.split("//")[-1].split("/")[0].removeprefix("www.") or None,
                "ats": c["ats"],
                "ats_slug": c["ats_slug"],
                "tags": ["yc", "discovered"],
            }
        )

    path = ROOT / "companies.yaml"
    path.write_text(
        yaml.safe_dump({"companies": existing}, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    _echo({"added": len(fresh), "total": len(existing), "new": [c["name"] for c in fresh]})


@app.command()
def serve(
    host: str = typer.Option(None),
    port: int = typer.Option(None),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (disables the scheduler)"),
) -> None:
    """Start the FastAPI backend and the scheduler."""
    _setup_logging()
    from jobhunter import CONFIG
    from jobhunter.api import serve as _serve

    api = CONFIG.get("api") or {}
    typer.echo(f"API on http://{host or api.get('host', '127.0.0.1')}:{port or api.get('port', 8000)}")
    typer.echo("Docs at /docs   |   Dashboard: cd dashboard && npm run dev")
    _serve(host=host, port=port, reload=reload)


# ---------------------------------------------------------------- knowledge graph

kg_app = typer.Typer(add_completion=False, help="Knowledge graph — pipeline data + project context, one queryable store")
app.add_typer(kg_app, name="kg")


@kg_app.command("build")
def kg_build(no_viewer: bool = typer.Option(False, help="Skip writing knowledge/graph.html")) -> None:
    """Load knowledge/context.yaml, mirror every table, write BRIEF.md and the HTML viewer."""
    _setup_logging()
    from jobhunter.kg import analyze, brief, context, export, sync
    from jobhunter.kg.store import Graph

    with Graph() as g:
        ctx = context.load(g)
    out = {"context": ctx, "data": sync.sync_all(), "brief": brief.write()}
    if not no_viewer:
        out["viewer"] = export.write_html()
        out["graphml"] = analyze.write_graphml()
    with Graph() as g:
        out["stats"] = g.stats()
    _echo(out)


@kg_app.command("sync")
def kg_sync() -> None:
    """Mirror the pipeline tables into the data layer (runs automatically after each cycle)."""
    _setup_logging()
    from jobhunter.kg import sync

    _echo(sync.sync_all())


@kg_app.command("context")
def kg_context() -> None:
    """Reload only the context layer from knowledge/context.yaml (session notes are kept)."""
    _setup_logging()
    from jobhunter.kg import context
    from jobhunter.kg.store import Graph

    with Graph() as g:
        _echo(context.load(g))


@kg_app.command("brief")
def kg_brief(print_: bool = typer.Option(False, "--print", help="Print instead of writing the file")) -> None:
    """Render knowledge/BRIEF.md — the context handoff a fresh session reads first."""
    from jobhunter.kg import brief

    typer.echo(brief.render() if print_ else brief.write())


@kg_app.command("stats")
def kg_stats() -> None:
    from jobhunter.kg.store import Graph

    with Graph() as g:
        _echo(g.stats())


@kg_app.command("search")
def kg_search(
    query: str,
    kind: str = typer.Option(None, help="Comma-separated kinds, e.g. feature,decision or job,contact"),
    limit: int = 15,
    any_: bool = typer.Option(False, "--any", help="Match any term instead of all"),
) -> None:
    """Full-text search across both layers."""
    from jobhunter.kg.store import Graph

    kinds = [k.strip() for k in kind.split(",")] if kind else None
    with Graph() as g:
        hits = g.search(query, kinds=kinds, limit=limit, mode="or" if any_ else "and")
    for n in hits:
        status = n["props"].get("status")
        tag = f" [{status}]" if status else ""
        typer.echo(f"{n['id']:<48}{tag} {n['label']}")
        if n.get("summary"):
            typer.echo(f"    {n['summary'][:160]}")
    if not hits:
        typer.echo("no matches")


@kg_app.command("show")
def kg_show(node_id: str, depth: int = 1, json_: bool = typer.Option(False, "--json")) -> None:
    """A node, its properties and everything it links to."""
    from jobhunter.kg.store import Graph

    with Graph() as g:
        node = g.get(node_id)
        if node is None:
            hits = g.search(node_id, limit=5, mode="or")
            typer.secho(f"no node '{node_id}'", fg=typer.colors.RED)
            for h in hits:
                typer.echo(f"  did you mean {h['id']}  {h['label']}")
            raise typer.Exit(1)
        hood = g.neighbors(node_id, depth=depth)
    if json_:
        _echo({"node": node, **hood})
        return
    typer.secho(f"{node['id']}  ({node['kind']}, {node['layer']})", bold=True)
    typer.echo(node["label"])
    if node.get("summary"):
        typer.echo(f"\n{node['summary']}")
    props = {k: v for k, v in node["props"].items() if v not in (None, "", [], {})}
    if props:
        typer.echo("")
        for k, v in props.items():
            typer.echo(f"  {k}: {json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (list, dict)) else v}")
    labels = {n["id"]: n["label"] for n in hood["nodes"]}
    outs = [e for e in hood["edges"] if e["src"] == node_id]
    ins = [e for e in hood["edges"] if e["dst"] == node_id]
    if outs:
        typer.echo("\n→ outgoing")
        for e in sorted(outs, key=lambda e: (e["rel"], e["dst"])):
            typer.echo(f"  {e['rel']:<16} {e['dst']:<44} {labels.get(e['dst'], '')[:70]}")
    if ins:
        typer.echo("\n← incoming")
        for e in sorted(ins, key=lambda e: (e["rel"], e["src"])):
            typer.echo(f"  {e['rel']:<16} {e['src']:<44} {labels.get(e['src'], '')[:70]}")


@kg_app.command("path")
def kg_path(a: str, b: str, max_depth: int = 6) -> None:
    """Shortest path between two nodes — e.g. how a contact connects to a constraint."""
    from jobhunter.kg.store import Graph

    with Graph() as g:
        steps = g.path(a, b, max_depth=max_depth)
    if not steps:
        typer.echo(f"no path within {max_depth} hops")
        raise typer.Exit(1)
    for step in steps:
        if "edge" in step:
            e = step["edge"]
            typer.echo(f"    --{e['rel']}-->")
        else:
            typer.echo(f"{step['id']}  {step['label'][:80]}")


@kg_app.command("note")
def kg_note(
    text: str,
    about: list[str] = typer.Option(None, "--about", "-a", help="Node ids this note is about (repeatable)"),
    tag: list[str] = typer.Option(None, "--tag", "-t"),
    title: str = typer.Option(None, help="Short title; defaults to the first line of the text"),
    brief: bool = typer.Option(True, help="Regenerate BRIEF.md afterwards"),
) -> None:
    """Remember something — a decision, a result, what changed. This is how context accumulates."""
    from jobhunter.kg import brief as brief_mod
    from jobhunter.kg.store import Graph

    with Graph() as g:
        result = g.remember(text, about=about or [], tags=tag or [], title=title)
    if result["missing_targets"]:
        typer.secho(f"unknown --about ids (note saved without them): {result['missing_targets']}", fg=typer.colors.YELLOW)
    if brief:
        result["brief"] = brief_mod.write()
    _echo(result)


@kg_app.command("compose")
def kg_compose(
    statement: str = typer.Argument(None, help="Problem statement; defaults to the problem node"),
    for_: list[str] = typer.Option(None, "--for", help="Constraint/guarantee ids that matter (repeatable)"),
    top: int = typer.Option(2, help="Picks per stage"),
    include_dropped: bool = False,
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Pick the best feature per stage across every architecture draft for a problem statement."""
    from jobhunter.kg import compose

    result = compose.compose(statement, constraints=for_ or None, top=top, include_dropped=include_dropped)
    if json_:
        _echo(result)
        return
    typer.secho(f"statement: {result['statement'][:200].strip()}…", dim=True)
    typer.secho(f"constraints: {result['constraints']}", dim=True)
    typer.echo(f"weights: {result['weights']}   features considered: {result['features_considered']}\n")
    for st in result["stages"]:
        typer.secho(st["label"], bold=True)
        for p in st["picks"]:
            b = p["breakdown"]
            typer.echo(
                f"  {p['score']:.2f}  [{p['status']}] {p['label']}"
                f"\n         rel {b['relevance']:.2f} · fit {b['fit']:.2f} · status {b['status']:.2f} · consensus {b['consensus']:.2f}"
                f"   from: {', '.join(x.split(' — ')[0] for x in p['proposed_by']) or '(build)'}"
            )
            if p["serves"]:
                typer.echo(f"         serves: {', '.join(p['serves'])}")
        if st["also_considered"]:
            typer.echo("  also: " + ", ".join(f"{a['id'].split(':',1)[1]} ({a['score']:.2f})" for a in st["also_considered"][:6]))
        typer.echo("")


@kg_app.command("hubs")
def kg_hubs(
    layer: str = typer.Option("context", help="context | data | all"),
    kind: str = typer.Option(None, help="Comma-separated kinds to keep"),
    top: int = 15,
) -> None:
    """Most load-bearing nodes by betweenness centrality (NetworkX)."""
    from jobhunter.kg import analyze

    kinds = [k.strip() for k in kind.split(",")] if kind else None
    rows = analyze.hubs(layer=None if layer == "all" else layer, kinds=kinds, top=top)
    typer.echo(f"{'betweenness':>11} {'deg':>4}  id")
    for r in rows:
        typer.echo(f"{r['betweenness']:>11.4f} {r['degree']:>4}  {r['id']:<44} {r['label'][:60]}")
    orphans = analyze.orphans(layer=None if layer == "all" else layer)
    if orphans:
        typer.secho(f"\n{len(orphans)} unlinked node(s): " + ", ".join(o["id"] for o in orphans[:10]), fg=typer.colors.YELLOW)


@kg_app.command("export")
def kg_export(
    all_jobs: bool = typer.Option(False, help="Include unscored jobs (default: scored only)"),
    fmt: str = typer.Option("html", help="html | json | graphml"),
    out: str = typer.Option(None, help="Output path"),
) -> None:
    """Write the graph as a standalone HTML viewer, JSON, or GraphML."""
    from jobhunter.kg import analyze, export

    if fmt == "json":
        typer.echo(export.write_json(out or export.JSON_PATH, include_all_jobs=all_jobs))
    elif fmt == "graphml":
        typer.echo(analyze.write_graphml(out or analyze.GRAPHML_PATH, include_all_jobs=all_jobs))
    else:
        typer.echo(export.write_html(out or export.HTML_PATH, include_all_jobs=all_jobs))


if __name__ == "__main__":
    app()
