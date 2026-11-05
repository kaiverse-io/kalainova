"""Stock fetch against a mocked Pexels API: selection, download, credits, licensed rights, reel."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


class Resp:
    def __init__(self, data=None, blob=b"", status=200):
        self._d, self._b, self.status_code = data, blob, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._d

    def iter_content(self, n):
        yield self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_pick_prefers_coverage_and_resolution():
    from kalainova import stock
    c = [{"source": "pexels", "id": str(i), "width": 1080, "height": 1920, "duration": 10, "query": q, "link": "x"}
         for i, q in enumerate(["a", "a", "a", "b", "c"])]
    c.append({"source": "pexels", "id": "lo", "width": 360, "height": 640, "duration": 10, "query": "d", "link": "x"})
    got = stock.pick(c, 3)
    assert [x["query"] for x in got] == ["a", "b", "c"]


def test_no_key_is_a_clear_error(tmp_path, monkeypatch):
    from kalainova import stock
    from kalainova.jobfs import ContractError, Job
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    (tmp_path / "job.json").write_text("{}")
    with pytest.raises(ContractError, match="PEXELS_API_KEY"):
        stock.fetch(Job(tmp_path), "anything")


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_reel_from_mocked_pexels(tmp_path, monkeypatch):
    from footage_fixtures import clip
    from kalainova import __main__ as cli, stock
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("PEXELS_API_KEY", "test")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    blobs = [clip(tmp_path / f"c{i}.mp4", seed, dur=5, size=(320, 180)).read_bytes() for i, seed in enumerate((1, 5, 6))]

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        if "videos/search" in url:
            assert headers == {"Authorization": "test"}
            q = params["query"]
            return Resp({"videos": [{"id": abs(hash(q)) % 10 ** 6 + k, "url": f"https://pexels.example/{q}/{k}", "duration": 5,
                                     "user": {"name": f"Author {k}", "url": "u"},
                                     "video_files": [{"file_type": "video/mp4", "width": 1080, "height": 1920,
                                                      "link": f"https://cdn.example/{k}.mp4"}]} for k in range(3)]})
        k = int(url.rsplit("/", 1)[1].split(".")[0])
        return Resp(blob=blobs[k % 3])

    monkeypatch.setattr(stock.requests, "get", fake_get)
    monkeypatch.setattr(cli, "REPO", tmp_path)
    (tmp_path / "jobs").mkdir()
    rc = cli.main(["reel", "ct", "Test City", "8s reel, warm, title: Test City", "--count", "4"])
    folder = tmp_path / "jobs" / "ct"
    st = json.loads((folder / "stock.json").read_text())
    assert len(st["clips"]) == 4 and all(c["credit"].startswith("Video by") for c in st["clips"])
    am = json.loads((folder / "asset_manifest.json").read_text())
    assert all(a["rights"] == "licensed" for a in am["assets"] if a["role"] == "visual")
    sp = json.loads((folder / "script_packet.json").read_text())
    assert sp["publish"]["description"].startswith("Footage: Video by")
    assert rc == 0
