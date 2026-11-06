"""INTENT -> SCRIPT. Writes script_packet.json from job.brief.

Two planners:
  * an LLM provider when one is ready, or
  * the agent driving the session writes script_packet.json directly; this stage
    then only validates it. That is the default inside Claude Code / agent containers.
"""

from __future__ import annotations

import json
import re

from .jobfs import ContractError, Job
from .providers import router

SYSTEM = """You are the head writer of an AI-native content studio. You write short-form scripts that earn
retention and are safe to monetize.

Rules:
- Hook in the first 1.5 seconds: a concrete promise, tension, or surprising specific. No greetings, no "in this video".
- One idea per beat. Spoken lines are short, punchy, plain words. 2.3 to 2.8 words per second of target duration.
- Pattern interrupt every 2-4 seconds: each beat gets a distinct visual.
- Payoff delivers the hook's promise. CTA is one short line and never comment-bait or a fake giveaway.
- Every factual statement goes in claims[] with a real source URL or citation you are confident exists.
  If you are not sure, rewrite the line so it is not a factual claim.
- No real people's likeness, no brands, logos, trademarks, team or league names, song lyrics, or third-party footage
  unless job.rights says licensed/funded-brief and the brief names them.
- Original voice and angle. Never templated filler ("Did you know...?" stacks, "Let's dive in").
Output JSON only, matching the schema you are given. No prose around it."""


def _prompt(job: dict) -> str:
    brief = job.get("brief") or {}
    target = brief.get("duration_sec", 35)
    schema_hint = {
        "schema_version": "0.1",
        "job_id": job["job_id"],
        "title": "string <= 70 chars",
        "format": job.get("format") or "explainer",
        "target_duration_sec": target,
        "hooks": ["three alternative opening lines, strongest first"],
        "beats": [{"id": "b1", "role": "hook|body|payoff|cta", "text": "spoken line",
                   "on_screen": "<= 5 words overlay or empty", "visual_cue": "precise shot description for an image/video model",
                   "visual_kind": "still|video", "emphasis": ["words to highlight"]}],
        "claims": [{"id": "c1", "statement": "exact fact", "source": "URL"}],
        "publish": {"title": "platform title", "description": "2-3 lines", "hashtags": ["#tag"]},
    }
    return (
        f"Brief:\n{json.dumps(brief, indent=2, ensure_ascii=False)}\n\n"
        f"Media: {job.get('media')}. Rights: {job.get('rights')}. Target duration: {target}s.\n"
        f"Write 6-10 beats. visual_kind=video only for the beats where motion matters most (max 3).\n\n"
        f"JSON shape:\n{json.dumps(schema_hint, indent=2)}"
    )


def extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    blob = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(blob)


def run(job: Job, *, force: bool = False) -> dict:
    if job.has("script_packet") and not force:
        return job.read("script_packet")  # validates
    data = job.job
    if not data.get("brief"):
        raise ContractError(f"{job.id}: job.brief is required to plan (subject, audience, outcome)")
    if not router.available(job, "llm"):
        raise ContractError(
            f"{job.id}: no LLM provider is ready. Set the key for one listed in config/studio.yaml, or have the "
            f"agent write {job.path('script_packet')} directly."
        )
    last_err = None
    for attempt in range(3):
        prompt = _prompt(data) + (f"\n\nYour previous output failed validation:\n{last_err}\nFix it." if last_err else "")
        _, res = router.generate(job, "llm", "llm", prompt, system=SYSTEM, max_tokens=4000, note="plan")
        try:
            packet = extract_json(res.text)
            packet["schema_version"] = "0.1"
            packet["job_id"] = data["job_id"]
            job.write("script_packet", packet)
            return packet
        except (ValueError, ContractError) as exc:
            last_err = str(exc)[:1500]
    raise ContractError(f"{job.id}: planner failed validation 3 times: {last_err}")
