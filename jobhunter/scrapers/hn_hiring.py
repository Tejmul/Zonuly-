"""Hacker News "Ask HN: Who is hiring?" — monthly threads via the Algolia API.

Top-level comments are individual job posts, conventionally formatted as
`Company | Role | Location | REMOTE | Full-time | salary | url`.
"""

from __future__ import annotations

import logging
import re

import httpx

from jobhunter.scrapers.base import RawJob, gather_limited, get_json, html_to_text, looks_remote, parse_ts

log = logging.getLogger(__name__)

SOURCE = "hn"
SEARCH = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?tags=story,author_whoishiring&query=Ask%20HN%3A%20Who%20is%20hiring%3F&hitsPerPage=8"
)
ITEM = "https://hn.algolia.com/api/v1/items/{id}"
THREADS_TO_READ = 2  # current + previous month

ROLE_HINTS = (
    "engineer", "developer", "sde", "swe", "scientist", "ml ", "ai ", "llm",
    "machine learning", "backend", "back-end", "full stack", "fullstack",
    "python", "research", "infrastructure", "platform", "founding",
)

_SPLIT = re.compile(r"\s*\|\s*")
_YC_TAG = re.compile(r"\s*\((?:YC\s*[SWFX]?\d{2}|yc\s*[sw]\d{2})\)\s*", re.I)
_URL_RE = re.compile(r"https?://[^\s<>\"')]+")
_SALARY_RE = re.compile(
    r"(?:\$|₹|€|£|USD|INR|EUR|GBP)\s?\d[\d,.]*\s?(?:k|K|L|LPA|lakh|lpa|million|m)?"
    r"(?:\s*(?:-|–|to)\s*(?:\$|₹|€|£)?\s?\d[\d,.]*\s?(?:k|K|L|LPA|lakh|lpa|million|m)?)?"
)


def _parse_comment(c: dict) -> RawJob | None:
    text = html_to_text(c.get("text"))
    if not text or len(text) < 60:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    header = lines[0]
    parts = [p.strip() for p in _SPLIT.split(header) if p.strip()]

    if len(parts) >= 2:
        company = _YC_TAG.sub("", parts[0]).strip(" -–|")
        title = parts[1]
        rest = " | ".join(parts[2:])
    else:
        # unformatted post: fall back to the whole first line as the company
        company = _YC_TAG.sub("", header)[:60].strip(" -–|")
        title = next((ln for ln in lines[1:4] if any(h in ln.lower() for h in ROLE_HINTS)), "")
        rest = ""
        if not title:
            return None

    if not company or len(company) > 70:
        return None

    blob = f"{title} {rest} {text[:600]}".lower()
    if not any(h in blob for h in ROLE_HINTS):
        return None

    urls = _URL_RE.findall(text)
    apply_url = next((u for u in urls if not u.startswith("https://news.ycombinator.com")), None)
    sal = _SALARY_RE.search(rest) or _SALARY_RE.search(text[:1200])

    cid = c.get("id") or c.get("objectID")
    return RawJob(
        company_name=company,
        title=title[:140] or "Engineer",
        url=f"https://news.ycombinator.com/item?id={cid}",
        source=SOURCE,
        location=parts[2] if len(parts) > 2 else None,
        remote=looks_remote(rest, text[:400]),
        description=text,
        posted_at=parse_ts(c.get("created_at")),
        salary_raw=sal.group(0) if sal else None,
        company_website=apply_url,
        extra={"apply_url": apply_url},
    )


async def _fetch_thread(http: httpx.AsyncClient, story_id: str) -> list[RawJob]:
    data = await get_json(http, ITEM.format(id=story_id))
    if not isinstance(data, dict):
        return []
    out: list[RawJob] = []
    for child in data.get("children") or []:
        if not isinstance(child, dict) or child.get("author") is None:
            continue  # deleted comment
        job = _parse_comment(child)
        if job:
            out.append(job)
    log.info("hn: thread %s -> %d posts", story_id, len(out))
    return out


async def fetch(http: httpx.AsyncClient, companies: list[dict] | None = None) -> list[RawJob]:
    search = await get_json(http, SEARCH)
    if not isinstance(search, dict):
        log.warning("hn: Algolia search failed")
        return []
    hits = [
        h for h in search.get("hits") or []
        if "who is hiring" in (h.get("title") or "").lower()
    ][:THREADS_TO_READ]
    if not hits:
        return []
    results = await gather_limited([_fetch_thread(http, h["objectID"]) for h in hits], limit=2)
    jobs = [j for r in results if r for j in r]
    log.info("hn: %d jobs from %d threads", len(jobs), len(hits))
    return jobs
