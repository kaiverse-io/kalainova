"""A brief to a written script, for the pieces that used to need one handed in.

A model writes when one is available, and its output has to pass the same contract a person's would.
With no model, the agent driving the session writes the file instead, and this stage only says so.
"""

from __future__ import annotations

import json
from typing import Any

from . import consistency, prompts
from .jobfs import ContractError, Job
from .providers import router

WRITERS = {
    "song": ("song", "song_writer"),
    "comic": ("comic_script", "comic_writer"),
    "story": ("story", "story_writer"),
}
ATTEMPTS = 3


def _facts(job: Job) -> str:
    if not job.has("research"):
        return ""
    found = [f["statement"] for f in job.read("research")["findings"] if f.get("verified")]
    return (
        "Checked facts you may use (JSON):\n" + json.dumps(found, ensure_ascii=False)
        if found
        else ""
    )


def _fixed(job: Job) -> str:
    locked = consistency.for_job(job)
    if not locked:
        return ""
    return "\n\n" + prompts.load("plan_kit").format(
        context=consistency.planner_context(locked[0], locked[1]["cast"])
    )


def ensure(job: Job, kind: str) -> None:
    """Make sure this piece has its script, writing one from the brief if it can."""
    contract, prompt_name = WRITERS[kind]
    if job.has(contract):
        return
    data = job.job
    brief = data.get("brief") or {}
    if not brief:
        raise ContractError(f"{job.id}: job.brief is required to write this")
    if not router.available(job, "llm"):
        raise ContractError(
            f"{job.id}: no LLM provider is ready. Have the agent write {job.path(contract)}."
        )
    from .plan import extract_json

    last_error = ""
    for _ in range(ATTEMPTS):
        text = prompts.load(prompt_name).format(
            brief=json.dumps(brief, indent=2, ensure_ascii=False),
            job_id=job.id,
            facts=_facts(job),
        )
        retry = (
            f"\n\nYour previous output failed validation:\n{last_error}\nFix it."
            if last_error
            else ""
        )
        _, res = router.generate(
            job, "llm", "llm", text + _fixed(job) + retry, max_tokens=8000, note=f"write {kind}"
        )
        try:
            draft: dict[str, Any] = extract_json(res.text)
            draft["schema_version"] = "0.1"
            draft["job_id"] = job.id
            job.write(contract, draft)
            return
        except (ValueError, ContractError) as exc:
            last_error = str(exc)[:1500]
    raise ContractError(f"{job.id}: the writer failed validation {ATTEMPTS} times: {last_error}")
