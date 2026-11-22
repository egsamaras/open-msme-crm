import pytest
from pydantic import ValidationError

from app.core.config import _DEV_SECRET, Settings


def test_blank_jwt_secret_falls_back_to_dev_default() -> None:
    assert Settings(jwt_secret="", _env_file=None).jwt_secret == _DEV_SECRET  # type: ignore[call-arg]


@pytest.mark.parametrize("secret", ["", "short"])
def test_production_refuses_weak_secret(secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret=secret, _env_file=None)  # type: ignore[call-arg]


def test_production_accepts_strong_secret() -> None:
    s = Settings(environment="production", jwt_secret="x" * 40, _env_file=None)  # type: ignore[call-arg]
    assert not s.is_dev
