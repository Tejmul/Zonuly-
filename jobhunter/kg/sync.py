"""Project the pipeline's tables into the graph's data layer.

Mirrors, not copies: each node keeps a `ref_table`/`ref_id` back to its row and only
carries what is useful to search or traverse (no job descriptions, no email bodies).
Edges follow the funnel:

    profile:me -HIGH_MATCH-> job -POSTED_BY-> company <-WORKS_AT- contact <-SENT_TO- email <-REPLIES_TO- reply
    job -SOURCED_FROM-> source        company -USES_ATS-> ats        contact -FOUND_VIA-> channel
    email -ABOUT_JOB-> job            email -FOLLOWS_UP-> email      profile:me -HAS_SKILL-> skill

Idempotent — re-running upserts and prunes rows that vanished upstream.
"""

from __future__ import annotations

import json
import logging

from sqlmodel import select

from jobhunter import CONFIG, ROOT
from jobhunter.db import Company, Contact, Email, Job, Reply, get_session, init_db
from jobhunter.kg.store import Graph, slugify

log = logging.getLogger(__name__)

PROFILE_ID = "profile:me"

# Contact.source -> the context feature that produced it. This is the bridge between the
# data layer and the context layer: "who found this person" resolves to a design decision.
CHANNEL_FEATURE = {
    "github": "feature:github-commit-mining",
    "site": "feature:team-page-scrape",
    "pattern": "feature:email-pattern-inference",
    "hunter": "feature:hunter-free-tier-for-patterns",
}


def _loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _iso(dt) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def sync_companies(g: Graph, companies: list[Company]) -> int:
    keep: set[str] = set()
    ats_seen: set[str] = set()
    for c in companies:
        nid = f"company:{c.id}"
        keep.add(nid)
        g.upsert_node(
            nid, "company", c.name,
            summary=c.notes,
            props={
                "website": c.website, "domain": c.domain, "github_org": c.github_org,
                "ats": c.ats, "ats_slug": c.ats_slug, "email_pattern": c.email_pattern,
                "contacts_found_at": _iso(c.contacts_found_at),
            },
            layer="data", ref_table="company", ref_id=c.id,
            body=" ".join(filter(None, [c.name, c.domain, c.github_org, c.ats, c.notes])),
        )
        if c.ats:
            aid = f"ats:{c.ats}"
            if aid not in ats_seen:
                g.upsert_node(aid, "ats", c.ats, props={}, layer="data")
                ats_seen.add(aid)
            g.upsert_edge(nid, "USES_ATS", aid, layer="data")
    g.prune("company", keep)
    return len(keep)


def sync_jobs(g: Graph, jobs: list[Job]) -> int:
    keep: set[str] = set()
    sources_seen: set[str] = set()
    for j in jobs:
        nid = f"job:{j.id}"
        keep.add(nid)
        parsed = _loads(j.match_reasons, {})
        reasons = parsed.get("reasons", []) if isinstance(parsed, dict) else []
        verdict = parsed.get("verdict") if isinstance(parsed, dict) else (j.match_reasons or None)
        gaps = _loads(j.skill_gaps, [])
        salary = None
        if j.salary_min_lpa or j.salary_max_lpa:
            salary = f"₹{j.salary_min_lpa or '?'}–{j.salary_max_lpa or '?'} LPA"
        summary = verdict or " · ".join(filter(None, [j.location, salary]))
        g.upsert_node(
            nid, "job", f"{j.title} — {j.company_name}",
            summary=summary,
            props={
                "title": j.title, "company": j.company_name, "location": j.location, "remote": j.remote,
                "url": j.url, "source": j.source, "status": j.status,
                "score": j.match_score, "embed_sim": j.embed_sim,
                "salary_min_lpa": j.salary_min_lpa, "salary_max_lpa": j.salary_max_lpa, "salary_raw": j.salary_raw,
                "posted_at": _iso(j.posted_at), "scraped_at": _iso(j.scraped_at), "scored_at": _iso(j.scored_at),
                "reasons": reasons, "gaps": gaps,
            },
            layer="data", ref_table="job", ref_id=j.id,
            body=" ".join(filter(None, [j.title, j.company_name, j.location or "", verdict or ""] + list(reasons) + list(gaps))),
        )
        if j.company_id:
            g.upsert_edge(nid, "POSTED_BY", f"company:{j.company_id}", layer="data")
        sid = f"source:{j.source}"
        if sid not in sources_seen:
            if g.get(sid) is None:  # context.yaml normally defines sources; fall back to a bare node
                g.upsert_node(sid, "source", j.source, props={}, layer="data")
            sources_seen.add(sid)
        g.upsert_edge(nid, "SOURCED_FROM", sid, layer="data")
        if j.status == "high_match":
            g.upsert_edge(PROFILE_ID, "HIGH_MATCH", nid, props={"score": j.match_score}, layer="data")
        elif j.status in ("applied",):
            g.upsert_edge(PROFILE_ID, "APPLIED", nid, layer="data")
    g.prune("job", keep)
    return len(keep)


