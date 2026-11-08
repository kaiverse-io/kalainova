# 0014. Songs are takes of a written song, and readings never reject one on taste

Status: accepted · 2026-11-07.

## Context

The architecture had a song capability with no adapter, and a reviewed song had been accepted from a model the engine could not call. Measuring reviewed tracks showed that the obvious numbers mislead: the accepted track had twice the lyric error rate of the one sent back, because transcribers struggle with singing, and the distance from words to the beat did not separate them either.

## Decision

- A song is `song.json`: style, tempo, and sections with their lines. A model can write it from a brief, or an agent can.
- `style` describes a sound. A request to imitate a named person is refused before it reaches a model.
- Several takes are made and all are kept. Readings pick one, and a person's choice stands.
- Readings warn and choose among takes. Only a wrong level on the finished file blocks. Lyric error rate is not used; words found stands in for it.
- A finished song gets a master, lyric files timed to what was heard, stems when something can split them, and a job that cuts a lyric video to the track.
- Engines are swappable: HeartMuLa or ACE-Step on this machine, ElevenLabs or MiniMax rented, or a hosted app. A hosted app is never listed by default, because the lyrics leave the machine.

## Consequences

The song readings are candidates until enough songs carry a verdict. No engine has been run through this path on a real song yet: `docs/studio-goal.md` keeps that open. Which model holds up, and at what length, needs a real run. Publishing a song on its own still has no route, so a song reaches a platform through its lyric video.
