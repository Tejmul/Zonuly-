"""Ashby public job-board API — api.ashbyhq.com/posting-api/job-board/{slug}"""

from __future__ import annotations

import logging

import httpx

from jobhunter.scrapers.base import RawJob, gather_limited, get_json, html_to_text, looks_remote, parse_ts

log = logging.getLogger(__name__)

SOURCE = "ashby"
API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


def _salary(job: dict) -> str | None:
    comp = job.get("compensation") or {}
    summary = comp.get("compensationTierSummary") or comp.get("summary")
    if summary:
        return str(summary)
    for tier in comp.get("compensationTiers") or []:
        if tier.get("tierSummary"):
            return str(tier["tierSummary"])
    return None


async def fetch_board(http: httpx.AsyncClient, slug: str, company_name: str | None = None) -> list[RawJob]:
    data = await get_json(http, API.format(slug=slug))
    if not isinstance(data, dict):
        return []
    name = company_name or slug
    out: list[RawJob] = []
    for j in data.get("jobs") or []:
        url = j.get("jobUrl") or j.get("applyUrl")
        title = j.get("title")
        if not url or not title:
            continue
        location = j.get("location")
        secondary = ", ".join(
            s.get("location", "") for s in (j.get("secondaryLocations") or []) if isinstance(s, dict)
        )
        desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
        out.append(
            RawJob(
                company_name=name,
                title=title,
                url=url,
                source=SOURCE,
                location=location or secondary or None,
                remote=bool(j.get("isRemote")) or looks_remote(location, secondary, title),
                description=desc,
                posted_at=parse_ts(j.get("publishedAt") or j.get("updatedAt")),
                salary_raw=_salary(j),
                ats="ashby",
                ats_slug=slug,
            )
        )
    return out


async def fetch(http: httpx.AsyncClient, companies: list[dict]) -> list[RawJob]:
    targets = [c for c in companies if c.get("ats") == "ashby" and c.get("ats_slug")]
    results = await gather_limited([fetch_board(http, c["ats_slug"], c.get("name")) for c in targets])
    jobs = [j for r in results if r for j in r]
    log.info("ashby: %d jobs from %d boards", len(jobs), len(targets))
    return jobs
