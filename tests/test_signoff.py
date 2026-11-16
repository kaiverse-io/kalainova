"""No paid call without a person's signature over exactly what it buys (ADR 0022).

Each test signs with a real OpenSSH key made for it, against a trust file made for it, and then
tries what a rogue job, a loop or a mistaken agent would: an unsigned package, an edited one, the
same request twice, a higher price, a changed payload, an old package, another studio's package,
and spend past the studio's limits. Each is refused before the vendor is reached.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess

import pytest
from fakes import Wire
from PIL import Image
from test_router import PRICES, Flaky, job_with, providers  # noqa: F401 - the autouse fixture

from kalainova import gates, packages, signatures
from kalainova.__main__ import main
from kalainova.jobfs import ContractError, Job
from kalainova.providers import base, payloads, rehearsal, router
from kalainova.providers.contract import ImageRequest, Reference, Result, TextRequest

pytestmark = [
    pytest.mark.gated,
    pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen not installed"),
]


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
def key(tmp_path, monkeypatch):
    """A person's key, and a trust file that lists it for packages and limits."""
    folder = tmp_path / "keys"
    folder.mkdir()
    private = folder / "person"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "person",
                    "-f", str(private)], check=True)  # fmt: skip
    trust = folder / "allowed_signers"
    public = (folder / "person.pub").read_text().strip()
    trust.write_text(
        f'operator@studio namespaces="{signatures.PACKAGE},{signatures.LIMITS}" {public}\n'
    )
    monkeypatch.setattr(signatures, "TRUST", trust)
    monkeypatch.setattr(signatures, "_rewritable", lambda path: "")  # a test's file is its own
    monkeypatch.setitem(base._REGISTRY, "wired", Wired)
    monkeypatch.setitem(PRICES, "wired", {"image": {"per_image": 1.0}})
    Wired.extra = {}
    Wired.transport.sent.clear()
    Wired.transport.replies.clear()
    return private


def sign(path, key, namespace=signatures.PACKAGE):
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", namespace, str(path)],
                   check=True, capture_output=True)  # fmt: skip


@pytest.fixture
def limits(tmp_path, key):
    sign(gates.write_limits(tmp_path, 10.0, 100.0, "the operator"), key, signatures.LIMITS)


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


def _stills_package(tmp_path, job, key=None, **ask):
    """Rehearse the stills in a throwaway studio, as `kalainova package` does, and sign it."""
    copy = _job(tmp_path / "rehearsal", "r-rehearsal")
    with rehearsal.opened() as dry:
        dry.phase = "stills"
        router.generate(copy, _ask(copy, **ask))
        calls = dry.report()
    path = packages.build(job, "stills", {"stopped": "", "calls": calls})
    if key is not None:
        sign(path, key)
    return path


def test_a_signed_request_goes_out_once_and_its_charge_names_the_package(tmp_path, key, limits):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job, key)
    provider, res = router.generate(job, _ask(job))
    assert provider.name == "wired" and len(Wired.transport.sent) == 1
    (charge,) = json.loads(job.ledger_path.read_text())
    assert charge["package"] == str(path.relative_to(tmp_path)) and charge["cost"] == 1.0
    assert charge["signed_by"] == "operator@studio" and charge["package_entry"] == "request 1"
    with pytest.raises(ContractError, match="request 1 was spent already"):
        router.generate(job, _ask(job), fresh=True)
    assert len(Wired.transport.sent) == 1 and job.spent() == 1.0


