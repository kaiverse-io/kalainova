"""A camera test: one shot made on several models, side by side, before a shoot. A shot that sings
is made on models that sing it from its still and its line (`sing_models`), the line the same for
each, so the rows differ only in how each model sings.

Every bench take goes through the router and the take store like any other take, so it carries its
model, seed, cost, and how it read. It is marked as a bench take, which never replaces the take a
piece uses and does not count against a shot's take limits. Every model gets the same prompt, the
same start frame, and the same seeds, so a difference between rows comes from the model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import (
    benchreport,
    config,
    consistency,
    knowledge,
    media,
    shotmake,
    shots,
    takejudges,
    takes,
    timeline,
)
from .blobstore import sha256_file
from .editor import singing
from .jobfs import ContractError, Job
from .providers import base, router
from .providers.contract import (
    Billable,
    LipsyncRequest,
    Pin,
    Request,
    Result,
    SingRequest,
    VideoRequest,
)

Say = Callable[[str], None]
REPAINT = "+"  # "made-by+repainted-by": one model makes the shot, another redraws its mouth


@dataclass
class Row:
    model: str
    provider: str
    per_take: float
    own_price: bool  # the price table has a row for this model, not just for the capability
    repaint: str = ""  # the model that redraws the mouth to the line afterwards, when one does
    repaint_provider: str = ""


def split(model: str) -> tuple[str, str]:
    """The model that makes the shot, and the one that repaints its mouth ("" when none does)."""
    made, _, repaint = model.partition(REPAINT)
    return made.strip(), repaint.strip()


def _repainter(job: Job) -> str:
    names = config.preference("lipsync", job.job)
    if not names:
        raise ContractError(f"{job.id}: no provider is listed for lipsync, so nothing can repaint")
    return names[0]


def parse_models(text: str) -> list[str]:
    """The models to make the shot on. One is enough to add a row to a bench already run."""
    found = list(dict.fromkeys(m.strip() for m in text.split(",") if m.strip()))
    if not found:
        raise ContractError("a bench names its models: --models a,b")
    return found


def _provider_of(job: Job, model: str, capability: str = "video") -> str:
    """The first provider in the job's list for this capability that names this model."""
    names = config.preference(capability, job.job)
    known: list[str] = []
    for name in names:
        try:
            offered = base.get(name).models(capability)
        except KeyError:
            continue
        if model in offered:
            return name
        known += offered
    raise ContractError(
        f"{job.id}: {model} is not under {capability}_models for any provider this job uses; "
        f"known: {', '.join(sorted(set(known))) or 'none'}"
    )


@dataclass
class _Setup:
    beat: dict[str, Any]
    span: float
    still: Path
    prompt: str
    aspect: str
    kw: shotmake.Held
    resolved: Any = None
    lock: dict[str, Any] | None = None
    line: Path | None = None  # the shot's line of the vocal stem, when it sings

    @property
    def capability(self) -> str:
        return "sing" if self.line else "video"


def _inputs(setup: _Setup) -> dict[str, str]:
    """The hashes of what every model on the bench was given: the still, and the line it sings."""
    found = {"still": sha256_file(setup.still)}
    return found | ({"line": sha256_file(setup.line)} if setup.line else {})


def _setup(job: Job, shot: str) -> _Setup:
    data = job.job
    packet = job.read("script_packet")
    beat = next((b for b in packet["beats"] if b["id"] == shot), None)
    if not beat:
        raise ContractError(f"{job.id}: no shot {shot}")
    if beat.get("visual_kind") != "video":
        raise ContractError(f"{job.id}: {shot} is a still, so there is nothing to bench")
    still = job.work / "beats" / f"{shot}.still.png"
    if not still.exists():
        raise ContractError(
            f"{job.id}: {shot} has no start frame yet. Make the stills first (the stills package, "
            "or assets with brief.max_video_beats set to 0), so every model starts from it"
        )
    timeline = job.read("asset_manifest")["timeline"] if job.has("asset_manifest") else []
    placed = [s["end_sec"] - s["start_sec"] for s in timeline if s["beat_id"] == shot]
    span = placed[0] if placed else float(beat.get("duration_sec") or 0)  # the stills alone: plan
    locked = consistency.for_job(job)
    resolved, lock = locked if locked else (None, {})
    kw = shotmake.shot_kw(resolved, lock, "video", beat, start=still)
    prompt = shots.motion_prompt(
        packet,
        beat,
        shotmake.style(data),
        has_start_image=True,
        limit=shots.word_limit(config.preference("video", data)),
    )
    prof = config.profile(data.get("profile") or "short-9x16")
    aspect = str(prof.get("aspect", "9:16"))
    line = job.work / "beats" / f"{shot}.voice.wav" if beat.get("sings") else None
    if line and singing.sung_line(job, beat, line) < singing.NO_VOICE:
        raise ContractError(f"{job.id}: {shot} is not sung over its span, so it has no line")
    return _Setup(beat, float(span), still, prompt, aspect, kw, resolved, lock, line)


