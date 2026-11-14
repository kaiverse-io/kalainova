"""RENDER -> QA. Automated checks before the human gate. Writes qa.json.

fail  blocks approval. warn  shows on the review card.
A contact sheet (one frame per beat plus the hook) is built for the human and,
when an LLM provider with vision is available, for a rubric-scored judge.
"""

from __future__ import annotations

import re

from . import bar, config, media, prompts, qachecks, research, timeline
from .jobfs import DOCUMENT_MEDIA, CostCapExceeded, Job
from .providers import router


def _check(checks: list, cid: str, ok: bool, detail: str, severity: str = "fail") -> None:
    checks.append({"id": cid, "status": "pass" if ok else severity, "detail": detail})


def contact_sheet(job: Job, final, em: dict) -> str | None:
    """Every shot's first and last frame, at the piece's real shape. Whether it moved shows here."""
    out = timeline.shot_sheet(
        final, em.get("cuts", []), em["duration_sec"], job.work / "contact.jpg"
    )
    return out.name if out else None


def motion_sheets(job: Job, final, em: dict) -> tuple[str | None, str | None]:
    """A strip of frames across every shot, and a strip of frames either side of every cut."""
    motion = timeline.motion_sheet(
        final, em.get("cuts", []), em["duration_sec"], job.work / "motion.jpg"
    )
    cuts = em.get("cuts", [])
    report = timeline.cut_report(final, cuts) if len(cuts) > 1 else []
    around = timeline.cut_sheet(final, report, job.work / "cuts.jpg")
    return (motion.name if motion else None), (around.name if around else None)


def _keep_findings(job: Job, judge: dict) -> None:
    """The judge's faults, in a file a retake can read. An agent's findings are never overwritten."""
    if job.has("findings") and job.read("findings").get("source") != "judge":
        return
    found = qachecks.findings_from_judge(job.id, judge)
    if found:
        job.write("findings", found)
    else:
        job.path("findings").unlink(missing_ok=True)


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
    checks.extend(qachecks.licence_checks(manifest))
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
    checks.extend(qachecks.promise_checks(data, am))
    checks.extend(qachecks.placeholder_checks(am))
    checks.extend(qachecks.plan_checks(data, packet))
    checks.extend(qachecks.sound_checks(prof, am))
    checks.extend(qachecks.cut_checks(final, em))

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
    checks.extend(qachecks.licence_checks(am))

    sheet = contact_sheet(job, final, em)
    motion, cut_strip = motion_sheets(job, final, em)
    checks.extend(qachecks.safe_zone_checks(job, data.get("profile") or "short-9x16"))
    checks.extend(qachecks.cuts_on_beat_checks(job, em))
    checks.extend(qachecks.kit_checks(job, packet, am, sheet))
    judge = None
    try:
        failed_beats = qachecks.failed_beats(packet, checks)
        passed_beats = [b for b in packet.get("beats", []) if b["id"] not in failed_beats]
        if sheet and passed_beats:
            from .plan import extract_json

            cap = "judge" if router.available(job, "judge") else "llm"
            pref = config.preference(cap, job.job)
            prov = pref[0] if pref else "fake"
            judge_model = config.model_for(prov, "judge") or config.model_for(prov, "llm")
            _, res = router.generate(
                job,
                cap,
                cap,
                prompts.load("qa_rubric").format(
                    shape=qachecks.shape(prof),
                    script=qachecks.judge_script(packet, exclude_beats=failed_beats),
                ),
                images=[job.work / sheet, *([job.work / motion] if motion else [])],
                max_tokens=1600,
                model=judge_model,
                note="qa-judge",
            )
            judge = extract_json(res.text)
            _keep_findings(job, judge)
            checks.extend(qachecks.judged_shots(judge))
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
                "motion_strip": motion,
                "cut_strip": cut_strip,
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
