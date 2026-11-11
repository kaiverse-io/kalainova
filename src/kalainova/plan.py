"""INTENT -> SCRIPT. Writes script_packet.json from job.brief.

Two planners:
  * an LLM provider when one is ready, or
  * the agent driving the session writes script_packet.json directly; this stage
    then only validates it. That is the default inside Claude Code / agent containers.
"""

from __future__ import annotations

import json
import re

from . import consistency, prompts, shots
from .jobfs import ContractError, Job
from .providers import router


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
        "beats": [
            {
                "id": "b1",
                "role": "hook|body|payoff|cta",
                "text": "spoken line",
                "on_screen": "<= 5 words overlay or empty",
                "visual_cue": "precise shot description for an image/video model",
                "visual_kind": "still|video",
                "emphasis": ["words to highlight"],
                "cast": ["a name from continuity.people, if anyone is seen"],
                "location": "a name from continuity.places",
                "ambience": "what this place sounds like",
                "continues": "true only if this shot picks up exactly where the last one ended",
                "shot": {
                    "size": "wide|medium|close",
                    "first_frame": "the still picture at the start, with nothing happening yet",
                    "last_frame": "the still picture at the end",
                    "camera": "how the camera moves, and what it reveals when it stops",
                    "action": "what the subject does, start to finish",
                    "environment": "what else moves: water, smoke, cloud, crowd",
                },
            }
        ],
        "continuity": {
            "people": {"name": "age, build, hair, and exactly what they wear"},
            "places": {"name": "what the place is and how it is laid out"},
            "props": {"name": "what it looks like"},
        },
        "claims": [
            {"id": "c1", "statement": "exact fact", "source": "URL", "finding": "a finding id"}
        ],
        "publish": {"title": "platform title", "description": "2-3 lines", "hashtags": ["#tag"]},
    }
    budget = shots.video_budget(job)
    if "video" not in (job.get("media") or []):
        motion = "visual_kind=still for every beat."
    elif budget >= shots.UNLIMITED:
        motion = "visual_kind=video for every beat; a shot that does not move reads as a slideshow."
    else:
        motion = (
            f"visual_kind=video for at most {budget} beats, choosing where motion matters most."
        )
    return (
        f"Brief:\n{json.dumps(brief, indent=2, ensure_ascii=False)}\n\n"
        f"Media: {job.get('media')}. Rights: {job.get('rights')}. Target duration: {target}s.\n"
        f"Write 6-10 beats. {motion}\n\n"
        f"JSON shape:\n{json.dumps(schema_hint, indent=2)}"
    )


def _research_context(job: Job) -> str:
    """Findings checked against their sources. The writer states facts from here and nowhere else."""
    if not job.has("research"):
        return ""
    data = job.read("research")
    urls = {s["id"]: s["url"] for s in data["sources"]}
    usable = [
        {
            "finding": f["id"],
            "statement": f["statement"],
            "source": urls.get(f["source_ids"][0], ""),
        }
        for f in data["findings"]
        if f.get("verified")
    ]
    return "\n\n" + prompts.load("plan_research").format(
        findings=json.dumps(usable, indent=2, ensure_ascii=False),
        gaps=json.dumps(data.get("gaps") or [], ensure_ascii=False),
    )


def plan_refusals(job: Job, packet: dict) -> list[str]:
    """What shots.review refuses, so a planner can be told and try again."""
    brief = job.job.get("brief") or {}
    budget = shots.video_budget(job.job)
    found = shots.review(packet, budget=budget, allow_stills=bool(brief.get("allow_stills")))
    return [p["detail"] for p in found if p["status"] == "fail"]


def extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    blob = m.group(1) if m else text[text.find("{") : text.rfind("}") + 1]
    return json.loads(blob)


def run(job: Job, *, force: bool = False) -> dict:
    locked = consistency.for_job(job)
    if job.has("script_packet") and not force:
        packet = job.read("script_packet")  # validates
        if locked:
            consistency.check_script(job, locked[0], packet, locked[1]["cast"])
        return packet
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
        fixed = ""
        if locked:
            context = consistency.planner_context(locked[0], locked[1]["cast"])
            fixed = "\n\n" + prompts.load("plan_kit").format(context=context)
        prompt = (
            _prompt(data)
            + _research_context(job)
            + fixed
            + (
                f"\n\nYour previous output failed validation:\n{last_err}\nFix it."
                if last_err
                else ""
            )
        )
        _, res = router.generate(
            job,
            "llm",
            "llm",
            prompt,
            system=prompts.load("plan_system"),
            max_tokens=4000,
            note="plan",
        )
        try:
            packet = extract_json(res.text)
            packet["schema_version"] = "0.1"
            packet["job_id"] = data["job_id"]
            if locked:
                consistency.check_script(job, locked[0], packet, locked[1]["cast"])
            refused = plan_refusals(job, packet)
            if refused:
                raise ContractError("; ".join(refused))
            job.write("script_packet", packet)
            return packet
        except (ValueError, KeyError, ContractError) as exc:
            last_err = str(exc)[:1500]
    raise ContractError(f"{job.id}: planner failed validation 3 times: {last_err}")
