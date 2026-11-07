"""RENDER -> QA. Automated checks before the human gate. Writes qa.json.

fail  blocks approval. warn  shows on the review card.
A contact sheet (one frame per beat plus the hook) is built for the human and,
when an LLM provider with vision is available, for a rubric-scored judge.
"""

from __future__ import annotations

import re

from . import bar, config, consistency, media, prompts, research, shots, timeline
from .jobfs import DOCUMENT_MEDIA, ContractError, CostCapExceeded, Job
from .providers import router

# Files that came from a person or the engine itself, so there is no model licence to read.
NO_LICENCE = {"operator", "kit", "chained", "clip", "track", "local"}


def _check(checks: list, cid: str, ok: bool, detail: str, severity: str = "fail") -> None:
    checks.append({"id": cid, "status": "pass" if ok else severity, "detail": detail})


def contact_sheet(job: Job, final, em: dict) -> str | None:
    """Every shot's first and last frame, at the piece's real shape. Whether it moved shows here."""
    out = timeline.shot_sheet(
        final, em.get("cuts", []), em["duration_sec"], job.work / "contact.jpg"
    )
    return out.name if out else None


def _promise_checks(data: dict, am: dict) -> list[dict]:
    """A shot that asked to move and did not. Only a person can accept that, by saying so on the job."""
    breaks = am.get("promise_breaks") or []
    if not breaks:
        return []
    from .publish import placeholder_assets

    forgiven = (data.get("brief") or {}).get("allow_stills") or placeholder_assets(am)
    named = ", ".join(b["beat_id"] for b in breaks)
    return [
        {
            "id": "delivery.motion_promise",
            "status": "warn" if forgiven else "fail",
            "detail": f"asked to move and did not: {named}",
        }
    ]


def licence_checks(am: dict) -> list[dict]:
    """What each model's terms ask of whoever releases this. A person reads and meets them."""
    unknown, limited, owed = set(), set(), set()
    for asset in am["assets"]:
        provider = asset.get("provider")
        if not provider or provider in NO_LICENCE:
            continue
        model = str(asset.get("model", "")).split(":")[0]
        terms = config.licence_for(provider, model)
        if not terms:
            unknown.add(f"{provider}/{model}")
            continue
        if terms.get("commercial") is False:
            limited.add(f"{provider}/{model}")
        owed.update(str(o) for o in terms.get("obligations") or [])
    out = []
    if unknown:
        detail = f"nobody has read the terms of {sorted(unknown)}"
        out.append({"id": "rights.model_licence", "status": "warn", "detail": detail})
    if limited:
        detail = f"terms not confirmed for commercial use: {sorted(limited)}"
        out.append({"id": "rights.commercial_use", "status": "warn", "detail": detail})
    if owed:
        out.append(
            {"id": "rights.obligations", "status": "warn", "detail": "; ".join(sorted(owed))}
        )
    return out


def _sound_checks(prof: dict, am: dict) -> list[dict]:
    """What a premium mix would have that this one lacks. Only a person can say if it matters."""
    if prof.get("delivery") != "mezzanine":
        return []
    out = []
    if not any(a.get("role") == "sfx" for a in am["assets"]):
        detail = "voice and music only: no sound of the place under the picture"
        out.append({"id": "sound.layers", "status": "warn", "detail": detail})
    lossy = bar._source_is_lossy(am)
    if lossy:
        detail = f"{lossy} reached the mix through lossy audio, which no master can win back"
        out.append({"id": "sound.source_quality", "status": "warn", "detail": detail})
    return out


def _plan_checks(data: dict, packet: dict) -> list[dict]:
    brief = data.get("brief") or {}
    found = shots.review(
        packet,
        budget=int(brief.get("max_video_beats", 3)),
        allow_stills=True,
        wants_video="video" in data.get("media", []),
    )
    return [{**p, "status": "warn"} for p in found]


def _cut_checks(final, em: dict) -> list[dict]:
    if len(em.get("cuts", [])) < 2:
        return []
    bad = [c for c in timeline.cut_report(final, em["cuts"]) if c["flagged"]]
    if not bad:
        return [{"id": "edit.cuts", "status": "pass", "detail": "no click or flash at any cut"}]
    spots = ", ".join(f"{c['at_sec']:.2f}s" for c in bad[:8])
    detail = f"{len(bad)} cuts have a click or a flash: {spots}"
    return [{"id": "edit.cuts", "status": "warn", "detail": detail}]


