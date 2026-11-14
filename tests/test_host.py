from __future__ import annotations

from kalainova import host


def test_check_host_structure() -> None:
    res = host.check_host()
    assert "status" in res
    assert "python" in res
    assert res["python"]["supported"] is True
    assert "ffmpeg" in res
    assert "accelerator" in res
    assert "adapters" in res
    assert isinstance(res["missing"], list)


def test_host_cli_output(capsys) -> None:
    code = host.cli()
    captured = capsys.readouterr()
    assert "Host status:" in captured.out
    assert "Python:" in captured.out
    assert "Accelerator:" in captured.out
    assert code in (0, 1)
