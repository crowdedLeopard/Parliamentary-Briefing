"""Optional: a short, evidence-grounded 'likely drivers' note per member.

Runs only when the ANTHROPIC_API_KEY secret is set. The model sees only the
profile evidence gathered from Parliament's public record and must cite it;
without a key, profiles keep their rule-based signals and nothing else changes.
"""

from __future__ import annotations

import json
import logging
import os

import httpx

log = logging.getLogger("analysis")

PROMPT = """You are briefing Microsoft UK's public policy lead on a UK parliamentarian who asked a question \
relevant to technology policy. From the EVIDENCE only, write 2-3 sentences on what most plausibly drives \
their interest (for example constituency, committee role, frontbench brief, declared interests, a sustained \
line of questioning) and how that bears on Microsoft's issues. Rules: use only facts in the evidence; mark \
inferences with "likely" or "appears"; no speculation about private life, character or health; stay \
politically neutral; plain UK English; no preamble.

EVIDENCE:
{evidence}"""


def add_reads(profiles: list[dict], questions_by_uin: dict[str, dict]) -> int:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return 0
    model = os.environ.get("ANALYSIS_MODEL", "claude-sonnet-5-5")
    done = 0
    with httpx.Client(timeout=60) as c:
        for p in profiles:
            todays = [{"uin": u, "heading": (questions_by_uin.get(u) or {}).get("heading"),
                       "question": (questions_by_uin.get(u) or {}).get("questionText", "")[:600]} for u in p["today"]]
            evidence = json.dumps({k: p[k] for k in ("name", "party", "house", "seat", "since", "posts",
                                                       "committees", "focus", "interests", "history", "signals")}
                                  | {"questions_this_period": todays}, ensure_ascii=False)[:9000]
            try:
                r = c.post("https://api.anthropic.com/v1/messages",
                           headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                           json={"model": model, "max_tokens": 300,
                                 "messages": [{"role": "user", "content": PROMPT.format(evidence=evidence)}]})
                r.raise_for_status()
                p["read"] = "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
                done += 1
            except Exception as e:
                log.warning("analysis for %s failed: %s", p.get("name"), e)
    return done
