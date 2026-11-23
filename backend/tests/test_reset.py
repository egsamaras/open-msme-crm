"""The database reset command refuses unless it is clearly safe and clearly intended."""

import pytest

from app.core.config import Settings
from app.db import reset


def test_reset_needs_yes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called = []
    monkeypatch.setattr(reset, "_recreate", lambda url: called.append(url))
    assert reset.main([]) == 1
    assert "Re-run with --yes" in capsys.readouterr().err
    assert called == []


def test_reset_refuses_production(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prod = Settings(environment="production", jwt_secret="x" * 40)
    monkeypatch.setattr(reset, "get_settings", lambda: prod)
    called = []
    monkeypatch.setattr(reset, "_recreate", lambda url: called.append(url))
    assert reset.main(["--yes"]) == 2
    assert "production" in capsys.readouterr().err
    assert called == []