def test_an_unsigned_package_buys_nothing(tmp_path, key, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job)
    with pytest.raises(ContractError, match="is not signed"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == [] and job.committed() == 0


def test_a_package_edited_after_it_was_signed_buys_nothing(tmp_path, key, limits):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job, key)
    data = json.loads(path.read_text())
    data["requests"][0]["max_usd"] = 50.0
    path.write_bytes(packages.canonical(data))
    with pytest.raises(ContractError, match="does not match the file's bytes"):
        router.generate(job, _ask(job))
    path.write_text(path.read_text().replace('"max_usd": 50.0', '"max_usd":   50.0'))
    with pytest.raises(ContractError, match="not in its canonical form"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_a_request_the_package_does_not_name_buys_nothing(tmp_path, key, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job, key)
    with pytest.raises(ContractError, match="no signed package covers image on wired"):
        router.generate(job, _ask(job, prompt="another wall"))
    assert Wired.transport.sent == []


def test_a_price_above_the_signed_ceiling_buys_nothing(tmp_path, key, limits, monkeypatch):
    job = _job(tmp_path)
    _stills_package(tmp_path, job, key)
    monkeypatch.setitem(PRICES, "wired", {"image": {"per_image": 1.5}})
    with pytest.raises(ContractError, match=r"at most \$1.000, and it is now estimated"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_a_payload_changed_after_the_sign_off_is_not_sent(tmp_path, key, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job, key)
    Wired.extra = {"safety_tolerance": 6}  # the mapping changed between the sign-off and the run
    with pytest.raises(ContractError, match="not the one that was signed"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == [] and job.committed() == 0
    Wired.extra = {}  # nothing was sent, so the signed request is still there to spend
    router.generate(job, _ask(job))
    assert len(Wired.transport.sent) == 1


def test_an_uploaded_file_is_signed_by_its_bytes(tmp_path, key, limits):
    job = _job(tmp_path)
    face = tmp_path / "face.png"
    face.write_bytes(_picture())
    refs = (Reference(path=face, label="the character"),)
    path = _stills_package(tmp_path, job, key, references=refs)
    (sent,) = json.loads(path.read_text())["requests"][0]["sent"]
    assert sent["payload"]["image_url"].startswith("file:sha256:")
    router.generate(job, _ask(job, references=refs))  # uploaded as `up:face.png`, the same bytes
    (real,) = Wired.transport.payloads
    assert real["image_url"] == "up:face.png"


def test_an_expired_package_buys_nothing(tmp_path, key, limits, monkeypatch):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job, key)
    later = json.loads(path.read_text())["expires_at"]
    monkeypatch.setattr(packages, "_now", lambda: packages.dt.datetime.fromisoformat(later))
    with pytest.raises(ContractError, match="expired"):
        router.generate(job, _ask(job))


def test_a_package_copied_to_another_studio_buys_nothing(tmp_path, key):
    job = _job(tmp_path)
    path = _stills_package(tmp_path, job, key)
    other = tmp_path / "elsewhere"
    twin = _job(other)
    sign(gates.write_limits(other, 10.0, 100.0, "the operator"), key, signatures.LIMITS)
    (twin.folder / "packages").mkdir()
    for name in (path.name, path.name + ".sig"):
        shutil.copy(path.with_name(name), twin.folder / "packages" / name)
    with pytest.raises(ContractError, match="belongs to another studio"):
        router.generate(twin, _ask(twin))


def test_no_signed_limits_means_no_paid_call(tmp_path, key):
    job = _job(tmp_path)
    _stills_package(tmp_path, job, key)
    with pytest.raises(ContractError, match="has no spend limits"):
        router.generate(job, _ask(job))
    gates.write_limits(tmp_path, 10.0, 100.0, "an agent")  # written, and nobody signed it
    with pytest.raises(ContractError, match="limits.json is not signed"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_the_studio_limits_hold_across_jobs(tmp_path, key, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job, key)
    _job(tmp_path, "other", cap=None).charge("wired", "image", 9.5, "an earlier piece today")
    with pytest.raises(ContractError, match=r"committed \$9.50 today of its \$10.00 limit"):
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_a_limit_signed_for_packages_is_not_a_limit(tmp_path, key):
    job = _job(tmp_path)
    _stills_package(tmp_path, job, key)
    sign(gates.write_limits(tmp_path, 10.0, 100.0, "the operator"), key, signatures.PACKAGE)
    with pytest.raises(ContractError, match="made for another use"):
        router.generate(job, _ask(job))


def test_a_trust_file_this_user_could_rewrite_trusts_nobody(tmp_path, key, monkeypatch):
    monkeypatch.undo()  # the real check, on a file this test owns
    monkeypatch.setattr(signatures, "TRUST", tmp_path / "keys" / "allowed_signers")
    with pytest.raises(signatures.SignatureError, match="writable by this user"):
        signatures.anchor()
    monkeypatch.setattr(signatures, "TRUST", tmp_path / "nowhere")
    with pytest.raises(signatures.SignatureError, match="no trust file"):
        signatures.anchor()


def test_an_allowance_counts_its_calls(tmp_path, key, limits):
    job = _job(tmp_path)
    path = packages.allow(tmp_path, "r", capability="llm", provider="flaky", model="*", calls=2,
                          each=1.0, why="the script")  # fmt: skip
    sign(path, key)
    for _ in range(2):
        router.generate(job, TextRequest(prompt="hello"))
    with pytest.raises(ContractError, match="allowance 1 is used up"):
        router.generate(job, TextRequest(prompt="hello"))
    assert Flaky.calls == 2


def test_a_studio_wide_allowance_covers_any_job(tmp_path, key, limits):
    sign(packages.allow(tmp_path, "*", capability="llm", provider="flaky", model="*", calls=1,
                        each=1.0, why="a provider check"), key)  # fmt: skip
    router.generate(_job(tmp_path, "look-kit"), TextRequest(prompt="hello"))
    assert Flaky.calls == 1


def test_a_call_that_failed_unbilled_gives_its_entry_back(tmp_path, key, limits):
    job = _job(tmp_path)
    _stills_package(tmp_path, job, key)
    Wired.transport.replies = [ConnectionError("the vendor is down")]
    with pytest.raises(router.ProviderError, match="the vendor is down"):
        router.generate(job, _ask(job))
    assert job.committed() == 0
    router.generate(job, _ask(job))  # nothing was billed, so the signed request is still there
    assert len(Wired.transport.sent) == 2 and job.spent() == 1.0


def test_a_rehearsal_needs_no_package(tmp_path, key):
    job = _job(tmp_path)
    with rehearsal.opened():
        router.generate(job, _ask(job))
    assert Wired.transport.sent == []


def test_a_package_is_refused_when_its_rehearsal_cannot_be_signed(tmp_path, key):
    job = _job(tmp_path)
    with pytest.raises(ContractError, match="the rehearsal stopped"):
        packages.build(job, "stills", {"stopped": "the vendor would refuse", "calls": []})
    with pytest.raises(ContractError, match="makes no paid call"):
        packages.build(job, "stills", {"stopped": "", "calls": []})
    still = {"n": 1, "provider": "wired", "capability": "image", "phase": "stills", "key": "k",
             "estimate": 0.0, "requests": []}  # fmt: skip
    with pytest.raises(ContractError, match="have no price"):
        packages.build(job, "stills", {"stopped": "", "calls": [still]})
    with pytest.raises(ContractError, match="sign and run the stills package first"):
        packages.build(job, "motion", {"stopped": "", "calls": [{**still, "estimate": 1.0}]})
    judge = {**still, "key": "", "capability": "judge", "estimate": 0.02}  # writes no file
    moving = {**still, "phase": "motion", "capability": "video", "estimate": 0.7}
    motion = packages.build(job, "motion", {"stopped": "", "calls": [judge, moving]})
    assert [r["capability"] for r in json.loads(motion.read_text())["requests"]] == ["video"]


def test_the_rehearsed_and_the_real_upload_seal_alike(tmp_path):
    face = tmp_path / "face.png"
    face.write_bytes(b"face")
    addresses = ("rehearsal://upload/face.png#sha256=ab", "https://cdn/face", "data:x;base64,Zg")
    for address in addresses:
        payloads.remember(address, face)
    assert len({payloads.digest("m", {"image": a}) for a in addresses}) == 1
    assert payloads.sealed({"x": "data:image/png;base64,AAAA"})["x"].startswith("data:sha256:")


def test_signing_is_refused_away_from_a_terminal(tmp_path, key, monkeypatch, capsys):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    _job(tmp_path)
    assert main(["package", "r", "allowance", "--capability", "llm", "--provider", "flaky",
                 "--calls", "3", "--each", "0.05", "--why", "the script"]) == 0  # fmt: skip
    (path,) = (tmp_path / "jobs" / "r" / "packages").glob("*.json")
    assert "up to 3 x llm on flaky * at most $0.050 each: the script" in capsys.readouterr().out
    assert main(["sign", str(path), "--key", str(key)]) == 1
    assert "at a terminal" in capsys.readouterr().err
    assert not signatures.sig_path(path).exists()
    assert main(["packages", "r"]) == 0
    assert "NOT USABLE" in capsys.readouterr().out
    assert main(["limits", "--daily", "5", "--monthly", "50", "--by", "the operator"]) == 0
    assert "unsigned" in capsys.readouterr().out


def test_a_person_signs_at_a_terminal_by_typing_the_hash(tmp_path, key, monkeypatch, capsys):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    path = gates.write_limits(tmp_path, 5.0, 50.0, "the operator")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "not-it")
    assert main(["sign", str(path), "--key", str(key)]) == 1
    assert not signatures.sig_path(path).exists()
    monkeypatch.setattr("builtins.input", lambda prompt: packages.digest(path)[:8])
    assert main(["sign", str(path), "--key", str(key)]) == 0
    assert "by operator@studio" in capsys.readouterr().out
    assert main(["limits"]) == 0
    assert "$5.00 a day, $50.00 a month, signed by operator@studio" in capsys.readouterr().out


def test_a_file_that_is_neither_a_package_nor_limits_is_not_signed(tmp_path, key, monkeypatch):
    other = tmp_path / "job.json"
    other.write_text('{"kind": "something else"}')
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert main(["sign", str(other), "--key", str(key)]) == 1
    assert not signatures.sig_path(other).exists()
