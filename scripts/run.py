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


if __name__ == "__main__":
    app()
