# Feature map

> Where each user-visible feature starts, what code owns it, and which tests pin its behaviour.
> An agent reads this before searching the tree: the right file should be one lookup away, not a
> grep. Add a row in the same PR that adds the feature; `ARCHITECTURE.md` describes components,
> this describes what users can do with them.

| Feature | Entry point | Code | Tests |
|---|---|---|---|
| Make a generated piece | `kalainova make` | `assets.py`, `edit.py`, `render/` | `tests/test_engine.py` |
| Run anywhere: the engine's own files in the package, a per-user studio folder | `pip install`, `just ci-wheel` | `resources.py`, `jobfs.py`, `pyproject.toml` (force-include) | `tests/test_knowledge.py`, `scripts/check_wheel.py` |
| How a person on camera is directed, by version | `kalainova guide [kind]` | `knowledge.py`, `prompts/directions.yaml`, `shots.py` | `tests/test_knowledge.py`, `tests/test_performance_direction.py` |
| What a model takes, and its limits with sources | `kalainova guide <model>`, `kalainova models refresh` | `knowledge.py`, `knowledge_cli.py`, `providers/fal_catalog.py`, `providers/fal_sing.py` | `tests/test_knowledge.py` |
| Which judges this machine can run | `kalainova judges` | `bar/judges.py`, `judging_cli.py` | `tests/test_knowledge.py` |
| What made each take | `made_with` in `takes.json` | `knowledge.stamp`, `takes.py`, `shotmake.py`, `bench.py` | `tests/test_knowledge.py` |
| Free the disk a render used | `kalainova clean [--dry-run]` | `render/cache.py` | `tests/test_rendercache.py` |
| Rough cut before video is paid for, and a gate on video | `kalainova animatic`, `verdict --animatic`, `brief.animatic_gate` | `preproduction.py`, `assets.py`, `verdicts.py`, `publish/__init__.py` | `tests/test_preproduction.py` |
| Look sheet for a kit's candidate references | `kalainova look` | `lookdev.py`, `studio_cli.py` | `tests/test_preproduction.py` |
| Plan review before spending | `kalainova shotplan` | `shots.py` | `tests/test_shots.py` |
| Takes and retakes | `kalainova takes`, `take`, `retake` | `takes.py`, `shotmake.py` | `tests/test_takes.py` |
| See every paid request and its price before spending | `kalainova rehearse`, `scripts/check_fal_schemas.py --rehearsal` | `rehearse.py`, `providers/rehearsal.py`, `providers/transport.py`, `providers/router.py` | `tests/test_rehearsal.py` |
| Add or swap a vendor without touching the engine (ADR 0023) | a new adapter in `providers/`, its rows in `config/studio.yaml` | `providers/contract.py`, `providers/base.py`, `providers/transport.py` | `tests/boundary/test_provider_contract.py`, `tests/test_request_keys.py`, `tests/test_transport.py` |
| No paid call until a person signs off a package, with its readiness checked, under studio limits (ADR 0022) | `kalainova package`, `sign-off`, `packages`, `limits` | `gates.py`, `packages.py`, `readiness.py`, `signoff_cli.py`, `providers/payloads.py`, `providers/router.py`, `providers/transport.py` | `tests/test_signoff.py`, `tests/test_readiness.py` |
| Stop every paid call in a studio at once | `kalainova stop --by NAME`, `kalainova resume --by NAME` | `gates.py`, `providers/router.py` | `tests/test_gates.py` |
| Prices checked against the vendor and the studio's own bills | `kalainova ledger`, `scripts/check_fal_prices.py` | `providers/prices.py`, `providers/records.py`, `providers/fal.py`, `config/studio.yaml` | `tests/test_price_corrections.py`, `tests/test_call_audit.py`, `tests/test_prices.py` |
| Judge every take by eye on one page | `kalainova review` | `reviewpage.py` | `tests/test_review_page.py` |
| Character shots at the profile's source size | `kalainova make`, `retake` | `takes.py` (`held_to`), `shotmake.py`, `config/studio.yaml` (`character_source_min_px`) | `tests/test_take_honesty.py` |
| Compare models on one shot | `kalainova bench`, `verdict --take` | `bench.py`, `takes.py`, `timeline.py`, `verdicts.py` | `tests/test_bench.py` |
| A bench read: labelled side by side, table, the engine's pick and why | `kalainova bench-report`, `rank` in config | `benchreport.py`, `judging_cli.py` | `tests/test_bench_report.py` |
| How a person on camera moves, judged | `judges.performance` in config | `providers/runners/perform_run.py`, `takejudges.py` | `tests/test_perform_judge.py` |
| Preferences by aspect, and which readings follow them | `kalainova verdict --best --among --aspect`, `agreement` | `verdicts.py`, `judging_cli.py` | `tests/test_bench_report.py` |
| Every shot moves by default | `kalainova make`, `shotplan` | `shots.py`, `plan.py`, `assets.py` | `tests/test_moving_by_default.py` |
| The motion promise | `kalainova make` | `assets.py`, `shotmake.py`, `qachecks.py` | `tests/test_takes.py`, `tests/test_vendor_payloads.py` |
| Songs | `kalainova song`, `song-video` | `songs.py`, `bar/song.py` | `tests/test_songs.py` |
| Video cut to a track: bars, phrases, excerpt, character cutaways, shot list, estimate | `kalainova song-video [--excerpt] [--shots]` | `editor/musiccuts.py`, `editor/musicvideo.py`, `editor/beats.py` (seam: `adapters.beats`), `editor/beat_this.py`, `jobfs.py` (`open_child`), `qachecks.py` (`edit.cuts_on_beat`) | `tests/test_music_video.py`, `tests/test_beat_adapters.py` |
| A character who sings: `Sings:` shots sung in one call from their still and their line (ADR 0025) | `kalainova song-video --shots`, `sing_models` in config | `providers/contract.py` (`SingRequest`), `providers/fal.py` (`sing`), `shotmake.py` (`take_clip`, `sung_line`, `judged_sung`), `editor/musicvideo.py` (`_sings`, `beats_for`, `estimate`) | `tests/test_singing_shots.py`, `tests/test_fal_sing.py` |
| Lip match of a sung take scored, and singing models benched on one line | `judges.lipsync` in config, `kalainova bench <job> <shot> --models` | `providers/runners/syncnet_run.py`, `takejudges.py` (`judged_sung`), `bench.py` | `tests/test_singing_engine.py` |
| A short of a sung song cut where its words are sung; singing shots placed by the vocal stem; no lip sync over silence | `kalainova song-video --excerpt --shots` | `editor/singing.py` (`voiced`, `best_window`, `place`), `editor/musicvideo.py` (`_stretch`, `_placed`), `shotmake.py` (`lip_sync`) | `tests/test_singing_engine.py` |
| Lyrics heard off the vocal stem, the chorus reading, the pick between jobs | `kalainova song`, `kalainova review <job>... --judge` | `songs.py` (`_sung_words`), `bar/song.py` (`chorus_heard`, `saved_heard`, `assessed`), `takes.py` (`best`), `reviewpage.py` (`judged`, `_pick`) | `tests/test_singing_engine.py`, `tests/test_judges.py` |
| Song models chosen per job, and takes heard blind at one loudness, ranked once | `brief.song_model`, `kalainova review <job>... --blind`, `--rank` | `songs.py` (`_song_pin`), `providers/fal.py` (`song`), `reviewpage.py` (`blind`, `rank`) | `tests/test_blind_listening.py`, `tests/test_songs.py`, `tests/test_vendor_adapters.py` |
| Learned judges score takes, rank those that pass, never block (ADR 0024) | `judges.<kind>` in config, `kalainova review <job>... --judge` | `bar/judges.py`, `takes.py` (`_best`), `songs.py` (assess), `reviewpage.py` (`judged`), `providers/runners/muqeval_run.py`, `providers/runners/aesthetics_run.py` | `tests/test_judges.py` |
| Song release files, stems, length check | `kalainova song` | `render/release.py`, `providers/fal.py` (`separate`), `providers/router.py` (`refuse_too_long`) | `tests/test_song_release.py`, `tests/test_fal_stems.py` |
| A song's master as options heard blind: vocal moved a few dB, matched to an owned reference, set to a level, read again once encoded (ADR 0029) | `kalainova song master <job> [--vocal-db=] [--reference] [--level] [--hear]`, `kalainova review <job> --blind --shot master`, `kalainova take <job> master N` | `song_master.py`, `providers/separator.py`, `providers/runners/matchering_run.py`, `songs.py` (`clean`), `reviewpage.py` (`blind`), `schemas/takes.schema.json` (`master`) | `tests/test_song_master.py` |
| Tempo drift read as the metric relation nearest the tempo asked for, so a 3:2 percussion figure is not drift | `kalainova song`, `kalainova bar` | `bar/song.py` (`tempo_drift`, `METRIC_FOLDS`) | `tests/test_songs.py` |
| A song file's vocal gender sent as the model's own setting; the vendor's song id kept on the take; a style with "no ..." refused | `song.json` (`vocal_gender`, `avoid`), `kalainova song` | `songs.py` (`problems`, `NEGATION`, `song_request`), `providers/fal.py` (`song`), `prompts/song_writer.md` | `tests/test_song_file_to_release.py` |
| A job's song model and takes pinned by command; a song's takes rehearsed before spend | `kalainova pin <job> song PROVIDER:MODEL --takes N`, `kalainova rehearse <job>` | `studio_cli.py` (`_pin_job`), `songs.py` (`rehearse_takes`), `rehearse.py` | `tests/test_song_file_to_release.py` |
| The master a person chose released, with a record of what AI made part by part | `kalainova song master <job> --release` | `song_master.py` (`release`), `render/release.py` (`ai_use`), `writers.py` (`words_by`) | `tests/test_song_file_to_release.py` |
| Scripts from a brief | `kalainova song`, `comic`, `story` | `writers.py` | `tests/test_songs.py` |
| Research with checked quotes | `kalainova research` | `research.py`, `providers/search.py` | `tests/test_research.py` |
| Shot sheet, filmstrip, cut check | `kalainova sheet`, `filmstrip`, `cutcheck` | `timeline.py` | `tests/test_timeline.py` |
| Review in motion: motion strip, cut strip, findings, retake limits | `kalainova sheet --motion`, `sheet --cuts`, `findings`, `retake` | `timeline.py`, `qa.py`, `qachecks.py`, `takes.py`, `shotmake.py` | `tests/test_motion_review.py` |
| Character shot ceiling, overlay safe zone | `kalainova shotplan`, `make` | `shots.py`, `qachecks.py`, `config/studio.yaml` (`character_shot_max_sec`, `safe_zone`) | `tests/test_motion_review.py` |
| Kinetic captions drawn as a transparent layer; title, quote and stat cards | `brief.captions: kinetic`, `kalainova card` | `render/drawn.py`, `render/picture.py` (`op_burn_captions`), `edit.py`, `qachecks.py`, `providers/hyperframes.py` | `tests/test_drawn.py` |
| Timeline export, and an edit read back (seam: `adapters.timeline`) | `kalainova export`, `kalainova timeline-import` | `nle.py`, `nle_otio.py` (`otioconvert`), `opentools.py` (the contract every command adapter keeps) | `tests/test_nle.py`, `tests/test_nle_otio.py` |
| Footage edit | `kalainova ingest`, `edit`, `revise` | `editor/` | `tests/test_editor.py` |
| Patch one cut in an edit | Python API `editor.patch.patch_cut` | `editor/patch.py` | `tests/test_edit_patch.py` |
| Video openings that reuse the parent's body assets | Python API `variants.open_variant` | `variants.py`, `jobfs.py` (`open_child`) | `tests/test_variants.py` |
| Template-driven data shorts, refused when the data file is stale | Python API `templates.fill_template` | `templates.py` | `tests/test_templates.py` |
| Word-level speech cuts, or loudness cuts from `auto-editor` (seam: `adapters.speech_cuts`) | `kalainova edit` | `editor/speech.py` (`keep_spans`), `editor/auto_editor.py`, `editor/direct.py` | `tests/test_speech_clips.py`, `tests/test_speech_cuts_adapter.py` |
| Clips from a long source, refused without a record of where the source came from | `kalainova clips`, `brief.source` | `editor/clips.py` (`require_source`, `tidy`, `choose_crop`, `face_centre`, `motion_centre`, opening and closing cards), `publish/__init__.py` | `tests/test_speech_clips.py`, `tests/test_clip_cards.py`, `tests/test_production_cli.py` |
| Dubbing | `kalainova dub` | `dub.py` | `tests/test_dub.py` |
| Comics and books | `kalainova comic`, `story` | `comic.py`, `story.py` | `tests/test_comic.py`, `tests/test_story.py` |
| Kits, streams, locks | `kalainova kit`, `stream`, `request` | `kits.py`, `streams.py`, `consistency.py` | `tests/test_kits.py`, `tests/test_kit_jobs.py` |
| The studio bar | `kalainova bar` | `bar/` | `tests/test_bar.py` |
| Verdicts and signals | `kalainova verdict`, `signals` | `verdicts.py` | `tests/test_verdicts_provenance.py` |
| The review set | `kalainova review-set` | `verdicts.py`, `bar/sources.py` | `tests/test_review_set.py` |
| OpenAI-compatible LLM vendors (Gemini, Groq, OpenRouter, z.ai) | `providers: {"llm": ["groq"]}` | `providers/compat.py`, `config/studio.yaml` | `tests/test_compat_llm.py` |
| Live adapter check (opt-in, paid) | `kalainova providers --check` | `providers/check.py` | `tests/test_provider_check.py` |
| Chain of title | `kalainova provenance`, `ledger` | `provenance.py` | `tests/test_verdicts_provenance.py` |
| Approval and publishing | `kalainova approve`, `publish` | `publish/` | `tests/test_engine.py`, `tests/test_gate_master.py` |
| AI label per platform from the assets, and a publish time where the platform holds one | `kalainova publish --at` | `publish/labels.py`, `publish/aggregator.py` | `tests/test_publish_labels.py` |
| Cover picker: sharpest clean frame, square cut, brief override | `brief.cover_at_sec`, `brief.cover_file` | `render/cover.py`, `render/export.py` | `tests/test_cover.py` |
| Reservations and the ledger | every paid call | `jobfs.py`, `providers/router.py` | `tests/test_ledger.py`, `tests/test_router.py` |
| Open models on this machine | `providers: {"video": ["mac"]}` | `providers/mac.py`, `providers/runners/` | `tests/test_mac_provider.py` |
| Real word times from the `whisper-cli` command | `preference.transcribe: [whispercpp]`, `KALAINOVA_WHISPER_CPP_MODEL` | `providers/whispercpp.py` | `tests/test_whispercpp.py`; tried on real audio: `docs/how-to/try-the-open-tools.md` |
| Incremental render | `kalainova make --from edit` | `render/cache.py` | `tests/test_rendercache.py` |
| A stream's fixed sound identity: tempo, keys, drum kit, mastering target | Python API `sound_identity.load_sound_identity`, `sound_identity.check_track` | `sound_identity.py` | `tests/test_sound_identity.py` |
