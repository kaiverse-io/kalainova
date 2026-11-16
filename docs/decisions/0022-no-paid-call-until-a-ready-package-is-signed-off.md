# 0022. No paid call until a person signs off a package that is ready to buy

Status: accepted · 2026-11-16. Extends 0007 (humans gate publish), 0016 and 0020 (the animatic gate). Built on 0023 (the provider contract).

## Context

Paid generation is wasted when it is triggered by mistake, or when its inputs are vague enough that the take misses and is made again. The first paid run showed both:

- The first paid shot ran with the plan's own warning that it held a face for 5 s, past the 3.2 s a model holds one. That is a predicted retake, and nothing stopped it.
- Nothing said what a good take had to show, so there was nothing to judge the take against.
- Start stills were paid for before anyone looked at what would be asked.
- A forced re-run asks again for files already paid for. It showed in a rehearsal as $0.04 of music the job already had.
- An agent recorded the operator's verdicts with `--reviewer <their name>`, and a job's cap and pins were changed by hand in `job.json`.

A per-job cost cap limits how much goes wrong. It never asks whether a call is ready to buy. The engine is meant to run as a tool agents drive at volume, so the check has to scale: machines check what can be checked, and people decide the rest.

## Decision

1. **A package per paid stage.** `kalainova package <job> stills|motion` rehearses the job as it is now (nothing sent, nothing spent) and writes the paid calls of that stage to `<job>/packages/<stage>-<nonce>.json`.
   - A call that writes a file is a **request**:
     - the router's content key;
     - the provider, and the model it is routed to;
     - its ceiling, which is the corrected estimate;
     - what the engine asked for, and each vendor payload with its digest.

     An uploaded file is named in the payload by its bytes (`providers/payloads.py`).
   - A paid call that writes no file, such as the judge reading a still, is an **allowance**: so many calls of one capability, provider and model, each at most so much.
   - A motion package is refused while any still is unmade, because its keys would name stand-ins.
   - Paid work no rehearsal covers takes an allowance package written from the command line, for one job or every job in the studio: the plan, research, a look sheet, a provider check.
   - A package is canonical JSON with its studio, job, nonce and expiry: 24 h for a stage, at most 30 days for an allowance.
2. **Readiness.** Each package carries a verdict per paid call (`readiness.py`): ready, risks or blocked. The checks are free and need no model.
   - **Block**: the call cannot be bought as it stands. A face with no reference picture, longer than the model makes, a field the vendor would refuse, a plan that cannot be made as written, motion before the animatic is accepted, a start frame that is not the accepted still.
   - **Risk**: the call is likely to need a retake. A prompt under 12 words, a moving shot with no `shot.must_show`, a face held past what a model holds, nothing saying what moves, and the plan's other warnings, each attached to its shot.
3. **Success is stated before it is bought.** A moving shot says what a take must show to be kept (`shot.must_show`), and the planner writes it. A take is judged against it, and a retake names the part it missed.
4. **A person signs it off.** `kalainova sign-off <package> --by NAME` runs only at a terminal.
   - It prints the verdict, each finding with its fix, what each call makes and its ceiling.
   - It asks for a reason for each risk, then for the first 8 characters of the package's hash.
   - It writes `<package>.signoff.json`: the hash of the bytes read, the name, the time, and each reason.
   - A blocked package cannot be signed off.
   - Agents build packages and never sign them off.
5. **The router enforces it** for every provider that costs money, outside a rehearsal, as one step under a studio-wide lock (`gates.admit`):
   - spend is not stopped (`<studio>/STOP`);
   - the studio's limits hold: `<studio>/limits.json`, set by a named person at a terminal, sets a UTC daily and monthly ceiling over every job's dated ledger lines, open reservations included;
   - a signed-off, unexpired package of this studio and job covers the call at or under its ceiling, and the request has not been spent. The sign-off must match the package's bytes and answer every risk. Each use goes into `<studio>/packages/spent.jsonl`;
   - then the estimate is reserved on the job's ledger.

   The transport sends no payload whose digest was not signed off (`Context.signed`). A call that fails with nothing billed gives its entry back; a timeout, or a call billed then failed, keeps it spent. Each ledger line names the package, the entry and who signed it off.
6. **Nothing turns it off.** There is no brief field, flag or environment variable. With no limits or no signed-off package, a paid call refuses and says what is missing. Free providers and rehearsals need none of it.
7. **A retake is a new request**, so it needs its own package and sign-off.
8. **How it scales.**
   - The checks run before a person is asked, so they review findings, not raw requests.
   - Each accepted risk, with its reason, is on record beside the verdict on the take that followed. Each check can then be measured against what people kept, and sharpened or dropped.
   - Once a check agrees with people, ADR 0017's `by-exception` level can let a stream's READY packages be signed off by policy, with a person asked only about risks and blocks. That level is not built yet.

This is a guard against mistakes, not a lock against an agent that sets out to get around it. Keeping vendor keys from such an agent is a separate concern, and a gateway that holds them can be added behind the transport (ADR 0023) if one is ever needed.

## Consequences

- Every dollar traces to a person's sign-off of exact calls whose risks they answered.
- A call nobody looked at, a vague prompt, a missing reference, a second run of the same request or a loop is refused before it spends. A rebuild costs nothing.
- Each paid stage adds a person's step: read the findings, answer them, sign off. Fixing the findings cuts the retakes that cost more.
- A package goes stale when its inputs, prices or mapping change, and the run refuses.
- Studio limits count ledger lines from this version on: earlier lines carry no date.

## Alternatives considered

- **Cryptographic signatures against a root-owned trust file.** Built first, then dropped. They guard against a hostile agent forging a sign-off, which is not the goal, and they need a key and administrator setup on every machine, which does not scale to agent VMs.
- **Policy only** ("agents never approve"). It has already failed once.
- **A spend cap alone.** It limits damage; it does not ask whether a call is ready.
- **A tolerance on the signed price.** It pays more than was signed off; a higher price means a new package.
- **A model judging every prompt for vagueness.** It is useful later, as a `by-exception` check. It costs money on every package, and a rule people can read comes first.
