"""Shared scraper plumbing: the common job schema, HTTP client, HTML->text."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from jobhunter import CONFIG

log = logging.getLogger(__name__)

_SRC = CONFIG.get("sources") or {}
TIMEOUT = float(_SRC.get("request_timeout", 25))
CONCURRENCY = int(_SRC.get("concurrency", 8))
USER_AGENT = _SRC.get(
    "user_agent",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class RawJob:
    """One posting as scraped, before normalization. Every scraper emits these."""

    company_name: str
    title: str
    url: str
    source: str
    location: str | None = None
    remote: bool = False
    description: str | None = None
    posted_at: datetime | None = None
    salary_raw: str | None = None
    # company hints the normalizer folds into the Company row
    company_website: str | None = None
    ats: str | None = None
    ats_slug: str | None = None
    github_org: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=HEADERS,
        timeout=httpx.Timeout(TIMEOUT),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=CONCURRENCY * 2, max_keepalive_connections=CONCURRENCY),
    )


async def get_json(http: httpx.AsyncClient, url: str, **kw: Any) -> Any:
    """GET returning parsed JSON, or None on any failure. Scrapers must never crash the run."""
    try:
        r = await http.get(url, **kw)
        if r.status_code >= 400:
            log.debug("GET %s -> %s", url, r.status_code)
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001 — one dead board shouldn't kill the fleet
        log.debug("GET %s failed: %s", url, e)
        return None


async def get_text(http: httpx.AsyncClient, url: str, **kw: Any) -> str | None:
    try:
        r = await http.get(url, **kw)
        if r.status_code >= 400:
            return None
        return r.text
    except Exception as e:  # noqa: BLE001
        log.debug("GET %s failed: %s", url, e)
        return None


async def gather_limited(coros: list, limit: int = CONCURRENCY) -> list:
    """Run coroutines with bounded concurrency; exceptions become None."""
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            try:
                return await c
            except Exception as e:  # noqa: BLE001
                log.debug("task failed: %s", e)
                return None

    return await asyncio.gather(*(run(c) for c in coros))


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")


def html_to_text(html: str | None, *, limit: int = 12000) -> str:
    """Readable plain text from a job-description HTML blob."""
    if not html:
        return ""
    if "<" not in html:
        return _WS_RE.sub(" ", html).strip()[:limit]
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4"]):
            br.append("\n")
        text = soup.get_text()
    except Exception:  # noqa: BLE001 — malformed markup falls back to regex strip
        text = _TAG_RE.sub(" ", html)

    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()[:limit]


_REMOTE_RE = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed|worldwide)\b", re.I)


def looks_remote(*fields: str | None) -> bool:
    return any(_REMOTE_RE.search(f) for f in fields if f)


def parse_ts(value: Any) -> datetime | None:
    """Best-effort timestamp parsing across the many shapes job boards use."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            # ms vs s epoch
            secs = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(secs, tz=timezone.utc).replace(tzinfo=None)
        from dateutil import parser as dateparser

        dt = dateparser.parse(str(value))
        if dt is None:
            return None
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:  # noqa: BLE001
        return None
