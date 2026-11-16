# How to sign off paid work

Nothing paid runs until a person has signed for it (ADR 0022). A rehearsal, a free provider and the drawn route need none of this.

You set three things up once: a key, the trust file, and the studio's limits. Then each paid stage is three steps: build the package, read it, sign it.

## Once: a key to sign with

Any SSH key works. Use one that asks for you on every signature, so nothing running as you can sign silently.

- **Secretive** (recommended on a Mac): it keeps the key in the Secure Enclave and asks for Touch ID each time. Create a key in the app, set "Require authentication" on it, and export its public key, for example to `~/.ssh/kalainova.pub`. Point `SSH_AUTH_SOCK` at Secretive's socket in the shell you sign from.
- **A hardware key** (YubiKey and similar): `ssh-keygen -t ed25519-sk -f ~/.ssh/kalainova`. Each signature needs a touch.
- **A file key with a passphrase**: `ssh-keygen -t ed25519 -f ~/.ssh/kalainova`. This is the weakest choice: an agent that can read the file and learn the passphrase can sign.

Name the key once: `export KALAINOVA_SIGNING_KEY=~/.ssh/kalainova.pub`. With Secretive or another agent, use the public key; with a file key, either works.

## Once: the trust file

The engine checks signatures against one file it cannot change itself. Write it as an administrator:

```bash
sudo mkdir -p /etc/kalainova
echo "operator@studio namespaces=\"kalainova-package,kalainova-limits\" $(cat ~/.ssh/kalainova.pub)" \
  | sudo tee /etc/kalainova/allowed_signers
sudo chmod 644 /etc/kalainova/allowed_signers
```

`operator@studio` is the name the ledger records as the signer; use any name you like. A second person gets a second line. The engine refuses the file if you, or anything running as you, could edit it or its folder.

## Once: the studio's limits

```bash
uv run kalainova limits --daily 5 --monthly 40 --by "your name"
uv run kalainova sign "$KALAINOVA_HOME/limits.json"
```

The limits count every job in the studio, by UTC day and month, open reservations included. `uv run kalainova limits` shows them and what is committed so far. To change them, set them again and sign again; until you sign, nothing paid runs.

## Each paid stage

1. **Build the package.** `uv run kalainova package <job> stills` rehearses the job and lists every paid call the animatic will make: model, ceiling, the fields sent to the vendor, the schema verdict, and the total.
2. **Read it.** The same lines print again when you sign. Each uploaded file is named by its hash, so the package names exact bytes.
3. **Sign it.** `uv run kalainova sign <job>/packages/stills-<nonce>.json`. Type the first eight characters of the hash it shows, then confirm with Touch ID, a touch or your passphrase.
4. **Run the stage.** `uv run kalainova animatic <job>`. Each paid call is spent against its signed entry, once.
5. After you accept the animatic: `uv run kalainova package <job> motion`, read, sign, then `uv run kalainova make <job>`.

`uv run kalainova packages <job>` shows each package the job can spend under: signed or not, expired, and how much is spent.

## Paid work no rehearsal covers

The plan, research, a look sheet and a provider check make paid calls outside the stills and motion stages. Sign an allowance for them:

```bash
uv run kalainova package <job> allowance --capability llm --provider anthropic \
  --calls 20 --each 0.10 --why "plan and writing"
```

Use `*` in place of the job for an allowance any job in the studio may use, such as a look sheet's scratch job. `--model` names the model the router sends to (the default is any model), and `--days` how long it lasts (at most 30).

## When a paid call refuses

The message names what is missing:

- **no trust file**, or the trust file is writable by you: set it up as above.
- **no spend limits**, or `limits.json is not signed`: set and sign them.
- **no signed package covers ...**: build one for the stage and sign it.
- **signed ... at most $X, and it is now estimated at $Y**: the price went up since you signed. Build the package again and sign the new figure.
- **was spent already**: that exact request ran under this package. A retake is a new request, and needs its own package.
- **the request is not the one that was signed**: a mapping, a config row or an input changed after you signed. Build the package again.
- **the studio has committed $X today of its $Y limit**: wait for the next UTC day, or sign higher limits.

## What this does not stop

The checks run inside the engine, as your user. They stop accidents, loops and agents that use the engine. An agent that edits the engine, deletes the spend log, or calls a vendor with your key itself is not stopped here. The spend broker (ADR 0022) closes that, and vendor-side limits help where a vendor offers them. Keep vendor keys out of any shell an agent runs in.