def _judge_script(packet: dict) -> str:
    return str(
        [
            {
                "id": b["id"],
                "line": b["text"],
                "cue": b.get("visual_cue", ""),
                "moves": b.get("visual_kind") == "video",
            }
            for b in packet["beats"]
        ]
    )


def _shape(prof: dict) -> str:
    width, height = prof.get("width", 1), prof.get("height", 1)
    return "vertical" if height > width else "square" if height == width else "landscape"


def _judged_shots(judge: dict) -> list[dict]:
    bad = [
        f"{s.get('id')}: {s.get('note') or 'see the sheet'}"
        for s in judge.get("shots") or []
        if s.get("moved") is False
        or s.get("geometry_ok") is False
        or s.get("matches_previous") is False
    ]
    if not judge.get("shots"):
        return []
    detail = "; ".join(bad)[:600] or "every shot read as it should"
    return [{"id": "judge.shots", "status": "warn" if bad else "pass", "detail": detail}]


def _kit_checks(job: Job, packet: dict, am: dict, sheet: str | None) -> list[dict]:
    """A stream job proves the lock held: first from the record, then by looking at the frames."""
    from .plan import extract_json

    try:
        locked = consistency.for_job(job)
    except ContractError as exc:
        return [{"id": "consistency.lock", "status": "fail", "detail": str(exc)[:500]}]
    if not locked:
        return []
    resolved, lock = locked
    checks = [{"id": "consistency.lock", "status": "pass", "detail": "kits match the job's lock"}]
    checks += consistency.recorded_checks(resolved, lock, packet, am)
    if am.get("kit_lock_sha256") != consistency.lock_sha256(job):
        checks.append(
            {"id": "consistency.manifest", "status": "fail", "detail": "assets predate this lock"}
        )
    unseen = {"id": "consistency.vision", "status": "warn"}
    if not sheet:
        return [*checks, {**unseen, "detail": "no contact sheet; a human compares the frames"}]
    text = prompts.load("qa_consistency").format(
        context=consistency.judge_brief(resolved, lock["cast"]),
        script=[b["text"] for b in packet["beats"]],
    )
    images = [*consistency.judge_images(resolved, lock["cast"]), job.work / sheet]
    try:
        _, res = router.generate(
            job, "llm", "llm", text, images=images, max_tokens=800, note="qa-consistency"
        )
        return [*checks, *consistency.judge_checks(extract_json(res.text))]
    except CostCapExceeded:
        raise
    except LookupError:
        return [*checks, {**unseen, "detail": "no vision model ready; a human compares the frames"}]
    except Exception as exc:  # the human gate still stands, and the warning says so
        return [*checks, {**unseen, "detail": f"vision check failed: {exc}"[:300]}]