def ready(job: Job, shot: str) -> bool:
    """Whether the shot has the still and the length a bench starts from, so nothing before it
    needs making, or rehearsing."""
    try:
        return _setup(job, shot).span > 0
    except ContractError:
        return False


def _request_for(setup: _Setup, provider: str, model: str, say: Say) -> shotmake.Held:
    """What one model is given, worked out for that model rather than the stream's pinned one.

    A model that takes references gets the kit's, with the still as its first frame or its first
    reference by what it accepts; a model that takes none starts from the frame alone, said aloud.
    """
    pin = Pin(provider=provider, model=model)
    if not setup.kw.references:
        return shotmake.Held(pin=pin)
    if setup.line and base.get(provider).inputs("sing", model).references:
        return shotmake.Held(setup.kw.references, pin)  # the still first, then the kit
    if setup.line or not base.get(provider).inputs("video", model).references:
        say(f"{model} cannot take this shot's references, so it starts from the frame alone")
        return shotmake.Held(pin=pin)
    lock = dict(setup.lock or {})
    lock["generators"] = {
        **(lock.get("generators") or {}),
        "video": {"provider": provider, "model": model},
    }
    held = shotmake.shot_kw(setup.resolved, lock, "video", setup.beat, start=setup.still)
    return shotmake.Held(held.references, pin)


def settings(provider: str, model: str, line: float) -> str:
    """What else a sung row was given that differs between rows: its tier, any padding, and
    whether the still was its first frame, so rows are not read as alike when they were not."""
    spec = config.sing_spec(provider, model) or {}
    said = []
    tier = (spec.get("extra") or {}).get("resolution")
    if tier:
        said.append(f"at {tier}")
    least = float(spec.get("min_audio_sec") or 0)
    if least > line:
        said.append(f"the line padded to {least:g} s and cut back")
    if spec.get("images_param"):
        said.append("the still as a reference, not a fixed first frame")
    return "".join(f", {part}" for part in said)


def conditioning(provider: str, model: str, held: shotmake.Held, sings: bool = False) -> str:
    """What a bench take was given, in words, so takes with different inputs are not read alike."""
    if sings:
        pictures = f", {len(held.references)} kit picture(s)" if held.references else ""
        return f"the still{pictures} and its line of the vocal"
    if not held.references:
        return "the start frame only"
    kit = len(held.references)
    if base.get(provider).inputs("video", model).start_with_references:
        return f"the start frame and {kit} kit reference(s)"
    return f"{kit} reference(s), the still among them; no start frame"


def _not_made_before(job: Job, shot: str, model: str, prompt: str, again: bool) -> None:
    """A bench row the same as one already made, on the same model, prompt, and still, would buy
    the same test twice. It is made again only when asked (`--again`)."""
    if again:
        return
    entry = takes.load(job)["shots"].get(shot) or {}
    same = [
        t["n"]
        for t in entry.get("takes", [])
        if t.get("bench") and t.get("model") == model and t.get("prompt") == prompt
    ]
    if same:
        raise ContractError(
            f"{job.id}: {shot} was already benched on {model} with this prompt (take "
            f"{', '.join(map(str, same))}); change the prompt, or ask for another take with --again"
        )


