"""Match scoring: cheap embedding prefilter, then an LLM rubric pass on survivors.

A 4B model on 8 GB RAM can score maybe a few hundred jobs an hour, so the
embedding pass exists to make sure those calls are spent on plausible jobs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass

from sqlmodel import col, func, select

from jobhunter import CONFIG
from jobhunter import normalize as norm
from jobhunter import resume as resume_mod
from jobhunter.db import Job, get_session, get_setting, init_db, set_setting, utcnow

log = logging.getLogger(__name__)

_M = CONFIG["matching"]
PREFILTER = float(_M.get("embed_prefilter", 0.60))
PREFILTER_PCT = _M.get("embed_prefilter_percentile")
HIGH_MATCH = int(_M.get("high_match_threshold", 65))
MAX_YOE = int(CONFIG["search"].get("max_yoe", 3))
MIN_LPA = float(CONFIG["search"].get("min_lpa", 24))

EMBED_BATCH = 12  # keep peak RAM modest alongside the chat model

_RESUME_VEC_KEY = "resume_embedding"
_RESUME_HASH_KEY = "resume_embedding_hash"


# ---------------------------------------------------------------- embeddings

def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def resume_vector(*, force: bool = False) -> list[float]:
    """Embed the profile once and cache it; re-embeds automatically if the resume changed."""
    from jobhunter import llm

    text = resume_mod.embedding_text()
    digest = hashlib.sha1(text.encode()).hexdigest()

    with get_session() as session:
        if not force and get_setting(session, _RESUME_HASH_KEY) == digest:
            cached = get_setting(session, _RESUME_VEC_KEY)
            if cached:
                return json.loads(cached)

        vec = llm.embed_one(text)
        set_setting(session, _RESUME_VEC_KEY, json.dumps(vec))
        set_setting(session, _RESUME_HASH_KEY, digest)
        log.info("resume embedding refreshed (%d dims)", len(vec))
        return vec


def job_text(job: Job) -> str:
    bits = [job.title, job.company_name, job.location or "", (job.description or "")[:4000]]
    return "\n".join(b for b in bits if b)


def prefilter(limit: int = 400) -> int:
    """Compute resume<->JD cosine similarity for jobs that don't have one yet."""
    init_db()
    from jobhunter import llm

    rvec = resume_vector()
    done = 0
    with get_session() as session:
        rows = session.exec(
            select(Job).where(col(Job.embed_sim).is_(None)).order_by(col(Job.scraped_at).desc()).limit(limit)
        ).all()
        for i in range(0, len(rows), EMBED_BATCH):
            batch = rows[i : i + EMBED_BATCH]
            try:
                vecs = llm.embed([job_text(j) for j in batch])
            except llm.LLMUnavailable:
                raise
            except Exception as e:  # noqa: BLE001 — one bad batch shouldn't stop the pass
                log.warning("embed batch failed: %s", e)
                continue
            for job, v in zip(batch, vecs):
                job.embed_sim = round(cosine(rvec, v), 4)
                session.add(job)
                done += 1
            session.commit()
    log.info("prefilter: embedded %d jobs", done)
    return done


# ---------------------------------------------------------------- rubric scoring

RUBRIC_SYSTEM = """You are a hiring-funnel realist. You estimate the probability that THIS candidate
gets shortlisted (first recruiter/technical screen) for THIS specific job.

Be honest and calibrated, not encouraging:
- A job demanding more years than the candidate has is a real barrier, not a formality.
- Overlapping tech stack and shipped, relevant projects raise the odds a lot.
- Explicitly new-grad / early-career / "founding engineer at a small startup" postings favour this candidate.
- Senior/Staff/Principal titles for a candidate with under 3 years should score low, whatever the skill overlap.

Reply with JSON only."""

RUBRIC_PROMPT = """CANDIDATE
{profile}

JOB
Title: {title}
Company: {company}
Location: {location}{remote}
Salary: {salary}
Description (excerpt):
---
{description}
---

Score the shortlist probability 0-100 using this rubric, then combine:
1. skills_overlap (0-100): how much of the required stack the candidate demonstrably has
2. experience_fit (0-100): required years/seniority vs the candidate's {yoe} years
3. early_career_friendly (0-100): does the posting welcome new grads / early-career engineers
4. domain_fit (0-100): relevance of the candidate's projects and past work to this role

Reply with exactly:
{{
  "score": <int 0-100, the overall shortlist probability>,
  "skills_overlap": <int>,
  "experience_fit": <int>,
  "early_career_friendly": <int>,
  "domain_fit": <int>,
  "reasons": [<2-4 short strings, each citing something concrete from the job AND the resume>],
  "gaps": [<1-3 short strings: what the candidate is missing for this role>],
  "verdict": "<one sentence, plain and honest>"
}}"""


@dataclass
class Score:
    score: int
    reasons: list[str]
    gaps: list[str]
    verdict: str
    breakdown: dict


