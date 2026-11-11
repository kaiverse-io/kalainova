# Feature map

> Where each user-visible feature starts, what code owns it, and which tests pin its behaviour.
> An agent reads this before searching the tree: the right file should be one lookup away, not a
> grep. Add a row in the same PR that adds the feature; `ARCHITECTURE.md` describes components,
> this describes what users can do with them.

| Feature | Entry point | Code | Tests |
|---|---|---|---|
| Make a generated piece | `kalainova make` | `assets.py`, `edit.py`, `render/` | `tests/test_engine.py` |
| Free the disk a render used | `kalainova clean [--dry-run]` | `render/cache.py` | `tests/test_rendercache.py` |
| Rough cut before video is paid for, and a gate on video | `kalainova animatic`, `verdict --animatic`, `brief.animatic_gate` | `preproduction.py`, `assets.py`, `verdicts.py`, `publish/__init__.py` | `tests/test_preproduction.py` |
| Look sheet for a kit's candidate references | `kalainova look` | `lookdev.py`, `studio_cli.py` | `tests/test_preproduction.py` |
| Plan review before spending | `kalainova shotplan` | `shots.py` | `tests/test_shots.py` |
| Takes and retakes | `kalainova takes`, `take`, `retake` | `takes.py`, `shotmake.py` | `tests/test_takes.py` |
| Compare models on one shot | `kalainova bench`, `verdict --take` | `bench.py`, `takes.py`, `timeline.py`, `verdicts.py` | `tests/test_bench.py` |
| Every shot moves by default | `kalainova make`, `shotplan` | `shots.py`, `plan.py`, `assets.py` | `tests/test_moving_by_default.py` |
| The motion promise | `kalainova make` | `assets.py`, `shotmake.py`, `qachecks.py` | `tests/test_takes.py`, `tests/test_vendor_payloads.py` |
| Songs | `kalainova song`, `song-video` | `songs.py`, `bar/song.py` | `tests/test_songs.py` |
| Video cut to a track: bars, phrases, excerpt, character cutaways, estimate | `kalainova song-video [--excerpt]` | `editor/musiccuts.py`, `editor/musicvideo.py`, `editor/beats.py`, `jobfs.py` (`open_child`), `qachecks.py` (`edit.cuts_on_beat`) | `tests/test_music_video.py` |
| Song release files, stems, length check | `kalainova song` | `render/release.py`, `providers/fal.py` (`separate`), `providers/router.py` (`refuse_too_long`) | `tests/test_song_release.py`, `tests/test_fal_stems.py` |
| Scripts from a brief | `kalainova song`, `comic`, `story` | `writers.py` | `tests/test_songs.py` |
| Research with checked quotes | `kalainova research` | `research.py`, `providers/search.py` | `tests/test_research.py` |
| Shot sheet, filmstrip, cut check | `kalainova sheet`, `filmstrip`, `cutcheck` | `timeline.py` | `tests/test_timeline.py` |
| Review in motion: motion strip, cut strip, findings, retake limits | `kalainova sheet --motion`, `sheet --cuts`, `findings`, `retake` | `timeline.py`, `qa.py`, `qachecks.py`, `takes.py`, `shotmake.py` | `tests/test_motion_review.py` |
| Character shot ceiling, overlay safe zone | `kalainova shotplan`, `make` | `shots.py`, `qachecks.py`, `config/studio.yaml` (`character_shot_max_sec`, `safe_zone`) | `tests/test_motion_review.py` |
| Timeline export | `kalainova export` | `nle.py` | `tests/test_nle.py` |
| Footage edit | `kalainova ingest`, `edit`, `revise` | `editor/` | `tests/test_editor.py` |
| Word-level speech cuts | `kalainova edit` | `editor/speech.py` | `tests/test_speech_clips.py` |
| Clips from a long source | `kalainova clips` | `editor/clips.py` | `tests/test_speech_clips.py` |
| Dubbing | `kalainova dub` | `dub.py` | `tests/test_dub.py` |
| Comics and books | `kalainova comic`, `story` | `comic.py`, `story.py` | `tests/test_comic.py`, `tests/test_story.py` |
| Kits, streams, locks | `kalainova kit`, `stream`, `request` | `kits.py`, `streams.py`, `consistency.py` | `tests/test_kits.py`, `tests/test_kit_jobs.py` |
| The studio bar | `kalainova bar` | `bar/` | `tests/test_bar.py` |
| Verdicts and signals | `kalainova verdict`, `signals` | `verdicts.py` | `tests/test_verdicts_provenance.py` |
| The review set | `kalainova review-set` | `verdicts.py`, `bar/sources.py` | `tests/test_review_set.py` |
| Live adapter check (opt-in, paid) | `kalainova providers --check` | `providers/check.py` | `tests/test_provider_check.py` |
| Chain of title | `kalainova provenance`, `ledger` | `provenance.py` | `tests/test_verdicts_provenance.py` |
| Approval and publishing | `kalainova approve`, `publish` | `publish/` | `tests/test_engine.py`, `tests/test_gate_master.py` |
| AI label per platform from the assets, and a publish time where the platform holds one | `kalainova publish --at` | `publish/labels.py`, `publish/aggregator.py` | `tests/test_publish_labels.py` |
| Cover picker: sharpest clean frame, square cut, brief override | `brief.cover_at_sec`, `brief.cover_file` | `render/cover.py`, `render/export.py` | `tests/test_cover.py` |
| Reservations and the ledger | every paid call | `jobfs.py`, `providers/router.py` | `tests/test_ledger.py`, `tests/test_router.py` |
| Open models on this machine | `providers: {"video": ["mac"]}` | `providers/mac.py`, `providers/runners/` | `tests/test_mac_provider.py` |
| Incremental render | `kalainova make --from edit` | `render/cache.py` | `tests/test_rendercache.py` |
