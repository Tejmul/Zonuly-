"""WeWorkRemotely — public category RSS feeds (no API key, no scraping fragility)."""

from __future__ import annotations

import logging
import re

import httpx

from jobhunter.scrapers.base import RawJob, gather_limited, get_text, html_to_text, parse_ts

log = logging.getLogger(__name__)

SOURCE = "wwr"
FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]

# WWR titles are "Company: Role"
_TITLE_RE = re.compile(r"^\s*(?P<company>[^:]{2,60}?)\s*:\s*(?P<title>.+)$")


async def _fetch_feed(http: httpx.AsyncClient, url: str) -> list[RawJob]:
    text = await get_text(http, url)
    if not text:
        return []
    import feedparser

    parsed = feedparser.parse(text)
    out: list[RawJob] = []
    for e in parsed.entries:
        raw_title = (e.get("title") or "").strip()
        link = e.get("link")
        if not raw_title or not link:
            continue
        m = _TITLE_RE.match(raw_title)
        company = m.group("company").strip() if m else "Unknown"
        title = m.group("title").strip() if m else raw_title
        desc = html_to_text(e.get("summary") or e.get("description"))
        region = e.get("region") or ""
        out.append(
            RawJob(
                company_name=company,
                title=title,
                url=link,
                source=SOURCE,
                location=region or "Remote",
                remote=True,
                description=desc,
                posted_at=parse_ts(e.get("published") or e.get("updated")),
            )
        )
    return out


async def fetch(http: httpx.AsyncClient, companies: list[dict] | None = None) -> list[RawJob]:
    results = await gather_limited([_fetch_feed(http, u) for u in FEEDS], limit=4)
    seen: set[str] = set()
    jobs: list[RawJob] = []
    for r in results:
        for j in r or []:
            if j.url in seen:
                continue
            seen.add(j.url)
            jobs.append(j)
    log.info("wwr: %d jobs from %d feeds", len(jobs), len(FEEDS))
    return jobs
