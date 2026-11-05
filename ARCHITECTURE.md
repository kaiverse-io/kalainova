# Architecture

Kalainova is one engine and many jobs. A job declares a **strategy** and one or more **media** kinds. It does not declare a segment. Chassis supplied the cockpit: agent context, a single `just` entrypoint, CI, docs, an eval slot. There is no language runtime to stamp yet, because the compiler is not in this repo.

```
intent (operator supplies the subject)
  → strategy          docs/strategies.md
  → job folder        jobs/<id>/job.json
  → script / assets   script_packet, asset_manifest
  → edit              edit_manifest
  → render plan       render_plan (ops from a fixed list)
  → human gate
  → publish           outside the repo
  → measure           measure.json at 48h

just check ──► scripts/check.py
                 no media blobs in git
                 every job.json matches the contract
```

| Plane | Where | Role |
|---|---|---|
| Strategies | `docs/strategies.md` | How a piece gets made and how it can get paid. Subject-agnostic. |
| Pipeline | `docs/pipeline.md` | Stages from intent to measure. Same spine for every medium. |
| Contract | `schemas/` | Job, script, assets, edit, render plan, measure. |
| Jobs | `jobs/<id>/` | One piece. Copy `jobs/_template`. Subject text stays in that folder only. |
| Gates | `scripts/check.py`, CI | Media stays out of git. Jobs that violate the contract fail. |
| Evals | `evals/` | Empty until one job has an accepted or measured unit. |

Publish is not a function of this repo. Agents draft, render, and log. A human uploads and submits.

Rent generators, clippers, voices, and schedulers. Own the job folder. Do not build a shared compiler until one rented job has an accepted or measured unit. A schema is not a shipped frame.
