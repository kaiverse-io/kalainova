"""RENDER -> QA. Automated checks before the human gate. Writes qa.json.

fail  blocks approval. warn  shows on the review card.
A contact sheet (one frame per beat plus the hook) is built for the human and,
when an LLM provider with vision is available, for a rubric-scored judge.
"""

from __future__ import annotations

import re

from . import config, media
from .jobfs import CostCapExceeded, Job
from .providers import router

RUBRIC = """You are the quality gate of a content studio. Score this short vertical video from its contact sheet
and script. Return JSON only: {"hook": 0-10, "visual_quality": 0-10, "clarity": 0-10, "originality": 0-10,
"policy_risk": "none|low|high", "issues": ["..."], "verdict": "ship|fix|kill"}.
Kill anything that looks mass-produced, misleading, uses real people's likeness, brands, or garbled AI text."""


def _check(checks: list, cid: str, ok: bool, detail: str, severity: str = "fail") -> None:
    checks.append({"id": cid, "status": "pass" if ok else severity, "detail": detail})


def contact_sheet(job: Job, final, em: dict) -> str | None:
    work = job.work
    times = [0.4] + [c.get("start_sec", 0) + 0.6 for c in em.get("cuts", [])[1:]]
    frames = []
    for i, t in enumerate(times[:12]):
        f = work / f"qa_frame_{i:02d}.jpg"
        try:
            media.frame_at(final, min(t, em["duration_sec"] - 0.1), f)
            frames.append(f)
        except media.MediaError:
            pass
    if not frames:
        return None
    from PIL import Image
    thumbs = [Image.open(f).resize((270, 480)) for f in frames]
    cols = min(6, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 270, rows * 480), (0, 0, 0))
    for i, im in enumerate(thumbs):
        sheet.paste(im, ((i % cols) * 270, (i // cols) * 480))
    out = work / "contact.jpg"
    sheet.save(out, quality=85)
    for f in frames:
        f.unlink(missing_ok=True)
    return "contact.jpg"


def run_file(job: Job) -> dict:
    """Checks that need only the delivered file and its record, for files the engine did not render."""
    data, am, final = job.job, job.read("asset_manifest"), job.artifact()
    checks: list[dict] = []
    metrics: dict = {}
    if not final.exists():
        _check(checks, "render.exists", False, f"{final.name} missing")
        report = {"schema_version": "0.1", "job_id": data["job_id"], "passed": False, "checks": checks}
        job.write("qa", report)
        return report
    prof = config.profile(data.get("profile") or ("short-9x16" if final.suffix == ".mp4" else "podcast"))
    info = media.summarize(final)
    dur = media.duration(final)
    metrics.update(info, duration_sec=round(dur, 3))
    _check(checks, "duration", dur > 0, f"{dur:.2f}s")
    if final.suffix == ".mp4":
        _check(checks, "frame.size", (info.get("width"), info.get("height")) == (prof.get("width"), prof.get("height")),
               f"{info.get('width')}x{info.get('height')} vs {prof.get('width')}x{prof.get('height')}", "warn")
        black = media.blackdetect(final, 0.5)
        _check(checks, "picture.black_frames", not black, f"{len(black)} black spans ≥0.5s")
    if final.suffix != ".mp4" or info.get("sample_rate_hz"):
        loud = media.loudness(final)
        metrics.update(loud)
        tgt, tp_max = prof.get("target_lufs", -14), prof.get("true_peak_dbtp_max", -1)
        il, tp = loud["integrated_lufs"], loud["true_peak_dbtp"]
        _check(checks, "audio.loudness", il is not None and abs(il - tgt) <= 1.0, f"{il} LUFS (target {tgt}±1)", "warn")
        _check(checks, "audio.true_peak", tp is not None and tp <= tp_max + 0.3, f"{tp} dBTP (max {tp_max})")
    synthetic = any(a.get("synthetic") for a in am["assets"])
    metrics["synthetic"] = synthetic
    _check(checks, "disclosure.synthetic_flag", not synthetic or data.get("synthetic_disclosure", True),
           "synthetic assets present; publish must set the platform AI label")
    _check(checks, "rights.assets", all(a.get("rights") in ("owned", "licensed", "funded-brief") for a in am["assets"]),
           "every asset carries rights")
    checks.append({"id": "judge.content", "status": "warn", "detail": "no content review for this file; human reviews it"})
    from .publish import sha256_file
    report = {"schema_version": "0.1", "job_id": data["job_id"], "passed": all(c["status"] != "fail" for c in checks),
              "checks": checks, "metrics": metrics, "artifacts": {"video" if final.suffix == ".mp4" else "audio": final.name},
              "artifacts_sha256": {"video" if final.suffix == ".mp4" else "audio": sha256_file(final)}}
    job.write("qa", report)
    return report


def run(job: Job) -> dict:
    if not job.has("edit_manifest"):
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
        report = {"schema_version": "0.1", "job_id": data["job_id"], "passed": False, "checks": checks}
        job.write("qa", report)
        return report

    prof = em["profile"]
    info = media.summarize(final)
    dur = media.duration(final)
    metrics.update(info, duration_sec=round(dur, 3))
    _check(checks, "frame.size", (info.get("width"), info.get("height")) == (prof["width"], prof["height"]),
           f"{info.get('width')}x{info.get('height')} vs {prof['width']}x{prof['height']}")
    _check(checks, "frame.fps", abs(info.get("fps", 0) - prof["fps"]) < 0.5, f"{info.get('fps')} fps")
    _check(checks, "duration", abs(dur - em["duration_sec"]) <= 0.35, f"{dur:.2f}s vs plan {em['duration_sec']:.2f}s")
    _check(checks, "duration.short_form", dur <= 179, f"{dur:.1f}s (Shorts limit 3 min)", "warn")

    if em.get("audio"):
        loud = media.loudness(final)
        metrics.update(loud)
        tgt, tp_max = prof.get("target_lufs", -14), prof.get("true_peak_dbtp_max", -1)
        il, tp = loud["integrated_lufs"], loud["true_peak_dbtp"]
        _check(checks, "audio.loudness", il is not None and abs(il - tgt) <= 1.0, f"{il} LUFS (target {tgt}±1)")
        _check(checks, "audio.true_peak", tp is not None and tp <= tp_max + 0.3, f"{tp} dBTP (max {tp_max})")
        dead = [s for s in media.silencedetect(final, -45, 1.2) if s[1] - s[0] >= 1.2]
        _check(checks, "audio.dead_air", not dead, f"{len(dead)} silent spans ≥1.2s", "warn")

    black = media.blackdetect(final, 0.5)
    _check(checks, "picture.black_frames", not black, f"{len(black)} black spans ≥0.5s")

    # pacing: longest stretch without a visual change
    starts = [c.get("start_sec", 0) for c in em.get("cuts", [])] + [em["duration_sec"]]
    longest = max((b - a for a, b in zip(starts, starts[1:])), default=0)
    metrics["longest_shot_sec"] = round(longest, 2)
    stills = all(not c["source"].endswith(".video") for c in em.get("cuts", []))
    _check(checks, "pacing.pattern_interrupt", longest <= (5.0 if stills else 6.5),
           f"longest shot {longest:.1f}s", "warn")

    # hook timing
    caps = em.get("captions", [])
    first = caps[0]["start_sec"] if caps else None
    if caps or am.get("words"):  # edits of silent footage carry no captions to time
        _check(checks, "hook.first_word", first is not None and first <= 0.6, f"first caption at {first}s", "warn")
    hook_words = len(packet["beats"][0]["text"].split())
    _check(checks, "hook.length", hook_words <= 14, f"hook line {hook_words} words", "warn")

    # caption coverage of spoken words
    words = am.get("words", [])
    if words:
        covered = sum(1 for w in words if any(c["start_sec"] - 0.05 <= w["start_sec"] <= c["end_sec"] for c in caps))
        cov = covered / len(words)
        metrics["caption_coverage"] = round(cov, 3)
        _check(checks, "captions.coverage", cov >= 0.95, f"{cov:.0%} of words captioned")
        est = sum(1 for w in words if w.get("confidence", 1) < 0.8) / len(words)
        _check(checks, "captions.timing_source", est < 0.5,
               "word timings estimated (local voice); use a timestamped voice or transcribe pass", "warn")

    # claims
    bad = [c["id"] for c in packet.get("claims", []) if not re.match(r"https?://", c.get("source", ""))]
    _check(checks, "claims.sourced", not bad, f"claims without URL sources: {bad}" if bad else "all claims have URLs",
           "warn")

    # disclosure
    synthetic = any(a.get("synthetic") for a in am["assets"])
    metrics["synthetic"] = synthetic
    _check(checks, "disclosure.synthetic_flag", not synthetic or data.get("synthetic_disclosure", True),
           "synthetic assets present; publish must set the platform AI label")

    # stock credits must reach the post, not just the job folder
    if (job.folder / "stock.json").exists():
        from .stock import credits
        desc = (packet.get("publish") or {}).get("description", "")
        _check(checks, "rights.stock_credit", credits(job) in desc, "stock credit line present in publish description")

    # rights
    rights_ok = all(a.get("rights", data.get("rights")) in ("owned", "licensed", "funded-brief") for a in am["assets"])
    _check(checks, "rights.assets", rights_ok, "every asset carries rights")

    sheet = contact_sheet(job, final, em)
    judge = None
    try:
        if sheet:
            from .plan import extract_json
            _, res = router.generate(job, "llm", "llm", f"Script:\n{[b['text'] for b in packet['beats']]}\n\n{RUBRIC}",
                                     images=[job.work / sheet], max_tokens=800, note="qa-judge")
            judge = extract_json(res.text)
            _check(checks, "judge.verdict", judge.get("verdict") != "kill", f"judge: {judge.get('verdict')}")
            _check(checks, "judge.policy", judge.get("policy_risk") != "high", f"policy risk {judge.get('policy_risk')}")
    except CostCapExceeded:
        raise
    except LookupError:
        checks.append({"id": "judge.vision", "status": "warn", "detail": "no LLM provider ready; human reviews contact sheet"})
    except Exception as exc:  # judge is advisory
        checks.append({"id": "judge.vision", "status": "warn", "detail": f"judge error: {exc}"[:300]})

    passed = all(c["status"] != "fail" for c in checks)
    from .publish import sha256_file
    report = {"schema_version": "0.1", "job_id": data["job_id"], "passed": passed, "checks": checks, "metrics": metrics,
              "artifacts": {k: v for k, v in {"video": "final.mp4", "audio": "final.m4a" if (job.work / "final.m4a").exists() else None,
                                              "thumbnail": "thumb.jpg", "contact_sheet": sheet,
                                              "captions_srt": "captions.srt" if (job.work / "captions.srt").exists() else None}.items() if v}}
    report["artifacts_sha256"] = {"video": sha256_file(final)}
    if judge:
        report["judge"] = judge
    job.write("qa", report)
    return report
