"""Keep internal names off every published page.

The briefing is written for a named reader inside Microsoft, and the writer and validator
agents sometimes mention that reader or their team ("Hugh's brief", "for CELA") in the
text or the correction log. The website and the report pages are public, so render.py
and site.py pass every page through scrub() before it is written.

Add further internal names, comma-separated, in the repository variable REDACT_TERMS
(each one is removed, or replaced by "the reader" for a person's name).
"""

from __future__ import annotations

import os
import re

APOS = r"(?:'|’|&#x27;|&#39;|&rsquo;)"
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\w.+-]+@microsoft\.com\b", re.I), "[address removed]"),
    (re.compile(r"\bHugh Milward,?\s*(?:VP UK (?:&amp;|&) Ireland,?\s*)?(?:CELA,?\s*)?(?:\(Corporate, External (?:&amp;|and|&) Legal Affairs\),?\s*)?(?:Microsoft\b)?"), "the reader"),
    (re.compile(r"\bfor Microsoft UK CELA\b\.?\s*", re.I), ""),
    (re.compile(r"\bMicrosoft UK CELA\b", re.I), "Microsoft UK"),
    (re.compile(r",?\s*\bVP UK (?:&amp;|&) Ireland\b,?", re.I), ""),
    (re.compile(r"\s*\(?Corporate, External (?:&amp;|and|&) Legal Affairs\)?", re.I), ""),
    (re.compile(r"\bHugh Milward" + APOS + r"s\b"), "the reader's"),
    (re.compile(r"\bHugh Milward\b"), "the reader"),
    # a bare "Hugh" only: "Hugh Smith" could be a member of Parliament and is left alone
    (re.compile(r"\bHugh" + APOS + r"s\b"), "the reader's"),
    (re.compile(r"\bHugh\b(?!\s+(?:[A-Z][a-z]|O'|Mc|Mac))"), "the reader"),
    (re.compile(r",?\s*\bCELA\b,?"), ""),
]


def _extra() -> list[tuple[re.Pattern, str]]:
    terms = [t.strip() for t in os.environ.get("REDACT_TERMS", "").split(",") if t.strip()]
    return [(re.compile(r"\b" + re.escape(t) + APOS + r"s\b"), "the reader's") for t in terms] + \
           [(re.compile(r"\b" + re.escape(t) + r"\b"), "the reader") for t in terms]


def scrub(text: str) -> str:
    for rx, rep in _extra() + _RULES:
        text = rx.sub(rep, text)
    # "The reader" at the start of a sentence or list item
    return re.sub(r"(^|[.!?]\s+|>\s*)the reader", lambda m: m.group(1) + "The reader", text)
