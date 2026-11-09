---
name: break-down-a-piece
description: Write BREAKDOWN.md in a job folder, saying how a finished piece was made, what was used, what it cost, what review found, and what is still open. Use when a piece is handed to the operator, or when they ask how something was made or what it used.
---

# Break down a piece

The operator reads this to trust the piece and to change it later. Write it from the job's own records, not from memory. It lives in the job folder and never in this repo.

## Sources

- `job.json` and `script_packet.json`: the brief, the route, the beats.
- `asset_manifest.json`: the provider and model behind every asset. `ledger.json`: every charge.
- `uv run kalainova provenance <job>`: seeds, weights, licences, hashes.
- `qa.json`, `uv run kalainova bar <job>`, and `cutcheck`: the measurements.
- `config/studio.yaml` `licences`, and each tool's own licence for anything outside the engine.
- The conversation: the operator's decisions, and what you found and fixed.

## Sections

1. **The file.** Path, length, format, loudness, size, cost, and status: made, reviewed, approved, or published.
2. **How we got here.** One row per decision: what was asked, what it settled.
3. **What was used.** One row per tool or service: its role, where it ran, its cost, and its licence. Say plainly which services were set up but not used, and which parts no model made.
4. **The piece.** Beat by beat: time, line, what moves.
5. **The steps.** The commands in order, with how long the engine stages took.
6. **What review found.** Each fault, how it was found, and the fix. Name engine faults as engine faults.
7. **Final measurements.** Each with its limit. Say that a clean bar means no measured defect, not a good piece.
8. **Not done, and what to know.** Not heard, not approved, placeholders, file size, keys not yet wired in, and side effects on the machine (installed tools or skills, telemetry).
9. **Files.** What to edit to change the piece, and the command that remakes it.
10. **Next.** Three to five options, the operator's choice first.

Keep it factual and specific: numbers over adjectives, and no claim the records do not support.