def _size_warning(job: Job, setup: _Setup, provider: str, model: str, say: Say) -> None:
    """Said before spend: a model known to make a character shot under the profile's size floor.
    Known from config (`short_side` on its sing row) or from a take it made before."""
    prof = config.profile(job.job.get("profile") or "short-9x16")
    floor = int(prof.get("character_source_min_px") or 0)
    if not floor or not setup.beat.get("cast"):
        return
    made = split(model)[0]
    side = (config.sing_spec(provider, made) or {}).get("short_side") if setup.line else None
    if side is None:
        for entry in takes.load(job)["shots"].values():
            for take in entry.get("takes", []):
                r = take.get("readings") or {}
                if take.get("model") == model and r.get("width") and r.get("height"):
                    side = min(int(r["width"]), int(r["height"]))
    if side is not None and int(side) < floor:
        say(
            f"{model} makes {side} px on its short side, under this profile's {floor} px floor: "
            "its takes go to a person and are not picked"
        )


def estimate(
    job: Job, shot: str, models: list[str], count: int, say: Say = print, again: bool = False
) -> list[Row]:
    """What each model's takes should cost, said before anything is spent. Refuses over the cap."""
    setup = _setup(job, shot)
    rows = []
    table = config.studio().get("prices") or {}
    for model in models:
        made, repaint = split(model)
        _not_made_before(job, shot, model, setup.prompt, again)
        if repaint and not setup.line:
            raise ContractError(
                f"{job.id}: {shot} does not sing, so there is no line to repaint to"
            )
        capability = "video" if repaint else setup.capability
        provider = _provider_of(job, made, capability)
        _size_warning(job, setup, provider, model, say)
        request = _request_for(replace(setup, line=None) if repaint else setup, provider, made, say)
        asked = Billable(
            capability=capability,
            duration=setup.span,
            image=True,
            references=bool(request.references),
        )
        quote = router.quote(job, asked, only=[provider], pin=request.pin)
        if quote is None:
            raise ContractError(f"{job.id}: {provider} is not ready, so {made} cannot be tested")
        if quote[1] is None:
            raise ContractError(f"{job.id}: no price for {made}, so its cost cannot be estimated")
        per, by = quote[1], ""
        if repaint:  # the repaint is billed on the clip the first model makes
            by = _repainter(job)
            clip = base.get(provider).billed_seconds(asked, made)
            redo = Billable(capability="lipsync", duration=clip)
            second = router.quote(job, redo, only=[by], pin=Pin(provider=by, model=repaint))
            if second is None or second[1] is None:
                raise ContractError(f"{job.id}: no price for {repaint} on {by}")
            per += second[1]
        own = bool((table.get(provider) or {}).get(made))
        rows.append(Row(model, provider, per, own, repaint, by))
    total = sum(r.per_take for r in rows) * count
    for r in rows:
        note = "" if r.own_price else "  (no price of its own: the generic video rate)"
        say(f"{r.model}: about ${r.per_take * count:.2f} for {count} take(s){note}")
    say(f"bench total: about ${total:.2f}")
    cap = job.job.get("cost_cap")
    if total and cap is None:
        raise ContractError(f"{job.id}: a bench spends money, so the job needs a cost_cap")
    if cap is not None and total > float(cap) - job.committed():
        left = max(float(cap) - job.committed(), 0.0)
        raise ContractError(
            f"{job.id}: the bench is estimated at ${total:.2f} and the job has ${left:.2f} left "
            "under its cap; name fewer models, take fewer takes, or raise cost_cap"
        )
    return rows


