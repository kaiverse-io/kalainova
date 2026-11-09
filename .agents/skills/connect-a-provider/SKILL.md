---
name: connect-a-provider
description: Help the operator connect a rented service (fal, ElevenLabs, Exa, or another listed provider) so the engine can use it, without a key ever passing through the conversation or this repo. Use when a provider shows "needs" a key, or the operator asks which keys they need or how to add one.
---

# Connect a provider

1. Run `uv run kalainova providers` to show what is ready and what each missing key unlocks.
2. Say which keys the piece actually needs. The agent session does the writing, planning, and review, so no LLM key is needed for that. Voice needs a voice key. Video and images need a video key. Search works without a key.
3. Never take a key in chat, and never write one into this repo, a job, a kit, a stream, or a prompt. The operator stores it themselves, in their system's secret store or password manager, and a private environment script outside this repo exports it.
   - macOS Keychain: store with `security add-generic-password -a "$USER" -s <KEY_NAME> -w` (it prompts, so the key never reaches the shell history). Export with `export <KEY_NAME>="$(security find-generic-password -a "$USER" -s <KEY_NAME> -w 2>/dev/null)"`.
   - Linux with libsecret: store with `secret-tool store --label=<KEY_NAME> service <KEY_NAME>`. Export with `export <KEY_NAME>="$(secret-tool lookup service <KEY_NAME>)"`.
   - Elsewhere: a gitignored `.env` outside this repo, readable only by the operator.
4. Check it from a fresh shell, as the agent sees it: load the private environment, then run `uv run kalainova providers`. A key set only in the operator's terminal does not reach the agent.
5. Tell them what the provider costs and what its terms allow. Commercial use can depend on the plan. Free sign-up credit is not a free tier. Point to the vendor's own pricing page rather than quoting a number you have not checked.
6. Record which keys exist and where they load from in the operator's private agent memory, never in this repo, and never the key itself.
