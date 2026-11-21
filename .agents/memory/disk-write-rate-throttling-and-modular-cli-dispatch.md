# Disk write rate throttling and modular CLI dispatch

**Date:** 2026-11-21
**Class:** observed / tested
**Status:** active

## What happened
Watchdog incident reports in `/private/var/tmp/sysdiagnose_*/crashes_and_spins/ffmpeg_*.diag` identified that 18 parallel xdist workers running unconstrained FFmpeg renders dirtied 137.44 GB of file-backed memory over 3,922s (35.04 MB/s sustained). This exceeded macOS disk write limits and drove advisory levels to `Battery -> 3, User -> 2, ThermalPressure -> 2`. In test suites, `tests/footage_fixtures.py:clip()` wrote thousands of individual `.png` frame files to disk before encoding and unlinking them. In the engine, `src/kalainova/__main__.py` grew to 498 lines (2 lines away from the 500-line ceiling) with cyclomatic complexity 41 and CRAP score 156, and had to be suppressed under mypy and ruff debt lists.

## Root cause
1. Spawning unlimited workers (`-n auto`) and allowing child processes (FFmpeg) to spawn unconstrained threads caused severe disk I/O churn, CPU oversubscription, and kernel thermal throttling.
2. Generating video test clips by dumping uncompressed PNG frames to disk rather than streaming rawvideo directly to FFmpeg `stdin`.
3. Conflating parser declaration with imperative command waterfall execution in `__main__.py` rather than using the engine's proven modular CLI pattern (`add_parsers(sub)` and `dispatch(a)`).

## Fix
1. Pipe rawvideo frames directly into FFmpeg stdin via `media.run(input=raw_bytes)`, eliminating 100% of intermediate PNG filesystem I/O in test clip fixtures.
2. Cap child process threads in tests via `KALAINOVA_FFMPEG_THREADS=1` and `_cap_subprocess_threads` to prevent CPU context switching on 2-vCPU CI runners.
3. Modularize CLI into `editor_cli.py` (ingest, edit, revise, shots, stock, reel) and `job_cli.py` (lifecycle and document stages), shrinking `__main__.py` from 498 to 82 lines, dropping cyclomatic complexity to 3, and removing `kalainova.__main__` from mypy `ignore_errors` and ruff `per-file-ignores` debt lists in `pyproject.toml`.
4. Document `editor_cli` and `job_cli` in `ARCHITECTURE.md` and redraw in `## Component Diagram`.
