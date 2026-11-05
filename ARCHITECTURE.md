# Architecture

Kalainova is one engine and many jobs. A job declares a **strategy** and one or more **media** kinds. It does not declare a segment. Chassis supplied the cockpit planes: agent context, a single `just` entrypoint, docs and ADRs, a contract eval, pre-commit, a devcontainer, one skill. GitHub Actions is not on `main` yet (see `README.md`). There is no language runtime to stamp yet, because the compiler is not in this repo.

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

just ci ──► check   scripts/check.py           no media blobs in git; every job folder matches the contract
        ──► eval    check.py --fixtures        evals/contract: pass/ must pass, fail/ must fail
        ──► lint    scripts/lint_docs.py       engine docs grow no worked example
```

| Plane | Where | Role |
|---|---|---|
| Strategies | `docs/strategies.md` | How a piece gets made and how it can get paid. Subject-agnostic. |
| Pipeline | `docs/pipeline.md` | Stages from intent to measure. Same spine for every medium. |
| Contract | `schemas/` | Job, script, assets, edit, render plan, measure. |
| Jobs | `jobs/<id>/` | One piece. Copy `jobs/_template`. Subject text stays in that folder only. |
| Gates | `scripts/check.py`, `scripts/lint_docs.py`, pre-commit | Media stays out of git. Jobs that violate the contract fail. Engine docs stay subject-free. |
| Decisions | `docs/decisions/` | One ADR per standing rule. |
| Evals | `evals/contract/` | Contract fixtures run now. The content eval waits for an accepted or measured job. |

Publish is not a function of this repo. Agents draft, render, and log. A human uploads and submits.

Rent generators, clippers, voices, and schedulers. Own the job folder. Do not build a shared compiler until one rented job has an accepted or measured unit. A schema is not a shipped frame.
