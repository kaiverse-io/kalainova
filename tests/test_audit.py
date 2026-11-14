from __future__ import annotations

from kalainova import audit


def test_audit_provider_independence() -> None:
    fake_cfg = {
        "preference": {
            "image": ["fal", "local"],
            "video": ["fal"],
            "separate": [],
            "music": ["elevenlabs", "fal"],
        }
    }
    rep = audit.audit_provider_independence(fake_cfg)
    assert rep["total_capabilities"] == 4
    caps = rep["capabilities"]
    assert caps["image"]["diversity_status"] == "single-vendor-with-local"
    assert caps["video"]["diversity_status"] == "single-vendor"
    assert caps["video"]["lock_in_risk"] is True
    assert caps["separate"]["diversity_status"] == "local-only"
    assert caps["music"]["diversity_status"] == "multi-vendor"
    assert caps["music"]["lock_in_risk"] is False

    table = audit.format_table(rep)
    assert "Provider Independence Audit" in table
    assert "video" in table
