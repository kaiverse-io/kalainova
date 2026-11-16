"""A person's signature over a file, made and checked with OpenSSH (ADR 0022).

`ssh-keygen -Y sign` makes the signature and `ssh-keygen -Y verify` checks it. Each use has its own
namespace, so a signature made for one use cannot pass as another: a package (`PACKAGE`) or the
studio's limits (`LIMITS`). The engine only verifies. It holds no private key: the person signs
with a key kept where they choose, such as a Secure Enclave key in Secretive, which asks for Touch
ID, a hardware security key, or a file key.

Who may sign is listed in one trust file, OpenSSH's allowed-signers format, at `TRUST`. It is the
anchor, so the engine refuses one it could rewrite itself. It must belong to another user (root)
and be writable by neither this process nor its folder. An agent running as the operator then
cannot add its own key without an administrator's password.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .jobfs import ContractError

TRUST = Path("/etc/kalainova/allowed_signers")
PACKAGE = "kalainova-package"
LIMITS = "kalainova-limits"
SETUP = "docs/how-to/sign-off-paid-work.md"


class SignatureError(ContractError):
    """A signature is missing, made by a key nobody trusts, made for another use, or does not match
    the file's bytes; or the trust file itself cannot be trusted."""


def sig_path(path: Path) -> Path:
    return path.with_name(path.name + ".sig")


def _rewritable(path: Path) -> str:
    """Why this process could change who is trusted, or "" when it cannot."""
    for where in (path, path.parent):
        if os.access(where, os.W_OK):
            return f"{where} is writable by this user"
        if where.stat().st_uid == os.getuid():
            return f"{where} belongs to this user, who can make it writable"
    return ""


def anchor() -> Path:
    """The trust file, once it is one this process could not have written."""
    if not TRUST.is_file():
        raise SignatureError(
            f"no trust file at {TRUST}, so no signature can be checked and nothing paid runs; "
            f"list who may sign there ({SETUP})"
        )
    problem = _rewritable(TRUST)
    if problem:
        raise SignatureError(
            f"{problem}, so anything running as it could add a signer; nothing paid runs until "
            f"the trust file belongs to root and only root can write it ({SETUP})"
        )
    return TRUST


def _keygen(args: list[str], data: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    exe = shutil.which("ssh-keygen")
    if exe is None:
        raise SignatureError("ssh-keygen is not installed, so no signature can be checked")
    return subprocess.run(  # noqa: S603 - ssh-keygen, with arguments this module builds
        [exe, *args], input=data, capture_output=True, timeout=60, check=False
    )


def signer(path: Path, namespace: str) -> str:
    """Who signed `path` (its `.sig` beside it) for `namespace`, as the trust file names them.
    Raises unless a trusted key signed exactly these bytes for exactly this use."""
    sig = sig_path(path)
    if not sig.is_file():
        raise SignatureError(f"{path.name} is not signed; a person signs it: kalainova sign {path}")
    trust = anchor()
    found = _keygen(["-Y", "find-principals", "-s", str(sig), "-f", str(trust)])
    names = found.stdout.decode().split() if found.returncode == 0 else []
    if not names:
        raise SignatureError(f"{path.name} was signed by a key the trust file does not list")
    data = path.read_bytes()
    for name in names:
        checked = _keygen(
            ["-Y", "verify", "-f", str(trust), "-I", name, "-n", namespace, "-s", str(sig)], data
        )
        if checked.returncode == 0:
            return name
    raise SignatureError(
        f"{path.name}: the signature does not match the file's bytes, or was made for another use "
        f"than {namespace}"
    )


def sign(path: Path, key: Path, namespace: str) -> Path:
    """Sign `path` with the person's key. ssh-keygen talks to them directly (a passphrase, a touch,
    or Touch ID through the key's agent), so nothing here sees the private key."""
    sig = sig_path(path)
    sig.unlink(missing_ok=True)
    exe = shutil.which("ssh-keygen")
    if exe is None:
        raise SignatureError("ssh-keygen is not installed")
    done = subprocess.run(  # noqa: S603 - ssh-keygen, with arguments this module builds
        [exe, "-Y", "sign", "-f", str(key), "-n", namespace, str(path)], check=False
    )
    if done.returncode != 0 or not sig.is_file():
        raise SignatureError(f"ssh-keygen did not sign {path.name} (exit {done.returncode})")
    return sig
