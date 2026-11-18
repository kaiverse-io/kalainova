# How to run the engine on another machine

The engine is a package. Installed on a laptop, a server or an agent's VM, it knows everything a source checkout knows, because its prompts, default config, schemas, fonts, job template, directions and judge runners ship inside it (ADR 0027). CI proves this on every change: `just ci-wheel` builds the wheel, installs it alone in an empty folder, and runs the engine there.

## Install it

It is not on a package index yet. Build the wheel from a checkout, or take the one CI builds, and install that file:

```bash
uv build --wheel                          # in a checkout: writes dist/kalainova-<version>-py3-none-any.whl
uv tool install dist/kalainova-*.whl      # or: pip install dist/kalainova-*.whl
kalainova --help
```

## Where a studio's work lives

`KALAINOVA_HOME` names the studio folder: jobs, kits, streams, packages and limits. Left unset, it is this user's own data folder on this machine (on macOS `~/Library/Application Support/kalainova`). It is never inside the package, and never a checkout.

```bash
export KALAINOVA_HOME=/path/to/studio
```

The first version assumes one machine writes a studio folder at a time. Several machines or agents writing one studio at once need storage built for it; a synced folder is not assumed to be safe.

## A studio's own settings

`KALAINOVA_CONFIG` names the studio's private config. It is laid over the engine's defaults, table by table. It is where a studio sets:

- its look (`visual_style`), since the engine adds none of its own;
- the models it uses, and corrections to a model's `limits`;
- its own version of a direction (`directions`);
- its judges.

```bash
export KALAINOVA_CONFIG=/path/to/studio/studio.yaml
kalainova guide                   # every direction, its version, and which layer it comes from
kalainova guide <model>           # what a model takes, every limit with its source, or "unknown"
kalainova models refresh          # the recorded limits against what vendors publish now
```

## Judges

A judge runs in its own environment, with its own weights, both outside the package. Its command names the engine's runner as `{runners}/<script>.py`, which resolves to wherever the package is installed:

```yaml
judges:
  lipsync:
    - name: syncnet
      command: [/path/to/syncnet-env/bin/python, "{runners}/syncnet_run.py", --repo, /path/to/syncnet-src]
```

`kalainova judges` lists every configured judge as ready, or names what this machine lacks: the interpreter, the runner, or a file the command names. It runs nothing.

## Keys

A key never goes in the package, a job, a prompt, a trace, a skill or a config file. The engine reads keys from the environment. On an agent VM, the platform injects them at run time: short-lived, scoped to the work, from its secret store or workload identity. Spend still needs a person's sign-off on that machine (`docs/how-to/sign-off-paid-work.md`).
