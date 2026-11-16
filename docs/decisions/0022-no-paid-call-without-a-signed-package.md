# 0022. No paid call without a person's signature over exactly what it buys

Status: accepted · 2026-11-16. Extends 0007 (humans gate publish), 0016 and 0020 (the animatic gate). Built on 0023 (the provider contract).

## Context

The engine spends real money on rented models. The people and agents who drive it can be wrong, and the engine is to run as a packaged tool that agents drive while nobody watches.

The first paid run showed what that means:

- An agent recorded the operator's verdicts with `--reviewer <their name>`. That was on the operator's words, but nothing stopped it doing so without them.
- A job's cap, profile and provider pins were changed by hand in `job.json`, with no record.
- The animatic gate can be turned off from the brief.
- Start stills were paid for before anyone signed anything.
- The trace named a model never called, the price table was 25% low, and a request carried a field the vendor refused (all fixed in #121 and 0023).

"Agents never approve" is a policy, not a check. A per-job cost cap limits the damage but never asks whether a call should happen at all.

Codex reviewed a draft of this decision and found its holes; the decision below takes its corrections. The main ones: a 10% price tolerance still pays more than was signed; a signature must be single use and bound to the exact payload; a local check cannot stop an agent that edits the engine or holds the vendor key.

## Decision

1. **A package per paid stage.** `kalainova package <job> stills|motion` rehearses the job as it is now (nothing sent, nothing spent) and writes the paid calls of that stage to `<job>/packages/<stage>-<nonce>.json`.
   - A call that writes a file is a **request**: the router's content key, the provider, the model it is routed to (the pin, else the provider's default), its ceiling (the corrected estimate), what the engine asked for (`Request.described()`), and each vendor payload with its digest. An uploaded file is named in the payload by its bytes (`providers/payloads.py`), so the rehearsal's payload and the paid run's are the same.
   - A paid call that writes no file, such as the judge reading a still, is an **allowance**: so many calls of one capability on one provider and model, each at most so much.
   - A motion package is refused while any still is unmade, because its keys would name stand-ins.
   - Paid work no rehearsal covers (a look sheet, research, the plan, a provider check) takes an allowance package written from the command line: `kalainova package <job|*> allowance ...`, for one job or every job in the studio.
   - A package is canonical JSON. It names its studio, its job, a nonce and its expiry (24 h for a stage, at most 30 days for an allowance).
2. **A person signs it.** `kalainova sign <file>` prints the package from its own bytes, asks the person to type the start of its hash, and signs it with `ssh-keygen -Y sign`, under the namespace `kalainova-package`. It refuses unless it runs at a terminal. The key is the person's. The recommendation is a Secure Enclave key in Secretive, which asks for Touch ID on every signature; a hardware security key or a passphrase-protected file key also work. Agents prepare packages and never sign them.
3. **The engine only verifies.** Who may sign is listed in one OpenSSH allowed-signers file at `/etc/kalainova/allowed_signers`. The engine refuses one it could rewrite: the file and its folder must belong to another user (root) and be writable by neither. An agent running as the operator then cannot add its own key without an administrator's password.
4. **The router enforces it** for every provider that costs money, outside a rehearsal, in one studio-wide step under a lock (`gates.admit`):
   - spend is not stopped (`<studio>/STOP`, the kill switch);
   - the studio's signed limits hold: `<studio>/limits.json`, signed under `kalainova-limits`, sets a UTC daily and monthly ceiling over every job's dated ledger lines, open reservations included;
   - a signed, unexpired package of this studio and this job covers the call, at or under its signed ceiling, and the request has not been spent; each use is written to `<studio>/packages/spent.jsonl`;
   - then the estimate is reserved on the job's ledger.

   The transport then refuses to send any payload whose digest the person did not sign (`Context.signed`). A call that fails with nothing billed gives its entry back. A timeout, or a call billed then failed, keeps it spent. Each ledger line names the package, the entry and the signer.
5. **Nothing turns it off.** There is no brief field, flag or environment variable. With no trust file, no signed limits or no signed package, a paid call refuses and says what is missing. Free providers and rehearsals need none of it.
6. **A retake is a new request**, so it needs its own package and signature. No automatic paid retakes becomes a mechanism.
7. **What this does not stop, and what follows.** These checks run in the engine's own process, as the operator's user. They stop accidents, loops, rogue jobs and agents that use the engine. They do not stop an agent that edits the engine, deletes `spent.jsonl` to replay a request, or calls the vendor with the key itself. Those need the next step:
   - **A spend broker**: a small service under its own OS user that alone holds the vendor key, keeps the spend log, and forwards only requests whose signature and payload digest it checks itself. ADR 0023's transports make it one more transport for the engine.
   - **Vendor-side limits** wherever a vendor offers them.

## Consequences

- Every dollar traces to a person's signed decision: the ledger line names the package and the signer, and the package names every byte sent.
- A rogue job, a loop, a forged verdict or a hand-edited cap cannot spend through the engine. The worst it does is refuse.
- Each paid stage adds a human step: build, read, sign. That is the point, until ADR 0017's autonomy levels hand a gate to automation on evidence.
- A package goes stale when its inputs, prices or mapping change, and the run refuses. A rebuild costs nothing.
- The operator sets things up once: the trust file (with `sudo`), the signed limits, and a key. Until then nothing paid runs.
- Studio limits count ledger lines from this version on: earlier lines carry no date.

## Alternatives considered

- **Policy only** ("agents never approve"). It has already failed once: the reviewer field is a string.
- **One package for the whole piece.** The moving shots cannot be keyed until the real stills exist.
- **A spend cap alone.** It limits damage. It does not ask whether a call should happen at all.
- **A tolerance on the signed price** (the draft said 10%). It authorises spending more than was signed; the ceiling is the signed figure, and a higher price means a new package.
- **minisign or age.** Sound tools, but a software key the agent can read is forgeable by the agent, and they add a dependency. OpenSSH is on every Mac and Linux machine, and its namespaces separate uses.
- **Passkeys or a web approval page.** The right fit for a hosted studio, which needs a relying party that issues challenges. They come with the broker, not before it.
- **Sigstore, in-toto, OPA or Cedar.** Built for supply chains and for policy at scale. A few explicit rules in `gates.py` are easier to audit here.
