from __future__ import annotations

import pytest

from kalainova import fingerprint
from kalainova.jobfs import ContractError


def test_fingerprint_generation() -> None:
    fp = fingerprint.fingerprint(models=["model-a", "model-b"])
    assert fp["engine_version"] == "0.2.0"
    assert isinstance(fp["git_sha"], str)
    assert len(fp["prompts_hash"]) == 64
    assert len(fp["config_hash"]) == 64
    assert fp["models"] == ["model-a", "model-b"]


def test_fingerprint_verify_matches() -> None:
    job_data = {"fingerprint": {"engine_version": "0.2.0"}}
    # Should not raise
    fingerprint.verify(job_data, "0.2.0")


def test_fingerprint_verify_mismatch_raises() -> None:
    job_data = {"fingerprint": {"engine_version": "0.1.0"}}
    with pytest.raises(ContractError, match="does not match stream pinned version"):
        fingerprint.verify(job_data, "0.2.0")


def test_fingerprint_verify_unpinned_noop() -> None:
    job_data = {"fingerprint": {"engine_version": "0.1.0"}}
    fingerprint.verify(job_data, None)
    fingerprint.verify(job_data, "")
