---
name: clamp-xdist-workers-and-purge-test-home
description: pytest -n auto on high-core machines over-saturates CPU causing thermal throttling, and test KALAINOVA_HOME mkdtemp leaked orphaned directories; clamp workers to min(8, cpus) and atexit.register rmtree
metadata:
  type: feedback
---
Local test execution on Apple Silicon Mac throttled heavily (all 18 cores saturated at 100°C, kernel_task taking 800% CPU), and repeated pytest invocations accumulated thousands of orphaned `kalainova-test-home-*` temporary directories in `/tmp`.

**Root causes:**
1. `-n auto` on an 18-core Apple Silicon chip spawned 18 Python worker processes and pinned all P-cores and low-IPC E-cores simultaneously, hitting SoC package power limits and triggering thermal throttling. Subprocesses also competed for BLAS/OpenMP threads.
2. `tests/conftest.py` called `tempfile.mkdtemp(prefix="kalainova-test-home-")` at module import time to set `$KALAINOVA_HOME` safely away from the user's real data folder, but never registered a cleanup hook. Over hundreds of test runs, 1,200+ directories remained on disk.
3. Tests in `test_speech_clips.py` and `test_clip_cards.py` were generating 30-second synthetic video clips (`d=30`) and encoding 20-second 1080p outputs through FFmpeg and QA, taking 300+ seconds alone.

**Fix:**
- In `tests/conftest.py`, implemented `pytest_xdist_auto_num_workers(config)` to clamp workers to `min(8, os.cpu_count())`. This leaves thermal headroom on high-core dev machines while respecting 2-vCPU CI runners.
- Capped BLAS/OpenMP subprocess threads to 1 via autouse session fixture `_cap_subprocess_threads()`.
- Added `atexit.register(shutil.rmtree, _test_home, ignore_errors=True)` to ensure `$KALAINOVA_HOME` temp folder is always purged on process exit.
- Scaled synthetic test clip durations from 30s (`d=30`) down to 4s (`d=4`), retaining 100% of the FFmpeg pipeline and QA assertions while slashing module test time from 301s to 10s.

**Status:** proved. `just ci-test` dropped from >12 minutes down to 5m 18s with 0 thermal throttling, and all 1,266 leaked temp directories were purged with 0 leaks on exit.
