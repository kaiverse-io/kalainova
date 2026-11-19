"""A local model that listens, as a judge that compares songs (judges.song).

What a reading cannot say, whether vocals sound tuned, whether a groove stumbles, whether a song
stops abruptly, a model trained on sound can be asked. This runs one on this machine, through
MLX: no call leaves it, nothing is charged, and the same files are heard the same way every time,
because the weights are pinned to one revision, windows are taken at fixed places, and decoding
is greedy.

A small model asked for a score out of ten gives every song the same one, so it is asked to
compare. The songs of one run are compared in pairs, each pair in both orders so a model that
favours whichever comes first cannot win that way, window by window: the start, the middle, and
the end, `--window-sec` each. Each answer names the closer of the two to a professional release,
aspect by aspect, or says they are the same. The prompt is a versioned file in prompts/.

Writes {path: {aspect: share}}: for each aspect, the share of comparisons the song won, a tie
counting half. A share says how a song stood against the others in its run, never against a fixed
mark, so a judge ranks takes and never blocks one. One song alone is not judged.

    python listen_run.py --model REPO --revision SHA --prompt prompts/judge_song.md
        --out scores.json song.wav song.wav [song.wav ...]
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_TOKENS = 300


def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout  # noqa: S603


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} is not on PATH")
    return found


def length(path: Path) -> float:
    out = _run([_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", str(path)])  # fmt: skip
    return float(out.strip() or 0)


def windows(seconds: float, width: float) -> list[tuple[str, float, float]]:
    """Where a song is heard: its start, its middle, and its end, each `width` long."""
    if seconds <= width:
        return [("the whole song", 0.0, seconds)]
    middle = max((seconds - width) / 2, 0.0)
    return [
        ("the first part of the song", 0.0, width),
        ("a part from the middle of the song", middle, width),
        ("the last part of the song, up to its very end", seconds - width, width),
    ]


def picks(text: str) -> dict[str, str]:
    """The model's answer: for each aspect, "A", "B", or "SAME". Anything else is left out."""
    found = re.search(r"\{.*\}", text, re.DOTALL)
    if not found:
        return {}
    try:
        data = json.loads(found.group())
    except json.JSONDecodeError:
        return {}
    out = {}
    for aspect, value in data.items():
        said = str(value).strip().upper() if isinstance(value, str) else ""
        if said in ("A", "B"):
            out[aspect] = said
        elif said.startswith("SAME"):
            out[aspect] = "SAME"
    return out


class Tally:
    """Comparisons won, aspect by aspect, a tie counting half to each side."""

    def __init__(self) -> None:
        self.won: dict[str, dict[str, float]] = {}
        self.met: dict[str, dict[str, int]] = {}

    def add(self, first: str, second: str, said: dict[str, str]) -> None:
        for aspect, pick in said.items():
            for name in (first, second):
                self.met.setdefault(name, {}).setdefault(aspect, 0)
                self.won.setdefault(name, {}).setdefault(aspect, 0.0)
                self.met[name][aspect] += 1
            if pick == "A":
                self.won[first][aspect] += 1.0
            elif pick == "B":
                self.won[second][aspect] += 1.0
            else:
                self.won[first][aspect] += 0.5
                self.won[second][aspect] += 0.5

    def shares(self) -> dict[str, dict[str, float]]:
        return {
            name: {a: round(self.won[name][a] / n, 4) for a, n in sorted(met.items()) if n}
            for name, met in self.met.items()
        }


class Model:
    """The model, loaded once from its pinned revision, asked greedily."""

    def __init__(self, repo: str, revision: str) -> None:
        from huggingface_hub import snapshot_download  # the judge's own environment has these
        from mlx_vlm import load

        self.model, self.processor = load(snapshot_download(repo, revision=revision))

    def ask(self, prompt: str, sounds: list[str]) -> str:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        text = apply_chat_template(
            self.processor, self.model.config, prompt, num_images=0, num_audios=len(sounds)
        )
        out = generate(self.model, self.processor, text, audio=sounds, max_tokens=MAX_TOKENS,
                       temperature=0.0, seed=0, verbose=False)  # fmt: skip
        return str(getattr(out, "text", out))


def heard(track: Path, width: float, tmp: Path) -> list[tuple[str, str]]:
    """Each window of a song, as a 16 kHz mono file, with where in the song it is."""
    out = []
    for i, (where, start, span) in enumerate(windows(length(track), width)):
        wav = tmp / f"{track.parent.name}.{track.stem}.w{i}.wav"
        _run([_tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{start}", "-t", f"{span}", "-i",
              str(track), "-ac", "1", "-ar", "16000", str(wav)])  # fmt: skip
        out.append((where, str(wav)))
    return out


def compare(model: Model, tracks: list[Path], prompt: str, width: float, tmp: Path) -> Tally:
    windows_of = {str(t): heard(t, width, tmp) for t in tracks}
    tally = Tally()
    for a, b in itertools.combinations(windows_of, 2):
        for first, second in ((a, b), (b, a)):  # both orders, so neither place is favoured
            for (where, one), (_, two) in zip(windows_of[first], windows_of[second], strict=False):
                tally.add(first, second, picks(model.ask(prompt.format(where=where), [one, two])))
    return tally


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, help="a Hugging Face repo of MLX weights")
    ap.add_argument("--revision", required=True, help="the commit the weights are pinned to")
    ap.add_argument("--prompt", required=True, type=Path)
    ap.add_argument("--window-sec", type=float, default=30.0)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args()
    found: dict[str, dict[str, float]] = {}
    if len(a.files) < 2:
        print(f"{a.files[0]}: a judge that compares needs another song", file=sys.stderr)
    else:
        model = Model(a.model, a.revision)
        with tempfile.TemporaryDirectory() as folder:
            tally = compare(model, a.files, a.prompt.read_text(), a.window_sec, Path(folder))
            found = tally.shares()
    a.out.write_text(json.dumps(found, indent=2))


if __name__ == "__main__":
    main()
