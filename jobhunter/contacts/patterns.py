"""Email pattern inference and candidate generation.

If we already know one real address at a company (from GitHub commits or the
website), we can infer the pattern and apply it to every other name we found —
no API budget, no guessing from a blank slate.
"""

from __future__ import annotations

import logging
import re
import unicodedata

log = logging.getLogger(__name__)

# ordered by how common they are in tech companies
COMMON_PATTERNS = [
    "{first}",
    "{first}.{last}",
    "{f}{last}",
    "{first}{last}",
    "{first}_{last}",
    "{f}.{last}",
    "{first}{l}",
    "{last}{f}",
]

ALL_PATTERNS = COMMON_PATTERNS + ["{last}", "{f}{l}", "{first}-{last}", "{last}.{first}", "{first}.{l}"]


def normalize_name(name: str | None) -> tuple[str, str] | None:
    """'José García-López' -> ('jose', 'garcialopez'). Returns None if unusable."""
    if not name:
        return None
    # strip accents so they match ASCII mailbox conventions
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    ascii_name = re.sub(r"[^A-Za-z\s'\-]", " ", ascii_name)
    parts = [p for p in re.split(r"[\s]+", ascii_name.strip()) if len(p) > 1]
    # drop honorifics and suffixes
    parts = [p for p in parts if p.lower() not in {"dr", "mr", "ms", "mrs", "jr", "sr", "phd", "md", "ii", "iii"}]
    if len(parts) < 2:
        return None
    first = re.sub(r"[^a-z]", "", parts[0].lower())
    last = re.sub(r"[^a-z]", "", parts[-1].lower())
    if not first or not last:
        return None
    return first, last


def render(pattern: str, first: str, last: str, domain: str) -> str:
    local = (
        pattern.replace("{first}", first)
        .replace("{last}", last)
        .replace("{f}", first[:1])
        .replace("{l}", last[:1])
    )
    return f"{local}@{domain}"


def infer_pattern(known_email: str, name: str | None) -> str | None:
    """Given a real address and the person's name, work out the company's pattern."""
    parsed = normalize_name(name)
    if not parsed or "@" not in known_email:
        return None
    first, last = parsed
    local = known_email.split("@")[0].lower()
    for pattern in ALL_PATTERNS:
        candidate = (
            pattern.replace("{first}", first)
            .replace("{last}", last)
            .replace("{f}", first[:1])
            .replace("{l}", last[:1])
        )
        if candidate == local:
            return pattern
    return None


def learn_from_contacts(people: list[dict], domain: str) -> str | None:
    """Vote on the pattern across every known (name, email) pair at this domain."""
    votes: dict[str, int] = {}
    for p in people:
        email, name = p.get("email"), p.get("name")
        if not email or not name or not email.lower().endswith("@" + domain.lower()):
            continue
        pat = infer_pattern(email, name)
        if pat:
            votes[pat] = votes.get(pat, 0) + 1
    if not votes:
        return None
    best = max(votes.items(), key=lambda kv: kv[1])
    log.info("pattern for %s: %s (%d/%d agree)", domain, best[0], best[1], sum(votes.values()))
    return best[0]


def candidates(name: str, domain: str, pattern: str | None = None, *, limit: int = 4) -> list[str]:
    """Candidate addresses for a person, best guess first."""
    parsed = normalize_name(name)
    if not parsed or not domain:
        return []
    first, last = parsed

    if pattern:
        # a known pattern is worth far more than a spread of guesses
        return [render(pattern, first, last, domain)]

    out: list[str] = []
    for pat in COMMON_PATTERNS:
        addr = render(pat, first, last, domain)
        if addr not in out:
            out.append(addr)
        if len(out) >= limit:
            break
    return out