def run_file(job: Job) -> dict:
    """Checks that need only the delivered file and its record, for files the engine did not render."""
    data, am, final = job.job, job.read("asset_manifest"), job.artifact()
    checks: list[dict] = []
    metrics: dict = {}
    if data.get("stream"):
        checks.append(
            {
                "id": "consistency.outside_file",
                "status": "warn",
                "detail": "made outside the engine; no reference was enforced, so a human compares it",
            }
        )
    if not final.exists():
        _check(checks, "render.exists", False, f"{final.name} missing")
        report = {
            "schema_version": "0.1",
            "job_id": data["job_id"],
            "passed": False,
            "checks": checks,
        }
        job.write("qa", report)
        return report
    prof = config.profile(
        data.get("profile") or ("short-9x16" if final.suffix == ".mp4" else "podcast")
    )
    info = media.summarize(final)
    dur = media.duration(final)
    metrics.update(info, duration_sec=round(dur, 3))
    _check(checks, "duration", dur > 0, f"{dur:.2f}s")
    if final.suffix == ".mp4":
        _check(
            checks,
            "frame.size",
            (info.get("width"), info.get("height")) == (prof.get("width"), prof.get("height")),
            f"{info.get('width')}x{info.get('height')} vs {prof.get('width')}x{prof.get('height')}",
            "warn",
        )
        black = media.blackdetect(final, 0.5)
        _check(checks, "picture.black_frames", not black, f"{len(black)} black spans ≥0.5s")
    if final.suffix != ".mp4" or info.get("sample_rate_hz"):
        loud = media.loudness(final)
        metrics.update(loud)
        tgt, tp_max = prof.get("target_lufs", -14), prof.get("true_peak_dbtp_max", -1)
        il, tp = loud["integrated_lufs"], loud["true_peak_dbtp"]
        _check(
            checks,
            "audio.loudness",
            il is not None and abs(il - tgt) <= 1.0,
            f"{il} LUFS (target {tgt}±1)",
            "warn",
        )
        _check(
            checks,
            "audio.true_peak",
            tp is not None and tp <= tp_max + 0.3,
            f"{tp} dBTP (max {tp_max})",
        )
    synthetic = any(a.get("synthetic") for a in am["assets"])
    metrics["synthetic"] = synthetic
    _check(
        checks,
        "disclosure.synthetic_flag",
        not synthetic or data.get("synthetic_disclosure", True),
        "synthetic assets present; publish must set the platform AI label",
    )
    _check(
        checks,
        "rights.assets",
        all(a.get("rights") in ("owned", "licensed", "funded-brief") for a in am["assets"]),
        "every asset carries rights",
    )
    checks.append(
        {
            "id": "judge.content",
            "status": "warn",
            "detail": "no content review for this file; human reviews it",
        }
    )
    from .publish import sha256_file

    report = {
        "schema_version": "0.1",
        "job_id": data["job_id"],
        "passed": all(c["status"] != "fail" for c in checks),
        "checks": checks,
        "metrics": metrics,
        "artifacts": {"video" if final.suffix == ".mp4" else "audio": final.name},
        "artifacts_sha256": {"video" if final.suffix == ".mp4" else "audio": sha256_file(final)},
    }
    job.write("qa", report)
    return report


def run_song(job: Job) -> dict:
    """A song: its level blocks, its readings inform, and a person listens. Bound to the exact file."""
    from . import songs
    from .publish import sha256_file

    data, final = job.job, job.artifact()
    checks: list[dict] = []
    summary: dict = {}
    if final.exists():
        checks, summary = songs.checks(job)
    _check(checks, "render.exists", final.exists(), final.name)
    manifest = job.read("asset_manifest")
    _check(
        checks,
        "rights.assets",
        all(a.get("rights") in ("owned", "licensed", "funded-brief") for a in manifest["assets"]),
        "every asset carries rights",
    )
    checks.extend(licence_checks(manifest))
    report = {
        "schema_version": "0.1",
        "job_id": data["job_id"],
        "passed": all(c["status"] != "fail" for c in checks),
        "checks": checks,
        "artifacts": {"audio": final.name},
        "artifacts_sha256": {"audio": sha256_file(final)} if final.exists() else {},
    }
    if summary:
        report["bar"] = summary
    job.write("qa", report)
    return report


def run_document(job: Job) -> dict:
    """A comic or a book: its own checks, bound to the exact file like any other piece."""
    from . import comic, story
    from .publish import sha256_file

    data, final = job.job, job.artifact()
    made_for = comic if "comic" in data.get("media", []) else story
    checks = made_for.checks(job) if final.exists() else []
    _check(checks, "render.exists", final.exists(), final.name)
    manifest = job.read("asset_manifest")
    _check(
        checks,
        "rights.assets",
        all(a.get("rights") in ("owned", "licensed", "funded-brief") for a in manifest["assets"]),
        "every asset carries rights",
    )
    report = {
        "schema_version": "0.1",
        "job_id": data["job_id"],
        "passed": all(c["status"] != "fail" for c in checks),
        "checks": checks,
        "artifacts": {"document": final.name},
        "artifacts_sha256": {"document": sha256_file(final)} if final.exists() else {},
    }
    job.write("qa", report)
    return report


