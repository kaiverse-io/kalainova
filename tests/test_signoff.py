"""No paid call without a person's sign-off on exactly what it buys (ADR 0022).

Each test signs a package off as a person would, then tries what a mistake looks like: a package
nobody signed off, one changed after it, the same request twice, a higher price, a payload changed
since, an old package, another studio's package, and spend past the studio's limits. Each is
refused before the vendor is reached.
"""

from __future__ import annotations

import io
import json
import shutil

import pytest
from fakes import Wire
from PIL import Image
from test_router import PRICES, Flaky, job_with, providers  # noqa: F401 - the autouse fixture

from kalainova import gates, packages, readiness
from kalainova.__main__ import main
from kalainova.jobfs import ContractError, Job
from kalainova.providers import base, payloads, rehearsal, router
from kalainova.providers.contract import ImageRequest, Reference, Result, TextRequest

pytestmark = pytest.mark.gated


def _picture() -> bytes:
    out = io.BytesIO()
    Image.linear_gradient("L").resize((64, 64)).convert("RGB").save(out, format="PNG")
    return out.getvalue()


class Wired(base.Provider):
    """A paid image model behind a transport, as every rented vendor is (ADR 0023)."""

    name = "wired"
    capabilities = ("image",)
    env_key = None
    rehearses = True
    extra: dict = {}
    transport = Wire(default={"url": "u"}, files={"u": _picture()})

    def image(self, req, ctx):
        payload = {"prompt": req.prompt, "width": req.width, "height": req.height, **self.extra}
        if req.references:
            payload["image_url"] = self.transport.upload(req.references[0].path)
        reply = self.transport.send("wired/image", payload, ctx, model="wired/image")
        self.transport.fetch(reply, req.dst, at=("url",), billed=1.0)
        return Result(path=req.dst, cost=1.0, model="wired/image")


@pytest.fixture
def vendor(monkeypatch):
    """The wired vendor, registered and priced, with nothing sent yet."""
    monkeypatch.setitem(base._REGISTRY, "wired", Wired)
    monkeypatch.setitem(PRICES, "wired", {"image": {"per_image": 1.0}})
    Wired.extra = {}
    Wired.transport.sent.clear()
    Wired.transport.replies.clear()


def sign(path, by="the operator"):
    """Sign a package off as a person would, accepting each risk with a reason."""
    found = packages.load(path)["readiness"]
    return packages.sign_off(path, by, {f["id"]: "seen, and fine for a test" for f in found})


@pytest.fixture
def limits(tmp_path, vendor):
    gates.write_limits(tmp_path, 10.0, 100.0, "the operator")


NONE = lambda job, stage, calls: []  # noqa: E731 - readiness is tested in test_readiness.py


def _job(root, name="r", cap=5.0):
    folder = root / "jobs" / name
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({
        "schema_version": "0.1", "job_id": name, "strategy": "generated", "media": ["still"],
        "rights": "owned", "status": "draft", "cost_cap": cap,
        "providers": {"image": ["wired"], "llm": ["flaky"]},
    }))  # fmt: skip
    return Job(folder)


def _ask(job, prompt="a wall", references=()):
    return ImageRequest(prompt=prompt, dst=job.work / "s1.still.png", width=64, height=64,
                        references=references)  # fmt: skip


def _stills_package(tmp_path, job, signed=True, **ask):
    """Rehearse the stills in a throwaway studio, as `kalainova package` does, and sign it off."""
    copy = _job(tmp_path / "rehearsal", "r-rehearsal")
    with rehearsal.opened() as dry:
        dry.phase = "stills"
        router.generate(copy, _ask(copy, **ask))
        calls = dry.report()
    path = packages.build(job, "stills", {"stopped": "", "calls": calls}, readiness.review)
    if signed:
        sign(path)
    return path


def test_a_signed_request_goes_out_once_and_its_charge_names_the_package(tmp_path, vendor, limits):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job)
    provider, res = router.generate(job, _ask(job))
    assert provider.name == "wired" and len(Wired.transport.sent) == 1
    (charge,) = json.loads(job.ledger_path.read_text())
    assert charge["package"] == str(path.relative_to(tmp_path)) and charge["cost"] == 1.0
    assert charge["signed_by"] == "the operator" and charge["package_entry"] == "request 1"
    with pytest.raises(ContractError, match="request 1 was spent already"):
        router.generate(job, _ask(job), fresh=True)
    assert len(Wired.transport.sent) == 1 and job.spent() == 1.0


