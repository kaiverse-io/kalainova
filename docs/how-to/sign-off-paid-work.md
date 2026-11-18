# How to sign off paid work

Nothing paid runs until a person has read what it will buy and signed it off (ADR 0022). The point is to stop a call nobody meant to make, and inputs vague enough that the take is made again. A rehearsal, a free provider and the drawn route need none of this.

## The vendor's balance

A stage that runs out of money part way stops with half a piece made. So where a vendor says what
its account has left (fal does), the engine reads it three times:

- when a package is built, a balance below what it may spend is a BLOCK;
- at sign-off, it is read again and shown beside what the package may spend, and sign-off is
  refused if it cannot cover it;
- before each paid call, read at most once a minute; a call it cannot cover is refused, and nothing
  is sent.

A balance that cannot be read (no key loaded, or no such read from the vendor) never blocks. The
vendor's own refusal stays the backstop: a refused call is not billed, its package entry comes back,
and takes already made are kept, so running the stage again does not pay for them twice.

## Once: the studio's limits

```bash
uv run kalainova limits --daily 5 --monthly 40 --by "your name"
```

Run it at a terminal; an agent cannot set limits. They count every job in the studio, by UTC day and month, open reservations included. `uv run kalainova limits` shows them and what is committed so far.

## Each paid stage

1. **Build the package.** `uv run kalainova package <job> stills` rehearses the job and prints:
   - its verdict: READY, RISKS or BLOCKED;
   - each finding, with how to fix it;
   - every paid call: its shot, what it makes, its prompt, its inputs, and the most it may cost;
   - the total.
2. **Fix what you can.** A BLOCK must be fixed: a face with no reference picture, a shot longer than the model makes, a field the vendor would refuse, motion before the animatic is accepted. A RISK is likely to cost a retake: a vague prompt, a shot that does not say what a good take must show (`shot.must_show`), a face held too long. Fix it in `script_packet.json` and build the package again. It costs nothing.
3. **Sign it off.** `uv run kalainova sign-off <job>/packages/stills-<nonce>.json --by "your name"`. It prints the package again, then asks:
   - a reason for each risk you accept;
   - the first eight characters of the package's hash.

   It writes `stills-<nonce>.signoff.json` beside the package with your name, your reasons and the hash of what you read.
4. **Run the stage.** `uv run kalainova animatic <job>`. Each paid call is spent against its entry in the package, once.
5. After you accept the animatic: `uv run kalainova package <job> motion`, fix, sign off, then `uv run kalainova make <job>`.

`uv run kalainova packages <job>` shows each package the job can spend under: its verdict, signed off or not, expired, and how much is spent.

## Paid work no rehearsal covers

The plan, research, a look sheet and a provider check make paid calls outside the stills and motion stages. Build an allowance for them, then sign it off the same way:

```bash
uv run kalainova package <job> allowance --capability llm --provider anthropic \
  --calls 20 --each 0.10 --why "plan and writing"
```

Use `*` in place of the job for an allowance any job in the studio may use, such as a look sheet's scratch job. `--model` names the model the router sends to (the default is any), and `--days` how long it lasts (at most 30).

## When a paid call refuses

The message names what is missing:

- **no spend limits**: set them.
- **no signed-off package covers ...**: build one for the stage and sign it off.
- **... at most $X, and it is now estimated at $Y**: the price went up since you signed off. Build the package again.
- **was spent already**: that exact request ran under this package. A retake is a new request and needs its own package.
- **the request is not the one that was signed**: a prompt, a mapping, a config row or an input changed after you signed off. Build the package again.
- **changed after it was signed off**, or **does not answer every finding**: the package or its sign-off was edited. Build it again and sign off again.
- **the studio has committed $X today of its $Y limit**: wait for the next UTC day, or set higher limits.