def score_job(job: Job, profile_text: str, yoe: float) -> Score | None:
    from jobhunter import llm

    salary = "not stated"
    if job.salary_min_lpa:
        salary = f"~{job.salary_min_lpa}-{job.salary_max_lpa} LPA (INR equivalent)"

    data = llm.chat_json(
        RUBRIC_PROMPT.format(
            profile=profile_text,
            title=job.title,
            company=job.company_name,
            location=job.location or "unspecified",
            remote=" (remote)" if job.remote else "",
            salary=salary,
            description=(job.description or "")[:4500],
            yoe=yoe,
        ),
        RUBRIC_SYSTEM,
        temperature=0.2,
        num_predict=700,
        default=None,
    )
    if not isinstance(data, dict) or not isinstance(data.get("score"), (int, float)):
        return None

    raw = int(max(0, min(100, data["score"])))
    breakdown = {
        k: int(data[k]) for k in ("skills_overlap", "experience_fit", "early_career_friendly", "domain_fit")
        if isinstance(data.get(k), (int, float))
    }
    final = _apply_hard_rules(raw, job)
    return Score(
        score=final,
        reasons=[str(r)[:300] for r in (data.get("reasons") or [])][:4],
        gaps=[str(g)[:200] for g in (data.get("gaps") or [])][:3],
        verdict=str(data.get("verdict") or "")[:400],
        breakdown=breakdown,
    )


def _apply_hard_rules(score: int, job: Job) -> int:
    """Deterministic corrections the LLM is unreliable about."""
    if norm.is_senior(job.title):
        score = min(score, 35)   # a sub-3-year candidate is not getting a Staff screen
    if job.salary_max_lpa and job.salary_max_lpa < MIN_LPA:
        score = min(score, 40)   # below the user's floor, however good the fit
    if not job.description or len(job.description) < 200:
        score = min(score, 60)   # too little signal to be confident
    return int(max(0, min(100, score)))


def prefilter_threshold() -> float:
    """Effective cutoff: the configured percentile of the live distribution, floored by the absolute."""
    if not PREFILTER_PCT:
        return PREFILTER
    with get_session() as session:
        sims = sorted(session.exec(select(Job.embed_sim).where(col(Job.embed_sim).is_not(None))).all())
    if len(sims) < 20:
        return PREFILTER  # too few samples for a percentile to mean anything
    idx = min(len(sims) - 1, int(len(sims) * float(PREFILTER_PCT) / 100))
    return max(PREFILTER, round(sims[idx], 4))


def score_pending(limit: int = 40, *, min_sim: float | None = None) -> dict:
    """Rubric-score the highest-similarity unscored jobs."""
    init_db()
    threshold = prefilter_threshold() if min_sim is None else min_sim
    profile = resume_mod.load_profile()
    profile_text = resume_mod.profile_summary(profile)
    yoe = profile.get("years_experience") or 1

    stats = {"scored": 0, "skipped": 0, "high_match": 0, "failed": 0}
    with get_session() as session:
        rows = session.exec(
            select(Job)
            .where(col(Job.match_score).is_(None), col(Job.embed_sim).is_not(None))
            .order_by(col(Job.embed_sim).desc())
            .limit(limit)
        ).all()

        for job in rows:
            if (job.embed_sim or 0) < threshold:
                job.status = "ignored"
                job.match_score = 0
                job.match_reasons = f"Below similarity prefilter ({job.embed_sim:.2f} < {threshold})"
                job.scored_at = utcnow()
                session.add(job)
                stats["skipped"] += 1
                continue

            result = score_job(job, profile_text, yoe)
            if result is None:
                stats["failed"] += 1
                continue

            job.match_score = result.score
            job.match_reasons = json.dumps(
                {"reasons": result.reasons, "verdict": result.verdict, "breakdown": result.breakdown}
            )
            job.skill_gaps = json.dumps(result.gaps)
            job.scored_at = utcnow()
            job.status = "high_match" if result.score >= HIGH_MATCH else "scored"
            if job.status == "high_match":
                stats["high_match"] += 1
            session.add(job)
            stats["scored"] += 1
            session.commit()  # commit per job — scoring is slow and interruptible

        session.commit()

    log.info("scoring: %s", stats)
    return stats


def rescore_all() -> int:
    """Clear scores (e.g. after the resume changed) so the next pass redoes everything."""
    init_db()
    with get_session() as session:
        rows = session.exec(select(Job)).all()
        for job in rows:
            job.match_score = None
            job.match_reasons = None
            job.skill_gaps = None
            job.embed_sim = None
            job.scored_at = None
            job.notified = False
            if job.status in ("scored", "high_match", "ignored"):
                job.status = "new"
            session.add(job)
        session.commit()
    resume_vector(force=True)
    log.info("cleared scores on %d jobs", len(rows))
    return len(rows)


def counts() -> dict:
    with get_session() as session:
        total = session.exec(select(func.count()).select_from(Job)).one()
        scored = session.exec(
            select(func.count()).select_from(Job).where(col(Job.match_score).is_not(None))
        ).one()
        high = session.exec(
            select(func.count()).select_from(Job).where(Job.status == "high_match")
        ).one()
        embedded = session.exec(
            select(func.count()).select_from(Job).where(col(Job.embed_sim).is_not(None))
        ).one()
    return {"jobs": total, "embedded": embedded, "scored": scored, "high_match": high}