def run(
    job: Job, shot: str, models: list[str], count: int = 1, say: Say = print, again: bool = False
) -> dict[str, Any]:
    """Make the shot on each model, and write one sheet with a row per model."""
    if count < 1:
        raise ContractError("a bench makes at least one take of each model")
    rows = estimate(job, shot, models, count, say, again)
    setup = _setup(job, shot)
    made: list[dict[str, Any]] = []
    failed: dict[str, str] = {}
    for row in rows:
        made_by = split(row.model)[0]
        part = replace(setup, line=None) if row.repaint else setup
        request = _request_for(part, row.provider, made_by, lambda _: None)
        for i in range(count):
            n = takes.next_take_number(job, shot)

            def make(
                seed: int, dst: Path, request: shotmake.Held = request, row: Row = row
            ) -> tuple[Any, Any]:
                plain = VideoRequest(
                    prompt=setup.prompt,
                    dst=_unsung(dst) if row.repaint else dst,
                    duration=setup.span,
                    aspect=setup.aspect,
                    start=setup.still,
                    seed=seed,
                    sound=False,
                    references=request.references,
                    pin=request.pin,
                )
                if row.repaint:
                    return _repainted(job, setup, row, plain, dst)
                clip: Request = plain
                if setup.line:  # the same line for every model, sung in the call that makes it
                    clip = SingRequest(
                        prompt=setup.prompt,
                        still=setup.still,
                        audio=setup.line,
                        dst=dst,
                        aspect=setup.aspect,
                        references=request.references,
                        seed=seed,
                        pin=request.pin,
                    )
                return router.generate(job, clip, only=[row.provider], note=f"bench {row.model}")

            try:
                take = takes.attempt(
                    job,
                    shot,
                    n,
                    suffix=".mp4",
                    make=make,
                    assess=takejudges.judged_on_camera(
                        takejudges.judged_sung(takes.assess_clip, setup.line)
                        if setup.line
                        else takes.assess_clip,
                        setup.beat,
                    ),
                    prompt=setup.prompt,
                    seed=takes.seed_for(setup.prompt, i),
                    made_with=knowledge.stamp(setup.beat, _inputs(setup)),
                    extra={
                        "bench": True,
                        "conditioning": conditioning(
                            row.provider, made_by, request, bool(setup.line) and not row.repaint
                        )
                        + (
                            f", then its mouth repainted to the line by {row.repaint}"
                            if row.repaint
                            else ""
                        )
                        + (
                            settings(row.provider, row.model, media.duration(setup.line))
                            if setup.line and not row.repaint
                            else ""
                        ),
                    },
                )
            except RuntimeError as exc:
                failed[row.model] = str(exc)[:300]
                say(f"{row.model}: no take: {exc}")
                break
            made.append(take)
            say(f"{row.model} take {take['n']}, given {take['conditioning']}: {_reading(take)}")
    entry = takes.load(job)["shots"].get(shot) or {}
    benched = [t for t in entry.get("takes", []) if t.get("bench")]  # every row so far
    sheet = _sheet(job, shot, benched)
    report = benchreport.write(job, shot) if benched else None
    if report:
        say(f"watch them: {report['video']}")
        hidden = "the readings and the pick are kept until a person gives a verdict on these takes"
        say(f"{report['status']}: {report['reason']}" if report["shown"] else hidden)
    return {"takes": made, "failed": failed, "sheet": sheet, "report": report}


def _unsung(dst: Path) -> Path:
    return dst.with_name(f"{dst.stem}.unsung{dst.suffix}")


def _repainted(
    job: Job, setup: _Setup, row: Row, clip: VideoRequest, dst: Path
) -> tuple[Any, Result]:
    """The shot made as a plain clip, then its mouth redrawn to the line: one take, both costs."""
    assert setup.line is not None
    _, made = router.generate(job, clip, only=[row.provider], note=f"bench {split(row.model)[0]}")
    pin = Pin(provider=row.repaint_provider, model=row.repaint)
    redo = LipsyncRequest(video=clip.dst, audio=setup.line, dst=dst, pin=pin)
    provider, res = router.generate(
        job, redo, only=[row.repaint_provider], note=f"bench {row.model}"
    )
    both = replace(res, cost=float(made.cost or 0) + float(res.cost or 0), model=row.model,
                   seed=made.seed, sent=made.sent)  # fmt: skip
    return provider, both


def _reading(take: dict[str, Any]) -> str:
    readings = {k: v for k, v in (take.get("readings") or {}).items() if k != "score"}
    state = "moves" if take["ok"] else "MISSES the motion promise"
    cost = f", ${take['cost']:.2f}" if take.get("cost") else ""
    return f"{state} {readings}{cost}, seed {take['seed']}"


def _sheet(job: Job, shot: str, made: list[dict[str, Any]]) -> Path | None:
    if not made:
        return None
    rows = [
        (
            f"{t['model']}  take {t['n']}  given {t.get('conditioning', '?')}  {_reading(t)}",
            job.work / t["file"],
        )
        for t in made
    ]
    folder = job.work / "bench"
    folder.mkdir(exist_ok=True)
    return timeline.bench_sheet(rows, folder / f"{shot}.jpg")