def test_an_unsigned_package_buys_nothing(tmp_path, vendor, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job, signed=False)
    with pytest.raises(ContractError, match="is not signed off"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == [] and job.committed() == 0


def test_a_package_edited_after_it_was_signed_buys_nothing(tmp_path, vendor, limits):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job)
    data = json.loads(path.read_text())
    data["requests"][0]["max_usd"] = 50.0
    path.write_bytes(packages.canonical(data))
    with pytest.raises(ContractError, match="changed after it was signed off"):
        router.generate(job, _ask(job))
    path.write_text(path.read_text().replace('"max_usd": 50.0', '"max_usd":   50.0'))
    with pytest.raises(ContractError, match="not in its canonical form"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_a_request_the_package_does_not_name_buys_nothing(tmp_path, vendor, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job)
    with pytest.raises(ContractError, match="no signed-off package covers image on wired"):
        router.generate(job, _ask(job, prompt="another wall"))
    assert Wired.transport.sent == []


def test_a_price_above_the_signed_ceiling_buys_nothing(tmp_path, vendor, limits, monkeypatch):
    job = _job(tmp_path)
    _stills_package(tmp_path, job)
    monkeypatch.setitem(PRICES, "wired", {"image": {"per_image": 1.5}})
    with pytest.raises(ContractError, match=r"at most \$1.000, and it is now estimated"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_a_payload_changed_after_the_sign_off_is_not_sent(tmp_path, vendor, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job)
    Wired.extra = {"safety_tolerance": 6}  # the mapping changed between the sign-off and the run
    with pytest.raises(ContractError, match="not the one that was signed"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == [] and job.committed() == 0
    Wired.extra = {}  # nothing was sent, so the signed request is still there to spend
    router.generate(job, _ask(job))
    assert len(Wired.transport.sent) == 1


def test_an_uploaded_file_is_signed_by_its_bytes(tmp_path, vendor, limits):
    job = _job(tmp_path)
    face = tmp_path / "face.png"
    face.write_bytes(_picture())
    refs = (Reference(path=face, label="the character"),)
    path = _stills_package(tmp_path, job, references=refs)
    (sent,) = json.loads(path.read_text())["requests"][0]["sent"]
    assert sent["payload"]["image_url"].startswith("file:sha256:")
    router.generate(job, _ask(job, references=refs))  # uploaded as `up:face.png`, the same bytes
    (real,) = Wired.transport.payloads
    assert real["image_url"] == "up:face.png"


def test_an_expired_package_buys_nothing(tmp_path, vendor, limits, monkeypatch):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job)
    later = json.loads(path.read_text())["expires_at"]
    monkeypatch.setattr(packages, "_now", lambda: packages.dt.datetime.fromisoformat(later))
    with pytest.raises(ContractError, match="expired"):
        router.generate(job, _ask(job))


def test_a_package_copied_to_another_studio_buys_nothing(tmp_path, vendor):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job)
    other = tmp_path / "elsewhere"
    twin = _job(other)
    gates.write_limits(other, 10.0, 100.0, "the operator")
    (twin.folder / "packages").mkdir()
    for name in (path.name, packages.signoff_path(path).name):
        shutil.copy(path.with_name(name), twin.folder / "packages" / name)
    with pytest.raises(ContractError, match="belongs to another studio"):
        router.generate(twin, _ask(twin))


def test_no_limits_means_no_paid_call(tmp_path, vendor):
    job = _job(tmp_path)
    _stills_package(tmp_path, job)
    with pytest.raises(ContractError, match="has no spend limits"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_the_studio_limits_hold_across_jobs(tmp_path, vendor, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job)
    _job(tmp_path, "other", cap=None).charge("wired", "image", 9.5, "an earlier piece today")
    with pytest.raises(ContractError, match=r"committed \$9.50 today of its \$10.00 limit"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_an_allowance_counts_its_calls(tmp_path, vendor, limits):
    job = _job(tmp_path)
    path = packages.allow(tmp_path, "r", capability="llm", provider="flaky", model="*", calls=2,
                          each=1.0, why="the script")  # fmt: skip
    sign(path)
    for _ in range(2):
        router.generate(job, TextRequest(prompt="hello"))
    with pytest.raises(ContractError, match="allowance 1 is used up"):
        router.generate(job, TextRequest(prompt="hello"))
    assert Flaky.calls == 2


def test_a_studio_wide_allowance_covers_any_job(tmp_path, vendor, limits):
    sign(packages.allow(tmp_path, "*", capability="llm", provider="flaky", model="*", calls=1,
                        each=1.0, why="a provider check"))  # fmt: skip
    router.generate(_job(tmp_path, "look-kit"), TextRequest(prompt="hello"))
    assert Flaky.calls == 1


def test_a_call_that_failed_unbilled_gives_its_entry_back(tmp_path, vendor, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job)
    Wired.transport.replies = [ConnectionError("the vendor is down")]
    with pytest.raises(router.ProviderError, match="the vendor is down"):
        router.generate(job, _ask(job))
    assert job.committed() == 0
    router.generate(job, _ask(job))  # nothing was billed, so the signed request is still there
    assert len(Wired.transport.sent) == 2 and job.spent() == 1.0


def test_a_rehearsal_needs_no_package(tmp_path, vendor):
    job = _job(tmp_path)
    with rehearsal.opened():
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_a_package_is_refused_when_its_rehearsal_cannot_be_signed(tmp_path, vendor):
    job = _job(tmp_path)
    with pytest.raises(ContractError, match="the rehearsal stopped"):
        packages.build(job, "stills", {"stopped": "the vendor would refuse", "calls": []}, NONE)
    with pytest.raises(ContractError, match="makes no paid call"):
        packages.build(job, "stills", {"stopped": "", "calls": []}, NONE)
    still = {"n": 1, "provider": "wired", "capability": "image", "phase": "stills", "key": "k",
             "estimate": 0.0, "requests": []}  # fmt: skip
    with pytest.raises(ContractError, match="have no price"):
        packages.build(job, "stills", {"stopped": "", "calls": [still]}, NONE)
    with pytest.raises(ContractError, match="sign and run the stills package first"):
        packages.build(job, "motion", {"stopped": "", "calls": [{**still, "estimate": 1.0}]}, NONE)
    judge = {**still, "key": "", "capability": "judge", "estimate": 0.02}  # writes no file
    moving = {**still, "phase": "motion", "capability": "video", "estimate": 0.7}
    motion = packages.build(job, "motion", {"stopped": "", "calls": [judge, moving]}, NONE)
    assert [r["capability"] for r in json.loads(motion.read_text())["requests"]] == ["video"]


def test_the_rehearsed_and_the_real_upload_seal_alike(tmp_path):
    face = tmp_path / "face.png"
    face.write_bytes(b"face")
    addresses = ("rehearsal://upload/face.png#sha256=ab", "https://cdn/face", "data:x;base64,Zg")
    for address in addresses:
        payloads.remember(address, face)
    assert len({payloads.digest("m", {"image": a}) for a in addresses}) == 1
    assert payloads.sealed({"x": "data:image/png;base64,AAAA"})["x"].startswith("data:sha256:")


def test_signing_off_and_setting_limits_need_a_terminal(tmp_path, vendor, monkeypatch, capsys):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    _job(tmp_path)
    assert main(["package", "r", "allowance", "--capability", "llm", "--provider", "flaky",
                 "--calls", "3", "--each", "0.05", "--why", "the script"]) == 0  # fmt: skip
    (path,) = (tmp_path / "jobs" / "r" / "packages").glob("*.json")
    assert "up to 3 x llm on flaky * at most $0.050 each: the script" in capsys.readouterr().out
    assert main(["sign-off", str(path), "--by", "an agent"]) == 1
    assert "at a terminal" in capsys.readouterr().err
    assert not packages.signoff_path(path).exists()
    assert main(["packages", "r"]) == 0
    assert "NOT USABLE" in capsys.readouterr().out
    assert main(["limits", "--daily", "5", "--monthly", "50", "--by", "an agent"]) == 1
    assert not (tmp_path / gates.LIMITS).exists()


def _at_a_terminal(monkeypatch, answers):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))


def test_a_person_answers_each_risk_and_types_the_hash(
    tmp_path, vendor, limits, monkeypatch, capsys
):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))  # `kalainova limits` writes the studio's
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job, signed=False)
    (risk,) = packages.load(path)["readiness"]
    assert risk["id"] == "vague_prompt:call-1" and risk["level"] == "risk"
    _at_a_terminal(monkeypatch, [""])  # no reason for the risk: not signed off
    assert main(["sign-off", str(path), "--by", "the operator"]) == 1
    _at_a_terminal(monkeypatch, ["a test wall needs no more words", "wrong"])
    assert main(["sign-off", str(path), "--by", "the operator"]) == 1
    assert not packages.signoff_path(path).exists()
    _at_a_terminal(monkeypatch, ["a test wall needs no more words", packages.digest(path)[:8]])
    assert main(["sign-off", str(path), "--by", "the operator"]) == 0
    record = json.loads(packages.signoff_path(path).read_text())
    assert record["accepted"] == {"vague_prompt:call-1": "a test wall needs no more words"}
    router.generate(job, _ask(job))
    assert len(Wired.transport.sent) == 1
    _at_a_terminal(monkeypatch, [])
    assert main(["limits", "--daily", "5", "--monthly", "50", "--by", "the operator"]) == 0
    assert main(["limits"]) == 0
    assert "$5.00 a day, $50.00 a month, set by the operator" in capsys.readouterr().out


