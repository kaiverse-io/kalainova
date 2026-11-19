---
name: a-transcript-of-a-sung-mix-is-not-a-measurement
description: One Whisper pass over a generated song gave its lyrics, invented sentences, or "We'll be right back" x7; two passes on one vocal stem read 66% and 4.5% of the words; never choose between takes or masters by one pass
metadata:
  type: feedback
---
Words heard (`song.words_found`) on generated songs, read with the `mac` transcriber (whisper-large-v3-turbo through mlx-audio), 2026-11-19:

- Three master options of one take differed only by ±1.5 dB of vocal. One transcript was the lyrics. One was invented sentences that still scored 84%. One was "We'll be right back" seven times, which scored 0%.
- Two passes over the same vocal stem read 66% and 4.5%. Another stem read 0% on both passes, for both separation models.

So a single pass is noise, not a measurement, on sung audio over a band. It cannot choose a master (ADR 0029 says so) or a separation model. When words heard must decide something, take several passes and look at the spread, or have a person write down what they hear.

Two other lessons from the same work:
- **`audio-separator` resamples to 44.1 kHz unless it is given `--sample_rate`.** A stem at another rate cannot be laid on its mix. Even at the right rate, a model's vocal and "other" stems add back to the mix only to 16–18 dB, so move a stem as a change added to the mix (mix + (g − 1) × stem) and never sum stems back.
- **A tempo reading over 8-second windows needs sub-frame lags and 3:2 and 4:3 folds.** At 43 frames a second a whole-frame lag reads 126 bpm only as 123 or 129, and dance percussion locks most windows onto 84. The old `song.tempo_drift` failed every paid take at 0.09–0.18. beat_this held them within ±0.2 bpm.

**How to apply:** treat a transcript-based reading as a diagnostic, and say so on the page that shows it. Before trusting a stem, check its sample rate against the mix. Before trusting a new rhythm reading, check it against beat_this on real takes.
