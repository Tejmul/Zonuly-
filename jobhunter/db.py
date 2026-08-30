"""Database models: Company, Job, Contact, Email, Reply, Setting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine

from jobhunter import CONFIG, ROOT


def utcnow() -> datetime:
    """Naive UTC timestamp — SQLite has no tz type, and everything here is UTC by convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Company(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    website: Optional[str] = None
    domain: Optional[str] = None          # email domain, e.g. "mstack.com"
    github_org: Optional[str] = None
    ats: Optional[str] = None             # greenhouse | lever | ashby | None
    ats_slug: Optional[str] = None        # board token on the ATS
    notes: Optional[str] = None
    email_pattern: Optional[str] = None   # learned pattern e.g. "{first}.{last}"
    contacts_found_at: Optional[datetime] = None   # last contact-discovery run
    created_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id", index=True)
    company_name: str = Field(index=True)
    title: str
    location: Optional[str] = None
    remote: bool = False
    url: str = Field(index=True, unique=True)   # dedup key
    fingerprint: Optional[str] = Field(default=None, index=True)  # company+title dedup across sources
    source: str                                  # greenhouse | lever | hn | remoteok | ...
    description: Optional[str] = None
    posted_at: Optional[datetime] = None
    scraped_at: datetime = Field(default_factory=utcnow)
    # salary (normalized to INR LPA; null if unknown)
    salary_min_lpa: Optional[float] = None
    salary_max_lpa: Optional[float] = None
    salary_raw: Optional[str] = None
    currency: Optional[str] = None
    salary_extracted: bool = False               # LLM salary pass already ran
    # matching
    match_score: Optional[int] = None            # 0-100 shortlist probability
    match_reasons: Optional[str] = None          # LLM explanation
    skill_gaps: Optional[str] = None
    embed_sim: Optional[float] = None
    scored_at: Optional[datetime] = None
    status: str = Field(default="new", index=True)  # new | scored | high_match | ignored | applied
    notified: bool = False


class Contact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    name: Optional[str] = None
    role: Optional[str] = None            # e.g. "AI Engineer", "Recruiter"
    email: Optional[str] = Field(default=None, index=True)
    github: Optional[str] = None
    linkedin: Optional[str] = None
    source: str                           # github | site | hunter | pattern
    confidence: str = "scraped"           # verified | pattern-guessed | scraped
    is_recruiter: bool = False
    research_notes: Optional[str] = None  # what the researcher found about them
    researched_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class Email(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    contact_id: int = Field(foreign_key="contact.id", index=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    job_id: Optional[int] = Field(default=None, foreign_key="job.id")
    to_email: str
    subject: str
    body: str
    kind: str = "cold"                    # cold | followup
    parent_email_id: Optional[int] = None
    status: str = Field(default="draft", index=True)  # draft | approved | rejected | sent | replied | failed
    error: Optional[str] = None
    gmail_thread_id: Optional[str] = None
    gmail_message_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    approved_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    followup_sent: bool = False


class Reply(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email_id: int = Field(foreign_key="email.id", index=True)
    gmail_message_id: Optional[str] = Field(default=None, index=True, unique=True)
    from_addr: str
    body: str
    sentiment: Optional[str] = Field(default=None, index=True)  # positive | negative | closed | neutral
    sentiment_reason: Optional[str] = None
    received_at: datetime = Field(default_factory=utcnow)
    notified: bool = False


class Setting(SQLModel, table=True):
    """Small key/value store for runtime state the config file shouldn't own (send counters, cursors)."""

    key: str = Field(primary_key=True)
    value: str


DB_PATH = ROOT / CONFIG["db_path"]
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)


def get_setting(session: Session, key: str, default: str = "") -> str:
    row = session.get(Setting, key)
    return row.value if row else default


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        row = Setting(key=key, value=value)
    session.add(row)
    session.commit()
