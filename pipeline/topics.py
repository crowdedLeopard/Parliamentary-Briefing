"""Topic and keyword rules for the Parliament tech monitor.

Based on the keyword list in the original Power Automate flow
("Parliament Data Fetch Flow"), with these fixes:

* Whole-word matching, so "compute" no longer matches "computer" and
  "aws" no longer depends on a leading space.
* Text is stripped of HTML first, so "AI" at the start of a paragraph
  (e.g. "<p>AI ...") is caught.
* Ambiguous words only count in a tech context: "sovereign" (not Chagos
  sovereignty or the Sovereign Grant), "frontier" (not border frontiers),
  "outage" (not power cuts).

Each topic has a label (used as a briefing section heading) and a list of
regular expressions. Patterns are matched against lower-cased plain text.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    patterns: tuple[str, ...]


def _w(term: str) -> str:
    """Whole-word / whole-phrase pattern for a literal term."""
    return r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b"


TOPICS: tuple[Topic, ...] = (
    Topic(
        "microsoft",
        "Microsoft and its businesses",
        tuple(_w(t) for t in ("microsoft", "xbox", "linkedin", "github", "azure",
                              "copilot", "activision")),
    ),
    Topic(
        "tech_companies",
        "Other technology and AI companies",
        (
            _w("google"), _w("deepmind"), _w("amazon web services"), r"\baws\b",
            _w("openai"), _w("chatgpt"), _w("anthropic"), _w("nvidia"),
        ),
    ),
    Topic(
        "ai",
        "Artificial intelligence",
        (
            _w("artificial intelligence"), r"\bai\b", r"\bgenai\b",
            r"\bfrontier\s+(ai|models?|technolog\w*|systems?)\b",
            _w("large language model"), _w("large language models"), r"\bllms?\b",
            _w("machine learning"), r"\balgorithm\w*", r"\bchatbots?\b",
            r"\bdeepfakes?\b", _w("ai security institute"), _w("ai safety institute"),
            _w("facial recognition"),
        ),
    ),
    Topic(
        "cloud_compute",
        "Cloud, data centres and compute",
        (
            r"\bcloud\b", r"\bhyperscal\w*", r"\bdata\s+cent(re|er)s?\b", r"\bdatacent(re|er)s?\b",
            r"\bcompute\b", r"\bsupercomput\w*", r"\bgrowth\s+zones?\b", _w("cloud first"),
            r"\bsovereign\s+(cloud|ai|compute|capabilit\w*|technolog\w*|data|digital)\b",
            r"\b(digital|data|technological|tech|cloud)\s+sovereignty\b",
            r"\bvendor\s+lock(-|\s)?in\b", r"\bsemiconductors?\b",
        ),
    ),
    Topic(
        "online_safety",
        "Online safety and social media",
        (
            _w("online safety"), r"\bonline\s+harms?\b", r"\bofcom\b", _w("age verification"),
            _w("age assurance"), _w("social media"), r"\bonline\s+(scams?|fraud)\b",
        ),
    ),
    Topic(
        "copyright_ip",
        "Copyright and intellectual property",
        (_w("copyright"), _w("text and data mining"), _w("intellectual property")),
    ),
    Topic(
        "data_protection",
        "Data protection and privacy",
        (_w("data protection"), _w("information commissioner"), r"\bico\b", r"\bgdpr\b"),
    ),
    Topic(
        "cyber",
        "Cyber security and resilience",
        (
            r"\bcyber\w*", r"\bransomware\b", _w("network and information systems"),
            r"\b(it|cloud|system|systems|software|digital|online|technology|network|internet|website|computer)\s+outages?\b",
            r"\bcrowdstrike\b", _w("computer misuse"),
            r"\bencrypt\w*", _w("investigatory powers"),
        ),
    ),
    Topic(
        "competition",
        "Digital competition and markets",
        (_w("digital markets"), _w("strategic market status"), r"\bdmcc\b"),
    ),
    Topic(
        "gov_digital",
        "Government digital, IT and procurement",
        (
            _w("government digital service"), _w("digital and it services"),
            _w("digital, data and technology"), _w("digital procurement"),
            _w("digital technology"), _w("legacy it systems"),
        ),
    ),
    Topic(
        "skills",
        "Digital skills and education technology",
        (_w("digital skills"), r"\bcomputing\b", r"\bedtech\b"),
    ),
)

_COMPILED = tuple((t, tuple(re.compile(p, re.IGNORECASE) for p in t.patterns)) for t in TOPICS)

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def to_plain_text(value: str | None) -> str:
    """Strip HTML tags and entities and collapse whitespace."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return _SPACE_RE.sub(" ", text).strip()


def match_topics(*texts: str | None, extra_terms: list[str] | None = None) -> dict[str, list[str]]:
    """Return {topic_label: [matched words]} for the combined texts.

    ``extra_terms`` are literal words/phrases added for one run; they are
    reported under "Other keywords".
    """
    plain = " ".join(to_plain_text(t) for t in texts if t)
    found: dict[str, list[str]] = {}
    for topic, regexes in _COMPILED:
        hits: list[str] = []
        for rx in regexes:
            m = rx.search(plain)
            if m:
                word = m.group(0).lower()
                if word not in hits:
                    hits.append(word)
        if hits:
            found[topic.label] = hits
    if extra_terms:
        extra_hits = []
        for term in extra_terms:
            term = term.strip()
            if term and re.search(_w(term.lower()), plain, re.IGNORECASE):
                extra_hits.append(term.lower())
        if extra_hits:
            found["Other keywords"] = extra_hits
    return found
