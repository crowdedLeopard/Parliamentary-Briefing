"""Keep internal names off every published page.

The briefing is written for a named reader, and the writer and validator agents sometimes
mention that reader or their team in the text or the correction log. The website and the
report pages are public, so render.py and site.py pass every page through scrub() before
it is written.

The internal words are not written out here, because this repository is public too. Each
is stored as the start of the SHA-256 hash of its lower-case form, and scrub() compares the
hash of every word on a page against them:
  - FIRST_NAMES: a first name on its own (or with "'s") becomes "the reader". Followed by a
    capitalised word it is left alone, because a member of Parliament may share the name.
  - SURNAMES: a surname, with or without the first name before it, becomes "the reader".
  - DROP: a word (a team name) that is simply removed.
  - DOMAINS: an email address at one of these domains becomes "[address removed]".
The role title is also removed. Add further names, comma-separated, in the repository
variable REDACT_TERMS (each becomes "the reader").
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache

FIRST_NAMES = {"c93f1e400f26708f"}
SURNAMES = {"5c7dfb2ab2d1475c"}
DROP = {"12d3fca86a334260"}
DOMAINS = {"24299f39915b1fa5"}

APOS = r"(?:'|’|&#x27;|&#39;|&rsquo;)"
_SP = r"(?:\s|&nbsp;)+"
_EMAIL = re.compile(r"\b[\w.+-]+@([\w-]+(?:\.[\w-]+)+)\b")
_PAIR = re.compile(r"\b([A-Za-z]+)(" + _SP + r")(?=([A-Za-z]+)\b)")
_WORD = re.compile(r"\b([A-Za-z]+)(" + APOS + r"s\b)?(?=(" + _SP + r"(?:[A-Z][a-z]|O'|Mc|Mac))?)")
_DROP = re.compile(r"\s*\(\s*([A-Za-z]+)\s*\)|,?\s*\bfor\s+([A-Za-z]+)\b|,?\s*\b([A-Za-z]+)\b")
_ROLE = re.compile(r",?\s*\(?\bVP UK (?:&amp;|&|and) Ireland\b\)?,?"
                   r"|\s*\(?\bCorporate, External (?:&amp;|&|and) Legal Affairs\b\)?", re.I)


@lru_cache(maxsize=65536)
def _h(word: str) -> str:
    return hashlib.sha256(word.lower().encode()).hexdigest()[:16]


def _pair(m: re.Match) -> str:
    """Drop the first name of a full name; the surname is replaced next."""
    return "" if _h(m.group(1)) in FIRST_NAMES and _h(m.group(3)) in SURNAMES else m.group(0)


def _word(m: re.Match) -> str:
    h, poss = _h(m.group(1)), m.group(2)
    if h in SURNAMES or (h in FIRST_NAMES and (poss or not m.group(3))):
        return "the reader" + ("'s" if poss else "")
    return m.group(0)                                 # "<first name> <Surname>" may be a member of Parliament


def _drop(m: re.Match) -> str:
    return "" if _h(m.group(1) or m.group(2) or m.group(3)) in DROP else m.group(0)


def _email(m: re.Match) -> str:
    return "[address removed]" if _h(m.group(1)) in DOMAINS else m.group(0)


def _extra() -> list[tuple[re.Pattern, str]]:
    terms = [t.strip() for t in os.environ.get("REDACT_TERMS", "").split(",") if t.strip()]
    return [(re.compile(r"\b" + re.escape(t) + APOS + r"s\b"), "the reader's") for t in terms] + \
           [(re.compile(r"\b" + re.escape(t) + r"\b"), "the reader") for t in terms]


def scrub(text: str) -> str:
    text = _EMAIL.sub(_email, text)
    for rx, rep in _extra():
        text = rx.sub(rep, text)
    text = _PAIR.sub(_pair, text)
    text = _WORD.sub(_word, text)
    text = _DROP.sub(_drop, text)                     # with its brackets, or the comma before it
    text = _ROLE.sub("", text)
    # "the reader" at the start of a sentence or list item
    return re.sub(r"(^|[.!?]\s+|>\s*)the reader", lambda m: m.group(1) + "The reader", text)
