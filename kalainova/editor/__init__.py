"""The editing arm: the operator's own footage in, a finished edit out.

    ingest   inputs/ (videos, images) -> footage.json     scene split + per-shot scores
    direct   footage + direction notes -> script/asset/edit manifests the shared compiler renders
    revise   a comment -> appended to direction.json, re-directed, re-rendered

Everything after `direct` is the same pipeline as generated pieces: compile -> render -> qa ->
approve -> publish -> measure. Strategy is owned-derivative (or client for someone else's footage).
"""
