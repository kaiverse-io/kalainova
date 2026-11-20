"""Takes judged by a frontier vision model on a subscription the studio already has, through its
own command line: Codex (`codex exec`) or Claude Code (`claude -p`) (judges.look).

What a reading cannot say, whether a take looks photographed or generated, whether it is flat
like a painting, whether hands and crowds hold together, a strong vision model can be asked. It
costs nothing beyond the subscription. The frames leave this machine for that vendor, as anything
asked of that subscription does.

The takes of one run are compared together: one picture, a row of `--frames` frames per take,
evenly spaced, each row labelled with a letter, and the model ranks every take on each aspect,
answering in a fixed JSON shape. It is asked `--votes` times with the rows in a different order
each time, so a model that favours a place cannot win by it, and the model is named (`--model`)
so a run says which model judged. A vendor can still change a model behind its name, so how
these scores agree with a person is measured (`kalainova agreement`) and kept measured.

Writes {path: {aspect: score}}: each aspect's mean place across the votes, from 1 (ranked first
every time) to 0 (last every time), and `votes_agree`, the share of votes that named the run's
most common first choice overall. The scores rank takes within one run, never against a fixed
mark, so a judge never blocks a take. One take alone is not judged.

    python look_run.py --cli codex --bin codex [--model NAME] --prompt prompts/judge_takes.md
        --out scores.json clip.mp4 clip.mp4 [clip.mp4 ...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASPECTS = ("picture", "depth", "physics", "eyes", "body", "overall")
ROW_HEIGHT = 480  # each frame's height in the picture: enough to see a face and hands
SHEET_MOST = 3600  # the picture's height at most; rows shrink to fit more takes
LABEL_WIDTH = 60
NESTED = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")  # set inside a session; a judge runs on its own


def _run(args: list[str], cwd: Path) -> str:
    env = {k: v for k, v in os.environ.items() if k not in NESTED}
    done = subprocess.run(args, capture_output=True, text=True, cwd=cwd, env=env,  # noqa: S603
                          stdin=subprocess.DEVNULL, timeout=900, check=True)  # fmt: skip
    return done.stdout


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} is not on PATH")
    return found


def frame_times(seconds: float, count: int) -> list[float]:
    """Evenly spaced through the clip, each at the middle of its share, so none is a fade."""
    return [round((i + 0.5) * seconds / count, 3) for i in range(count)]


def orders(n: int, votes: int) -> list[list[int]]:
    """Which take sits in which row for each vote: turned by a different step each time, and
    reversed every other vote, so no take keeps one place."""
    step = max(1, n // max(votes, 1))
    out = []
    for v in range(votes):
        turned = [(i + v * step) % n for i in range(n)]
        out.append(turned[::-1] if v % 2 else turned)
    return out


def places(ranking: list[str], letters: str) -> dict[str, float]:
    """A ranking of letters as scores: 1 for first, 0 for last, evenly between."""
    seen = [x for x in dict.fromkeys(str(r).strip().upper() for r in ranking) if x in letters]
    if len(seen) < 2:
        return {}
    last = len(seen) - 1
    return {x: (last - i) / last for i, x in enumerate(seen)}


def answer(text: str) -> dict[str, list[str]]:
    """The model's rankings, aspect by aspect, from the first JSON object in what it wrote."""
    found = re.search(r"\{.*\}", text, re.DOTALL)
    if not found:
        return {}
    try:
        data = json.loads(found.group())
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in data.items() if k in ASPECTS and isinstance(v, list)}


def frames(clip: Path, count: int, tmp: Path) -> list[Image.Image]:
    seconds = float(_run([_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(clip)], tmp).strip() or 0)  # fmt: skip
    out = []
    for i, at in enumerate(frame_times(seconds, count)):
        dst = tmp / f"{clip.parent.name}.{clip.stem}.{i}.jpg"
        _run([_tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{at}", "-i", str(clip),
              "-frames:v", "1", "-vf", f"scale=-2:{ROW_HEIGHT}", str(dst)], tmp)  # fmt: skip
        out.append(Image.open(dst).convert("RGB"))
    return out


