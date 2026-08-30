"""ATS discovery — given a company name/website, find which public job board it uses.

Used two ways: to validate/repair companies.yaml, and to auto-grow the seed list
from YC and other company feeds.
"""

from __future__ import annotations

import logging
import re

import httpx

from jobhunter.scrapers.base import gather_limited

log = logging.getLogger(__name__)

PROBES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


def slug_candidates(name: str, website: str | None = None) -> list[str]:
    """Plausible board tokens for a company, most likely first."""
    out: list[str] = []

    def add(s: str) -> None:
        s = s.strip("-").lower()
        if s and s not in out:
            out.append(s)

    base = re.sub(r"[^a-z0-9\s-]", "", name.lower())
    base = re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|technologies|technology|labs|ai|io)\b", " ", base)
    add(re.sub(r"[\s-]+", "", base))          # "scale ai" -> "scale"
    add(re.sub(r"[\s-]+", "-", base.strip()))  # "scale ai" -> "scale"
    add(re.sub(r"[^a-z0-9]", "", name.lower()))  # "scale ai" -> "scaleai"
    add(re.sub(r"[^a-z0-9]+", "-", name.lower()))

    if website:
        host = re.sub(r"^https?://", "", website).split("/")[0]
        host = host.removeprefix("www.")
        add(host.split(".")[0])
    return [s for s in out if len(s) > 1][:5]


async def probe(http: httpx.AsyncClient, ats: str, slug: str) -> tuple[str, str, int] | None:
    """Return (ats, slug, job_count) if this board exists and has postings."""
    try:
        r = await http.get(PROBES[ats].format(slug=slug))
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return None
    jobs = data if isinstance(data, list) else (data.get("jobs") or [])
    if not isinstance(jobs, list) or not jobs:
        return None
    return (ats, slug, len(jobs))


async def find_ats(
    http: httpx.AsyncClient,
    name: str,
    website: str | None = None,
    *,
    hint: str | None = None,
) -> tuple[str, str, int] | None:
    """Probe every (ats, slug) combination; return the board with the most jobs."""
    slugs = slug_candidates(name, website)
    atss = [hint] if hint in PROBES else list(PROBES)
    if hint in PROBES:
        atss += [a for a in PROBES if a != hint]
    results = await gather_limited(
        [probe(http, a, s) for a in atss for s in slugs], limit=6
    )
    hits = [r for r in results if r]
    if not hits:
        return None
    return max(hits, key=lambda h: h[2])
