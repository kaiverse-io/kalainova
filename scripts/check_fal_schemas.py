"""Compare the field names the active studio config and the fal adapter use with fal's schemas.

Free: fal serves each model's input schema with no key. Not part of CI (it needs the network).
Reads whichever config is active (KALAINOVA_CONFIG, else config/studio.yaml) and says which.

    uv run python scripts/check_fal_schemas.py
    uv run python scripts/check_fal_schemas.py --rehearsal <job work>/rehearsal.json

With --rehearsal it checks the requests a rehearsal wrote down (kalainova rehearse): every field
each one would send is in the model's schema, and every field the schema requires is there.
Covers request field names only, not reply parsing, prices, or other vendors.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
URL = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="


def schema(model: str) -> tuple[set[str], set[str]]:
    """The request fields a model's input schema lists, and the ones it requires."""
    url = URL + urllib.parse.quote(model, safe="/")
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 - fixed https host
        schemas = json.load(r)["components"]["schemas"]
    found: set[str] = set()
    required: set[str] = set()
    for name, body in schemas.items():
        if name.endswith("Input") and "properties" in body and "Element" not in name:
            found |= set(body["properties"])
            required |= set(body.get("required") or [])
    return found, required


def input_fields(model: str) -> set[str]:
    return schema(model)[0]


def check_rehearsal(path: Path) -> int:
    """Each request a rehearsal wrote down, against its model's live schema."""
    report = json.loads(path.read_text())
    bad = 0
    for call in report.get("calls", []):
        if call.get("provider") != "fal":
            continue  # another vendor's requests are checked by its own adapter in the rehearsal
        for req in call.get("requests", []):
            model, sent = req["model"], set(req.get("payload") or {})
            try:
                have, need = schema(model)
            except Exception as exc:  # noqa: BLE001 - report any network or schema failure per call
                print(f"  ?  {call['n']} {model}: could not read its schema ({exc})")
                bad += 1
                continue
            problems = [f"not in schema: {sorted(sent - have)}"] if sent - have else []
            problems += [f"missing required: {sorted(need - sent)}"] if need - sent else []
            print(f"  {'XX' if problems else 'ok'} {call['n']} {model}  {'; '.join(problems)}")
            bad += bool(problems)
    return 1 if bad else 0


def _video_names(spec: dict) -> set[str]:
    names = {"prompt", "duration", *spec.get("extra", {})}
    if spec.get("takes_seed", True):
        names.add("seed")
    names |= {spec[k] for k in ("image_param", "end_image_param") if spec.get(k)}
    names.add(spec.get("aspect_param", "aspect_ratio"))
    return {n for n in names if n}


def _reference_names(cap: str, spec: dict) -> set[str]:
    names = {"prompt", *spec.get("extra", {})}
    if spec.get("images_param"):
        names.add(spec["images_param"])
    if spec.get("elements"):
        names |= {"elements", "image_urls"}
    names |= {spec[k] for k in ("start_image_param", "end_image_param") if spec.get(k)}
    if cap == "video":
        names |= {"duration", "aspect_ratio"}
        if spec.get("takes_seed", True):
            names.add("seed")
    return names


def expected(cfg: dict) -> dict[str, set[str]]:
    """Model id to the request fields the config says it is sent."""
    want: dict[str, set[str]] = {}
    for model, spec in cfg.get("video_models", {}).get("fal", {}).items():
        want[model] = _video_names(spec)
    for cap, models in cfg.get("reference_models", {}).get("fal", {}).items():
        for model, spec in models.items():
            want.setdefault(model, set()).update(_reference_names(cap, spec))
    for model, spec in cfg.get("audio_models", {}).get("fal", {}).items():
        names = {spec.get("style_field", "prompt")}
        if not spec.get("lyrics_in_prompt"):  # otherwise the words travel inside the style field
            names.add("lyrics")
        if spec.get("max_sec") and spec.get("takes_duration", True):
            names.add("duration")
        want.setdefault(model, set()).update(names)
    return want


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--rehearsal":
        return check_rehearsal(Path(sys.argv[2]))
    base = REPO / "config" / "studio.yaml"
    cfg = yaml.safe_load(base.read_text())
    private = os.environ.get("KALAINOVA_CONFIG")
    if private and Path(private).exists():
        from kalainova.config import overlay  # the engine's own rule, so this checks what runs

        cfg = overlay(cfg, yaml.safe_load(Path(private).read_text()) or {})
    print(f"config: {base}" + (f", with {private} laid over it" if private else ""))
    bad = 0
    for model, names in sorted(expected(cfg).items()):
        try:
            have = input_fields(model)
        except Exception as exc:  # noqa: BLE001 - report any network or schema failure per model
            print(f"  ?  {model}: could not read its schema ({exc})")
            bad += 1
            continue
        missing = sorted(names - have)
        note = f": not in schema: {missing}" if missing else ""
        print(f"  {'ok' if not missing else 'XX'} {model}{note}")
        bad += bool(missing)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
