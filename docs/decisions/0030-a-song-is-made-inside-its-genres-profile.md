# 0030. A song is written and made inside its genre's profile, which the studio sets

Status: accepted · 2026-11-19. Builds on 0022 (no paid call until a ready package is signed off) and 0029 (a song's master is chosen by a person).

## Context

What a song was came from three places at once. A person wrote a line of brief. A writer (a model, or the agent) chose the tempo, key, structure and sound. The pinned model made it. Nothing held these together across songs, so each song was decided from scratch, and nothing said what a studio's songs in one genre are.

The first blind comparison showed the cost. Two takes of one style that fixed one groove for the whole song came back with "the same type of beats", and post-production cannot change a beat.

## Decision

1. **A genre profile is the studio's decision.** It sits in the private config under `genres:`: a tempo range, keys, the length, a structure with bar counts, base style words, what to keep out, the voice, the song model, and how many takes. The repo names no genre.
2. **A job names its genre.** Use `kalainova new --genre`, or `kalainova request <stream> --media song --genre`. A stream that makes audio can be asked for a song.
3. **The writer writes inside it** (`prompts/genre_profile.md`): a tempo in range, one of its keys, its structure, its style words first, its voice.
4. **The engine holds the song to it.** It pins the profile's model and takes unless the brief pins them. A song file outside the tempo range, keys or voice is refused before any spend.

## Consequences

- Choosing a genre's model is one edit to its profile, made after a blind bake-off, and every later song of that genre follows it.
- The profile is config, so a job's config hash records the profile it was made under. It is not yet a frozen kit, attested by a person and versioned. Moving it into a music kit is the next step once a stream fixes its music.
- Reference tracks for each genre (for reference matching and readings against them) belong in the same profile when the operator has them.
