"""Test CLI orchestration without creating accounts in a developer database."""

import argparse
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from api.cli import auth as manage


def test_password_prompt_checks_confirmation_and_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(["long-password-value", "different-value"])
    monkeypatch.setattr(manage, "getpass", lambda prompt: next(answers))
    with pytest.raises(ValueError, match="do not match"):
        manage.read_password()
    answers = iter(["short", "short"])
    with pytest.raises(ValueError, match="12 to 1024"):
        manage.read_password()
    answers = iter(["long-password-value", "long-password-value"])
    assert manage.read_password() == "long-password-value"


@pytest.mark.asyncio
async def test_create_and_reset_dispatch_without_printing_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = MagicMock()
    repository.create_user = AsyncMock(return_value=MagicMock(id="created-id"))
    repository.set_password = AsyncMock()
    monkeypatch.setattr(manage, "PasswordRepository", lambda sessions: repository)
    monkeypatch.setattr(manage, "engine", MagicMock(dispose=AsyncMock()))
    args = argparse.Namespace(
        action="create-user",
        username="alice",
        display_name="Alice",
    )
    password = "keep-password-out-of-stdout"
    await manage.execute(args, password)
    repository.create_user.assert_awaited_once_with(
        "alice", password, display_name="Alice"
    )
    args.action = "set-password"
    await manage.execute(args, password)
    repository.set_password.assert_awaited_once_with("alice", password)
    assert password not in capsys.readouterr().out


def test_database_failure_never_prints_credential_parameters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["auth.manage", "set-password", "alice"])
    monkeypatch.setattr(manage, "read_password", lambda: "never-print-this-password")
    monkeypatch.setattr(
        manage,
        "execute",
        AsyncMock(side_effect=SQLAlchemyError("hash-bound-parameter-secret")),
    )
    with pytest.raises(SystemExit) as error:
        manage.main()
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "Database operation failed" in message
    assert "secret" not in message
    assert "never-print" not in message
