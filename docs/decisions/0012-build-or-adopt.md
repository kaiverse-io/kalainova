# 0012. Check what already exists before building a layer

Status: accepted · 2026-11-07. Amends 0002 and 0007.

## Context

ADR 0002 said to rent the tools and own the job folder, the gate, and the log. ADR 0007 widened that to the compile path, because the line had to emit a frame. After that, each new layer was built by default. A review on 2026-11-07 compared the engine with open projects layer by layer. About 40% of its lines duplicated something adoptable or were built before anything needed them, and most of the gaps a review had just found already had working answers elsewhere. No ADR had weighed any of those projects.

## Decision

- Before adding a layer, look for it in open projects and record the choice in the PR that adds it. An ADR is only needed when the choice is significant.
- **Adopt** what is commodity and permissively licensed, running it as a separate tool where possible, and credit it in `NOTICE.md`.
- **Rewrite the idea, never the code,** when a project's licence does not fit. This repository is Apache 2.0, so AGPL and non-commercial code stays out of it. Reading it for an idea is fine, and so is running it as its own program.
- **Rent** what a vendor does better than a local model: generation, character hold, lip sync.
- **Own** only what nothing else provides. On that review, that was: takes of a shot with retakes driven by a reading, an approval bound to the exact bytes of a master, a master checked against a platform's published requirements, the job record across vendors, and comics.
- A model's code licence does not cover its weights. Each is read on its own, and `licences:` in `config/studio.yaml` keeps what a person found.

## Amendment, 2026-11-12: call the tool as it is, never port it

The rule about licences above is replaced by a simpler one. An open tool is called as a command or binary, in its own environment, and its code is never ported into this repository. A capability gets a seam in `config/studio.yaml` (`adapters:`) only together with its second adapter, so a seam always has two real implementations to hold it honest. The in-house one stays the default until a side-by-side on a small fixed input, kept outside the repo, says otherwise. A missing tool stops the step and names itself. The first is `beat_this` for beats and downbeats (`editor/beat_this.py`).

## Consequences

`docs/studio-goal.md` lists where each capability's idea came from. Footage editing, stock, captions, and kits stop growing until a real piece needs more from them. Switching to one of these projects wholesale was weighed and declined: none of them checks a master against a platform's requirements, and the faults that reached a human in review came from the models and the planning, which any of them would inherit.
