# Feature map

> Where each user-visible feature starts, what code owns it, and which tests pin its behaviour.
> An agent reads this before searching the tree: the right file should be one lookup away, not a
> grep. Add a row in the same PR that adds the feature; `ARCHITECTURE.md` describes components,
> this describes what users can do with them.

| Feature | Entry point | Code | Tests |
|---|---|---|---|
| _Example — replace:_ health check | `GET /healthz` | `src/<package>/api/health.py` | `tests/test_health.py` |