def sync_contacts(g: Graph, contacts: list[Contact]) -> int:
    keep: set[str] = set()
    channels: set[str] = set()
    for c in contacts:
        nid = f"contact:{c.id}"
        keep.add(nid)
        research = _loads(c.research_notes, None)
        hook = research.get("hook") if isinstance(research, dict) else None
        notes = research.get("notes") if isinstance(research, dict) else c.research_notes
        g.upsert_node(
            nid, "contact", c.name or c.email or f"contact {c.id}",
            summary=(c.role or "") + (f" · hook: {hook}" if hook and hook != "null" else ""),
            props={
                "email": c.email, "role": c.role, "github": c.github, "linkedin": c.linkedin,
                "source": c.source, "confidence": c.confidence, "is_recruiter": c.is_recruiter,
                "researched_at": _iso(c.researched_at), "research": research,
            },
            layer="data", ref_table="contact", ref_id=c.id,
            body=" ".join(filter(None, [c.name, c.email, c.role, c.confidence, c.source, notes if isinstance(notes, str) else ""])),
        )
        g.upsert_edge(nid, "WORKS_AT", f"company:{c.company_id}", props={"confidence": c.confidence}, layer="data")
        ch = f"channel:{c.source}"
        if ch not in channels:
            g.upsert_node(ch, "channel", c.source, props={}, layer="data")
            feat = CHANNEL_FEATURE.get(c.source)
            if feat and g.get(feat) is not None:
                g.upsert_edge(ch, "PROVIDED_BY", feat, layer="data")
            channels.add(ch)
        g.upsert_edge(nid, "FOUND_VIA", ch, layer="data")
    g.prune("contact", keep)
    return len(keep)


def sync_emails(g: Graph, emails: list[Email]) -> int:
    keep: set[str] = set()
    for e in emails:
        nid = f"email:{e.id}"
        keep.add(nid)
        g.upsert_node(
            nid, "email", f"[{e.status}] {e.subject}",
            summary=e.body[:240] if e.body else None,
            props={
                "to": e.to_email, "kind": e.kind, "status": e.status, "error": e.error,
                "gmail_thread_id": e.gmail_thread_id,
                "created_at": _iso(e.created_at), "approved_at": _iso(e.approved_at), "sent_at": _iso(e.sent_at),
                "followup_sent": e.followup_sent,
            },
            layer="data", ref_table="email", ref_id=e.id,
            body=" ".join(filter(None, [e.subject, e.to_email, e.status, e.kind, (e.body or "")[:600]])),
        )
        g.upsert_edge(nid, "SENT_TO", f"contact:{e.contact_id}", layer="data")
        g.upsert_edge(nid, "TARGETS", f"company:{e.company_id}", layer="data")
        if e.job_id:
            g.upsert_edge(nid, "ABOUT_JOB", f"job:{e.job_id}", layer="data")
        if e.parent_email_id:
            g.upsert_edge(nid, "FOLLOWS_UP", f"email:{e.parent_email_id}", layer="data")
    g.prune("email", keep)
    return len(keep)


def sync_replies(g: Graph, replies: list[Reply]) -> int:
    keep: set[str] = set()
    for r in replies:
        nid = f"reply:{r.id}"
        keep.add(nid)
        g.upsert_node(
            nid, "reply", f"[{r.sentiment or 'unclassified'}] from {r.from_addr}",
            summary=r.sentiment_reason,
            props={"from": r.from_addr, "sentiment": r.sentiment, "received_at": _iso(r.received_at), "body": (r.body or "")[:600]},
            layer="data", ref_table="reply", ref_id=r.id,
            body=" ".join(filter(None, [r.from_addr, r.sentiment, r.sentiment_reason, (r.body or "")[:600]])),
        )
        g.upsert_edge(nid, "REPLIES_TO", f"email:{r.email_id}", layer="data")
    g.prune("reply", keep)
    return len(keep)


def _skill_leaves(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _skill_leaves(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _skill_leaves(v)]
    return []


def sync_profile(g: Graph) -> int:
    """The candidate as a node, with skills as their own nodes so gaps and jobs can point at them."""
    path = ROOT / CONFIG["profile_path"]
    if not path.exists():
        g.upsert_node(PROFILE_ID, "profile", "candidate (no profile.json yet)", props={}, layer="data")
        return 0
    p = json.loads(path.read_text(encoding="utf-8"))
    skills = sorted({s.strip() for s in _skill_leaves(p.get("skills")) if s and s.strip()})
    g.upsert_node(
        PROFILE_ID, "profile", p.get("name") or "candidate",
        summary=p.get("headline"),
        props={
            "email": p.get("email"), "links": p.get("links"), "years_experience": p.get("years_experience"),
            "education": p.get("education"), "experience": p.get("experience"), "projects": p.get("projects"),
            "strengths": p.get("strengths"), "target_titles": p.get("target_titles"), "summary": p.get("summary"),
            "skills": skills,
        },
        layer="data",
        body=" ".join(filter(None, [p.get("name"), p.get("headline"), p.get("summary")] + skills)),
    )
    keep: set[str] = set()
    for s in skills:
        sid = f"skill:{slugify(s)}"
        keep.add(sid)
        g.upsert_node(sid, "skill", s, props={}, layer="data")
        g.upsert_edge(PROFILE_ID, "HAS_SKILL", sid, layer="data")
    g.prune("skill", keep)
    return len(skills)


def sync_all() -> dict:
    """Mirror every table into the data layer. Safe to run after any pipeline stage."""
    init_db()
    # Read everything first, then write. The graph write is one large transaction on the
    # same file; holding a SQLAlchemy reader open across it deadlocks on "database is locked".
    with get_session() as session:
        companies = session.exec(select(Company)).all()
        jobs = session.exec(select(Job)).all()
        contacts = session.exec(select(Contact)).all()
        emails = session.exec(select(Email)).all()
        replies = session.exec(select(Reply)).all()
    out: dict = {}
    with Graph() as g:
        out["skills"] = sync_profile(g)
        out["companies"] = sync_companies(g, companies)
        out["jobs"] = sync_jobs(g, jobs)
        out["contacts"] = sync_contacts(g, contacts)
        out["emails"] = sync_emails(g, emails)
        out["replies"] = sync_replies(g, replies)
    log.info("kg sync: %s", out)
    return out