def run(job: Job) -> dict:
    if "song" in job.job.get("media", []):
        return run_song(job)
    if any(kind in job.job.get("media", []) for kind in DOCUMENT_MEDIA):
        return run_document(job)
    if not job.has("edit_manifest") or not job.read("edit_manifest").get("cuts"):
        return run_file(job)
    data = job.job
    em = job.read("edit_manifest")
    packet = job.read("script_packet")
    am = job.read("asset_manifest")
    final = job.work / "final.mp4"
    checks: list[dict] = []
    metrics: dict = {}

    if not final.exists():
        _check(checks, "render.exists", False, "final.mp4 missing")
        report = {
            "schema_version": "0.1",
            "job_id": data["job_id"],
            "passed": False,
            "checks": checks,
        }
        job.write("qa", report)
        return report

    prof = em["profile"]
    info = media.summarize(final)
    dur = media.duration(final)
    metrics.update(info, duration_sec=round(dur, 3))
    _check(
        checks,
        "frame.size",
        (info.get("width"), info.get("height")) == (prof["width"], prof["height"]),
        f"{info.get('width')}x{info.get('height')} vs {prof['width']}x{prof['height']}",
    )
    _check(
        checks, "frame.fps", abs(info.get("fps", 0) - prof["fps"]) < 0.5, f"{info.get('fps')} fps"
    )
    _check(
        checks,
        "duration",
        abs(dur - em["duration_sec"]) <= 0.35,
        f"{dur:.2f}s vs plan {em['duration_sec']:.2f}s",
    )
    if prof.get("aspect") == "9:16":
        _check(
            checks, "duration.short_form", dur <= 179, f"{dur:.1f}s (Shorts limit 3 min)", "warn"
        )

    if em.get("audio"):
        loud = media.loudness(final)
        metrics.update(loud)
        tgt, tp_max = prof.get("target_lufs", -14), prof.get("true_peak_dbtp_max", -1)
        il, tp = loud["integrated_lufs"], loud["true_peak_dbtp"]
        _check(
            checks,
            "audio.loudness",
            il is not None and abs(il - tgt) <= 1.0,
            f"{il} LUFS (target {tgt}±1)",
        )
        _check(
            checks,
            "audio.true_peak",
            tp is not None and tp <= tp_max + 0.3,
            f"{tp} dBTP (max {tp_max})",
        )
        dead = [s for s in media.silencedetect(final, -45, 1.2) if s[1] - s[0] >= 1.2]
        _check(checks, "audio.dead_air", not dead, f"{len(dead)} silent spans ≥1.2s", "warn")

    black = media.blackdetect(final, 0.5)
    _check(checks, "picture.black_frames", not black, f"{len(black)} black spans ≥0.5s")

    # pacing: longest stretch without a visual change
    starts = [c.get("start_sec", 0) for c in em.get("cuts", [])] + [em["duration_sec"]]
    longest = max((b - a for a, b in zip(starts, starts[1:])), default=0)
    metrics["longest_shot_sec"] = round(longest, 2)
    stills = all(not c["source"].endswith(".video") for c in em.get("cuts", []))
    if prof.get("delivery") != "mezzanine":
        _check(
            checks,
            "pacing.pattern_interrupt",
            longest <= (5.0 if stills else 6.5),
            f"longest shot {longest:.1f}s",
            "warn",
        )

    # hook timing
    caps = em.get("captions") or em.get("closed_captions") or []
    first = caps[0]["start_sec"] if caps else None
    # a film's opening is its design, so it does not count against the first word
    opening = float(config.profile(job.job.get("profile") or "").get("open_sec", 0.0))
    if caps or am.get("words"):  # edits of silent footage carry no captions to time
        _check(
            checks,
            "hook.first_word",
            first is not None and first <= 0.6 + opening,
            f"first caption at {first}s",
            "warn",
        )
    hook_words = len(packet["beats"][0]["text"].split())
    _check(checks, "hook.length", hook_words <= 14, f"hook line {hook_words} words", "warn")

    # caption coverage of spoken words
    words = am.get("words", [])
    if words:
        covered = sum(
            1
            for w in words
            if any(c["start_sec"] - 0.05 <= w["start_sec"] <= c["end_sec"] for c in caps)
        )
        cov = covered / len(words)
        metrics["caption_coverage"] = round(cov, 3)
        _check(checks, "captions.coverage", cov >= 0.95, f"{cov:.0%} of words captioned")
        est = sum(1 for w in words if w.get("confidence", 1) < 0.8) / len(words)
        _check(
            checks,
            "captions.timing_source",
            est < 0.5,
            "word timings estimated (local voice); use a timestamped voice or transcribe pass",
            "warn",
        )

    # claims
    bad = [
        c["id"] for c in packet.get("claims", []) if not re.match(r"https?://", c.get("source", ""))
    ]
    _check(
        checks,
        "claims.sourced",
        not bad,
        f"claims without URL sources: {bad}" if bad else "all claims have URLs",
        "warn",
    )
    checks.extend(research.claim_checks(job, packet))
    checks.extend(_promise_checks(data, am))
    checks.extend(_plan_checks(data, packet))
    checks.extend(_sound_checks(prof, am))
    checks.extend(_cut_checks(final, em))

    # disclosure
    synthetic = any(a.get("synthetic") for a in am["assets"])
    metrics["synthetic"] = synthetic
    _check(
        checks,
        "disclosure.synthetic_flag",
        not synthetic or data.get("synthetic_disclosure", True),
        "synthetic assets present; publish must set the platform AI label",
    )

    # stock credits must reach the post, not just the job folder
    if (job.folder / "stock.json").exists():
        from .stock import credits

        desc = (packet.get("publish") or {}).get("description", "")
        _check(
            checks,
            "rights.stock_credit",
            credits(job) in desc,
            "stock credit line present in publish description",
        )

    # rights
    rights_ok = all(
        a.get("rights", data.get("rights")) in ("owned", "licensed", "funded-brief")
        for a in am["assets"]
    )
    _check(checks, "rights.assets", rights_ok, "every asset carries rights")
    checks.extend(licence_checks(am))

    sheet = contact_sheet(job, final, em)
    checks.extend(_kit_checks(job, packet, am, sheet))
    judge = None
    try:
        if sheet:
            from .plan import extract_json

            _, res = router.generate(
                job,
                "llm",
                "llm",
                prompts.load("qa_rubric").format(shape=_shape(prof), script=_judge_script(packet)),
                images=[job.work / sheet],
                max_tokens=1600,
                note="qa-judge",
            )
            judge = extract_json(res.text)
            checks.extend(_judged_shots(judge))
            _check(
                checks,
                "judge.verdict",
                judge.get("verdict") != "kill",
                f"judge: {judge.get('verdict')}",
            )
            _check(
                checks,
                "judge.policy",
                judge.get("policy_risk") != "high",
                f"policy risk {judge.get('policy_risk')}",
            )
    except CostCapExceeded:
        raise
    except LookupError:
        checks.append(
            {
                "id": "judge.vision",
                "status": "warn",
                "detail": "no LLM provider ready; human reviews contact sheet",
            }
        )
    except Exception as exc:  # judge is advisory
        checks.append(
            {"id": "judge.vision", "status": "warn", "detail": f"judge error: {exc}"[:300]}
        )

    studio_bar = bar.measure_job(job.work, em, am)
    checks.extend(bar.as_checks(studio_bar))
    passed = all(c["status"] != "fail" for c in checks)
    from .publish import sha256_file

    master = job.work / "final.master.mov"
    report = {
        "schema_version": "0.1",
        "job_id": data["job_id"],
        "passed": passed,
        "checks": checks,
        "metrics": metrics,
        "bar": studio_bar,
        "artifacts": {
            k: v
            for k, v in {
                "video": "final.mp4",
                "master": master.name if master.exists() else None,
                "audio": "final.m4a" if (job.work / "final.m4a").exists() else None,
                "thumbnail": "thumb.jpg",
                "contact_sheet": sheet,
                "captions_srt": "captions.srt" if (job.work / "captions.srt").exists() else None,
            }.items()
            if v
        },
    }
    report["artifacts_sha256"] = {"video": sha256_file(final)}
    if master.exists():
        report["artifacts_sha256"]["master"] = sha256_file(master)
    if judge:
        report["judge"] = judge
    job.write("qa", report)
    return report
