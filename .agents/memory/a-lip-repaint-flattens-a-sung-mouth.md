---
name: a-lip-repaint-flattens-a-sung-mouth
description: Redrawing the mouth of a finished clip to a sung line kept a third of the mouth's movement; singing is one voice-driven call, and a repaint is for speech
metadata:
  type: feedback
---
A clip from a video model that takes no audio was repainted by a lip-sync model to a sung line. The mouth judge measured it:
- the mouth-opening spread fell from 0.049 to 0.015, so about 30% of the movement was kept;
- the mouth's match to the voice fell to 0.14.

A reviewer saw a near-closed smile where an open singing mouth should be.

An independent test of lip sync on real songs (two songs, one take each, the same mouth-opening-against-loudness measure) ranked every voice-driven model above every repaint. The repaints left the mouth open in the silences, and the speech-tuned one scored lowest.

Two outside reviews agreed. The clip's motion never heard the song, so a repaint can fix timing at best, never a performance.

**Fix:**
- ADR 0025: a sung shot is made in one call that takes the voice.
- The bench's `repaint_mouth_kept` reading measures how much movement a repaint keeps.

A repaint stays reasonable for speech and dubbing, best with a model that also moves the head and body.

**Why:** the repaint route looked like a way to combine one model's motion with another's lips. It cost a paid take to learn it flattens singing.

**How to apply:** don't plan a lip repaint for singing. For speech, read `repaint_mouth_kept` and the windowed lip readings before trusting one.
