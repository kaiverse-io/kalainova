---
name: make-a-song
description: Write and make an original song with Kalainova, choose among takes, and open a lyric video. Use when asked for a song, a jingle, a track, or lyrics to be sung.
---

# Make a song

1. Open a job with `"media": ["song"]` (`docs/how-to/make-a-song.md`). The subject stays in the job folder.
2. Write `song.json`, or let a listed model write it. Words are original. `style` describes a sound and never names a person to imitate.
3. Ask which engine if the job does not pin one. A hosted app sends the lyrics off this machine, so it needs the operator's say-so, and so does anything that costs money.
4. Run `uv run kalainova song <job>`, then `uv run kalainova takes <job>`.
5. Say what the readings can and cannot tell. They warn, and a song is judged by listening, which you cannot do. Never present a reading as proof that a song is good.
6. Stop at the gate. Offer `uv run kalainova song-video <job> <new id>` if a picture is wanted; add `--excerpt SECONDS` for a short. With no lyric lines it cuts on the music's bars, phrases and biggest rise in energy; read its estimate aloud before any `make`. If it says no steady pulse or no clear energy peak, report that to the operator rather than choosing a cut point. Never run `approve`.
