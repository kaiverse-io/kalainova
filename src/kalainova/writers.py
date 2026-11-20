"""A brief to a written script, for the pieces that used to need one handed in.

A model writes when one is available, and its output has to pass the same contract a person's would.
With no model, the agent driving the session writes the file instead, and this stage only says so.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import consistency, genres, prompts, song_lead
from .jobfs import ContractError, Job, validate
from .providers import router
from .providers.contract import TextRequest

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


def _fixed(job: Job, kind: str) -> str:
    """What the stream's kits fix, for the writer: a script's rules for a script, and for a song
    the artist's voice and canon only, since a song has no hooks, cast or shots."""
    locked = consistency.for_job(job)
    if not locked:
        return ""
    name = "song_kit" if kind == "song" else "plan_kit"
    return "\n\n" + prompts.load(name).format(
        context=consistency.planner_context(locked[0], locked[1]["cast"])
    )


Check = Callable[[dict[str, Any]], list[str]]
Draft = dict[str, Any]


def _drafted(
    job: Job, kind: str, ask: str, accept: Callable[[Any], Draft], check: Check | None
) -> Draft:
    """A writer's answer to `ask`, made into a file by `accept` and held to `check`; a draft
    either faults is told what is wrong, and written again."""
    from .plan import extract_json

    last_error = ""
    for _ in range(ATTEMPTS):
        retry = (
            f"\n\nYour previous output failed validation:\n{last_error}\nFix it."
            if last_error
            else ""
        )
        _, res = router.generate(
            job, TextRequest(prompt=ask + retry, max_tokens=8000), note=f"write {kind}"
        )
        try:
            draft = accept(extract_json(res.text))
            validate(WRITERS[kind][0], draft, where=f"{job.id}/{WRITERS[kind][0]}.json")
            faults = check(draft) if check else []
            if faults:
                raise ValueError("; ".join(faults))
            return draft
        except (ValueError, ContractError) as exc:
            last_error = str(exc)[:1500]
            said = f"{job.id}: the writer's draft was refused, and is asked again"
            print(f"{said}: {last_error[:300]}", file=sys.stderr)
    raise ContractError(f"{job.id}: the writer failed validation {ATTEMPTS} times: {last_error}")


def _ready(job: Job, contract: str) -> dict[str, Any]:
    brief = job.job.get("brief") or {}
    if not brief:
        raise ContractError(f"{job.id}: job.brief is required to write this")
    if not router.available(job, "llm"):
        raise ContractError(
            f"{job.id}: no LLM provider is ready. Have the agent write {job.path(contract)}."
        )
    return dict(brief)


def ensure(
    job: Job, kind: str, check: Check | None = None, replace: bool = False, revise: str = ""
) -> None:
    """Make sure this piece has its script, writing one from the brief if it can. `check` says
    what a draft must not have (a song's rules, its genre); a draft it faults is told, and written
    again. With replace, a script already there is set aside once a new one passes, and not
    before; with revise, the writer is handed it and a person's notes to revise it by."""
    contract, prompt_name = WRITERS[kind]
    if job.has(contract) and not replace:
        return
    brief = _ready(job, contract)
    text = prompts.load(prompt_name).format(
        brief=json.dumps(brief, indent=2, ensure_ascii=False),
        job_id=job.id,
        facts=_facts(job),
        genre=genres.writer_text(brief) if kind == "song" else "",
        sound=prompts.load("song_sound").strip() if kind == "song" else "",
        lead=song_lead.writer_text(job, own=not revise) if kind == "song" else "",
    )
    if revise:
        text += "\n\n" + prompts.load("song_revise").format(
            song=json.dumps(job.read(contract), indent=1, ensure_ascii=False), notes=revise.strip()
        )

    def accept(draft: Any) -> Draft:
        draft["schema_version"] = "0.1"
        draft["job_id"] = job.id
        if contract == "song":
            draft["words_by"] = "model"  # a release's AI disclosure reads who wrote them
        return dict(draft)

    draft = _drafted(job, kind, text + _fixed(job, kind), accept, check)
    if replace and job.has(contract):
        set_aside(job, contract)
    job.write(contract, draft)


def _noted(sections: list[dict[str, Any]], notes: list[Any]) -> list[dict[str, Any]]:
    """Each section as it was, with the writer's note as its style (none when the note is empty)."""
    out = []
    for section, note in zip(sections, notes, strict=True):
        kept = {k: v for k, v in section.items() if k != "style"}
        out.append({**kept, "style": str(note).strip()} if str(note).strip() else kept)
    return out


def sound(job: Job, check: Check | None = None) -> Draft:
    """The sound of a song whose words are written: the writer writes its style, what to keep out,
    how its uncommon words are said, and each section's note. Every line, the tempo, the key and the
    sections stay as they were, and so does who wrote the words. The file it replaces is kept in
    the job's work folder, named by its digest."""
    brief = _ready(job, "song")
    song = dict(job.read("song"))
    sections = list(song["sections"])
    fixed = ("title", "bpm", "key", "language", "vocal_gender", "instrumental")
    shown = {k: song[k] for k in fixed if k in song}
    shown["sections"] = [{k: s[k] for k in ("kind", "bars", "lines", "style") if k in s}
                         for s in sections]  # fmt: skip
    shown["sound it had"] = {k: song[k] for k in ("style", "avoid", "pronounce") if song.get(k)}
    text = prompts.load("song_brief").format(
        song=json.dumps(shown, indent=2, ensure_ascii=False),
        genre=genres.writer_text(brief),
        sound=prompts.load("song_sound").strip(),
        count=len(sections),
    )

    def accept(answer: Any) -> Draft:
        notes = answer.get("sections") if isinstance(answer, dict) else None
        if not isinstance(notes, list) or len(notes) != len(sections):
            raise ValueError(f"give one section style for each of the {len(sections)}, in order")
        style = str(answer.get("style") or "").strip()
        if not style:
            raise ValueError('give the song\'s "style"')
        out = {**song, "style": style, "avoid": str(answer.get("avoid") or "").strip()}
        out.pop("pronounce", None)
        if answer.get("pronounce"):
            out["pronounce"] = {str(w): str(v) for w, v in dict(answer["pronounce"]).items()}
        out["sections"] = _noted(sections, notes)
        return out

    new = _drafted(job, "song", text + _fixed(job, "song"), accept, check)
    set_aside(job, "song")
    job.write("song", new)
    return new


def set_aside(job: Job, contract: str) -> Path:
    """A written file moved into the job's work folder, named by its digest, so a new one can be
    written in its place and the old one is still there to read."""
    path = job.path(contract)
    before = path.read_bytes()
    job.work.mkdir(parents=True, exist_ok=True)
    kept = job.work / f"{contract}.{hashlib.sha256(before).hexdigest()[:12]}.json"
    kept.write_bytes(before)
    path.unlink()
    return kept
