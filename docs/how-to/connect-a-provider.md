# Connect a provider

A provider is ready when its key is in the environment. `uv run kalainova providers` shows what is ready and what each missing key unlocks. Keys never go in this repo, a job, a kit, or a prompt: store them in your system's secret store and export them from a private script (the `connect-a-provider` skill walks through it).

## An OpenAI-compatible LLM vendor

One adapter, `providers/compat.py`, serves any vendor that speaks the OpenAI chat-completions shape. Four are built in:

| Name | Key variable |
| --- | --- |
| `gemini` (its OpenAI-compatible endpoint) | `GEMINI_API_KEY` |
| `groq` | `GROQ_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `zai` (z.ai GLM) | `ZAI_API_KEY` |

The repo does not pick a model or a price for them, because ids and tiers change. In your private config (`$KALAINOVA_CONFIG`), copy the model id from the vendor's current docs:

```yaml
models:
  groq: {llm: <model id from the vendor's model list>}
prices:
  groq:
    llm: {free: true}                 # a free tier; otherwise input_per_mtok and output_per_mtok
preference:
  llm: [anthropic, groq]              # or pin one in a job: providers: {"llm": ["groq"]}
```

A vendor with no model id is not ready, so it is never tried by accident. A free tier is priced as `free: true`; read its terms first, since free tiers can train on what you send and are rate limited. To add another vendor, or move a URL, add `openai_compat: {name: {base_url: ..., env_key: ...}}` to the config.

Nothing here makes a live call. To check the real reply once, use [check-a-provider-live.md](check-a-provider-live.md).

## A vendor the engine has no adapter for

The engine asks for work in its own terms (ADR 0023), so a new vendor is one module in `src/kalainova/providers/` plus its config rows. No stage, record or prompt changes.

1. **Transport.** How the vendor's platform is reached. A vendor that answers one POST with JSON or the file itself uses `transport.Https(name, base_url, headers)`. A queue, a polling API or a storage upload gets its own `Transport` subclass, as `fal.FalQueue` is. Either one gives the adapter rehearsal, the receipt (the vendor's request id and billed units), labels, and errors in the engine's terms.
2. **Adapter.** A `Provider` subclass that names its capabilities, sets `env_key`, `rehearses = True` and `transport`, and implements one method per capability. Each method takes the engine's request (`contract.VideoRequest` and the rest) and a `Context`, maps the request to the vendor's fields, sends it through `self.transport`, and returns a `Result` with the engine's facts as fields (`seed`, `sent`, `billed_seconds`, `words`, `hits`).
3. **Config.** Model ids under `models:`, prices under `prices:`, and how each model takes references or frames under `reference_models:` and `video_models:`. The engine reads those through `Provider.inputs`.
4. **Done when** `uv run pytest tests/boundary` passes for it, and `kalainova rehearse` shows its requests for a real job. Then [check-a-provider-live.md](check-a-provider-live.md) makes one cheap paid call.