def sheet(rows: list[list[Image.Image]], dst: Path) -> Path:
    """The takes as rows of frames, each row's letter on its left; rows shrink to keep the
    picture within SHEET_MOST, so many takes still fit one picture."""
    tall = min(ROW_HEIGHT, SHEET_MOST // len(rows))
    rows = [[f.resize((round(f.width * tall / f.height), tall)) for f in r] for r in rows]
    width = max(f.width for r in rows for f in r)
    picture = Image.new("RGB", (LABEL_WIDTH + width * len(rows[0]), tall * len(rows)))
    draw = ImageDraw.Draw(picture)
    font = ImageFont.load_default(size=40)
    for r, row in enumerate(rows):
        draw.text((14, r * tall + tall // 2 - 22), string.ascii_uppercase[r],
                  fill="white", font=font)  # fmt: skip
        for c, frame in enumerate(row):
            picture.paste(frame, (LABEL_WIDTH + c * width, r * tall))
    picture.save(dst, quality=90)
    return dst


def schema(n: int, dst: Path) -> Path:
    letters = list(string.ascii_uppercase[:n])
    ranked = {"type": "array", "items": {"type": "string", "enum": letters}}
    dst.write_text(json.dumps({"type": "object", "additionalProperties": False,
                               "required": list(ASPECTS),
                               "properties": {a: ranked for a in ASPECTS}}))  # fmt: skip
    return dst


def ask(a: argparse.Namespace, prompt: str, image: Path, tmp: Path, n: int) -> str:
    """One vote, from the named command line, in a folder of its own."""
    model = ["--model", a.model] if a.model else []
    if a.cli == "codex":
        said = tmp / "said.json"
        _run([a.bin, "exec", "--skip-git-repo-check", "-s", "read-only", "-i", str(image),
              "--output-schema", str(schema(n, tmp / "shape.json")), "-o", str(said), *model,
              prompt], tmp)  # fmt: skip
        return said.read_text()
    out = _run([a.bin, "-p", f"{prompt}\n\nThe image is the file {image.name} in this folder.",
                "--output-format", "json", "--allowedTools", "Read", *model], tmp)  # fmt: skip
    return str(json.loads(out).get("result", ""))


def judge(
    a: argparse.Namespace, clips: list[Path], prompt: str, tmp: Path
) -> dict[str, dict[str, float]]:
    shown = [frames(c, a.frames, tmp) for c in clips]
    n = len(clips)
    totals: dict[str, dict[str, list[float]]] = {str(c): {} for c in clips}
    firsts: list[str] = []
    for v, order in enumerate(orders(n, a.votes)):
        letters = string.ascii_uppercase[:n]
        image = sheet([shown[i] for i in order], tmp / f"vote{v}.jpg")
        asked = prompt.format(n=n, letters=", ".join(letters), frames=a.frames)
        said = answer(ask(a, asked, image, tmp, n))
        for aspect, ranking in said.items():
            for letter, score in places(ranking, letters).items():
                clip = str(clips[order[letters.index(letter)]])
                totals[clip].setdefault(aspect, []).append(score)
        if said.get("overall"):
            firsts.append(str(clips[order[letters.index(str(said["overall"][0]).upper())]]))
    common = Counter(firsts).most_common(1)
    agree = common[0][1] / len(firsts) if common else 0.0
    return {c: {k: round(sum(v) / len(v), 4) for k, v in sorted(t.items())} | (
                {"votes_agree": round(agree, 3)} if t else {})
            for c, t in totals.items()}  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cli", required=True, choices=("codex", "claude"))
    ap.add_argument("--bin", required=True, help="the command line's path")
    ap.add_argument(
        "--model", default="", help="the model to ask; the command line's default if none"
    )
    ap.add_argument("--prompt", required=True, type=Path)
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args()
    found: dict[str, dict[str, float]] = {}
    if len(a.files) < 2:
        print(f"{a.files[0]}: a judge that compares needs another take", file=sys.stderr)
    elif len(a.files) > 26:
        print("a judge that compares takes at most 26 at once", file=sys.stderr)
    else:
        with tempfile.TemporaryDirectory() as folder:
            try:
                found = judge(a, a.files, a.prompt.read_text(), Path(folder))
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
                print(f"not judged: {exc}", file=sys.stderr)
    a.out.write_text(json.dumps({k: v for k, v in found.items() if v}, indent=2))


if __name__ == "__main__":
    main()