def test_a_blocked_package_or_an_unanswered_risk_is_not_signed_off(tmp_path, vendor, limits):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job, signed=False)
    with pytest.raises(ContractError, match="give a reason to accept vague_prompt:call-1"):
        packages.sign_off(path, "the operator", {})
    sign(path)
    record = packages.signoff_path(path)
    data = json.loads(record.read_text())
    data["accepted"] = {}
    record.write_text(json.dumps(data))  # the risk's answer removed by hand
    with pytest.raises(ContractError, match="does not answer every finding"):
        router.generate(job, _ask(job))
    blocked = json.loads(path.read_text())
    blocked["readiness"].append({"id": "no_references:s1", "level": "block", "check": "x",
                                 "shot": "s1", "call": 1, "detail": "d", "fix": "f"})  # fmt: skip
    path.write_bytes(packages.canonical(blocked))
    with pytest.raises(ContractError, match="is blocked"):
        packages.sign_off(path, "the operator", {"vague_prompt:call-1": "fine"})
    assert Wired.transport.sent == []


def test_a_lip_sync_made_on_a_clip_this_stage_buys_is_signed_as_a_counted_allowance(
    tmp_path, vendor
):
    """Its input is the clip just bought, so its bytes cannot be known when the package is signed.
    An exact entry would refuse it in the real run, after the clip was already paid for."""
    job = _job(tmp_path)
    clip = {"n": 1, "provider": "wired", "capability": "video", "phase": "motion", "key": "v",
            "estimate": 0.42, "requests": []}  # fmt: skip
    syncs = [{**clip, "n": n, "capability": "lipsync", "key": f"l{n}", "estimate": 0.15}
             for n in (2, 3)]  # fmt: skip
    data = json.loads(
        packages.build(job, "motion", {"stopped": "", "calls": [clip, *syncs]}, NONE).read_text()
    )
    assert [r["capability"] for r in data["requests"]] == ["video"]
    (sync,) = data["allowances"]
    assert sync["capability"] == "lipsync" and sync["calls"] == 2
    assert sync["max_usd_each"] == pytest.approx(0.165), "a frame or two longer still fits"
    assert data["total_max_usd"] == pytest.approx(0.42 + 2 * 0.165)


def test_a_balance_that_cannot_cover_the_spend_stops_it_before_any_call(tmp_path, vendor, limits):
    """A stage that runs out of money part way leaves half a piece; so the balance is read when a
    package is built, when it is signed off, and before each call. An unreadable one never
    blocks."""
    from kalainova.providers import balances

    left = {"wired": 0.5}
    balances.READERS["wired"] = lambda: left["wired"]
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job, signed=False)  # it may spend $1.00
    assert "vendor_balance:wired" in [f["id"] for f in packages.load(path)["readiness"]]
    left["wired"] = 5.0
    balances._seen.clear()
    path = _stills_package(tmp_path / "again", job, signed=False)
    left["wired"] = 0.5  # money went between the build and the sign-off
    with pytest.raises(ContractError, match="balance is \\$0.50"):
        sign(path)
    left["wired"] = 5.0
    sign(path)
    left["wired"] = 0.5
    balances._seen.clear()
    with pytest.raises(ContractError, match="nothing was called"):
        router.generate(job, _ask(job))
    assert not Wired.transport.sent
    left["wired"] = None  # unreadable: the vendor's own refusal is the backstop
    balances._seen.clear()
    router.generate(job, _ask(job))
    assert len(Wired.transport.sent) == 1
