"""Provision local credentials: uv run python -m api.cli.auth --help.

Run from api/ so existing Settings loads the deployment's normal configuration.
Passwords are read using getpass, never command-line arguments or log output.
"""

import argparse
import asyncio
from getpass import getpass

from sqlalchemy.exc import SQLAlchemyError

from api.repositories.password import (
    PasswordRepository,
    normalize_username,
    validate_new_password,
)
from api.core.db import AsyncSessionLocal, engine


def read_password() -> str:
    password = getpass("Password: ")
    if password != getpass("Confirm password: "):
        raise ValueError("Passwords do not match")
    return validate_new_password(password)


async def execute(args: argparse.Namespace, password: str) -> None:
    repository = PasswordRepository(AsyncSessionLocal)
    try:
        if args.action == "create-user":
            user = await repository.create_user(
                args.username,
                password,
                display_name=args.display_name or args.username,
            )
            print(
                f"Created user {user.id}; enable auth.password and include password in auth.providers to sign in."
            )
        else:
            await repository.set_password(args.username, password)
            print("Password updated; existing login sessions are no longer valid.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage local password accounts; no public signup or default password."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser(
        "create-user", help="Create a local user and password identity"
    )
    create.add_argument("username")
    create.add_argument("--display-name")
    reset = actions.add_parser(
        "set-password", help="Reset password and invalidate existing sessions"
    )
    reset.add_argument("username")
    args = parser.parse_args()
    try:
        args.username = normalize_username(args.username)
        password = read_password()
        asyncio.run(execute(args, password))
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    except SQLAlchemyError:
        # Database exceptions can include bound credential hashes. Give a safe
        # operational error instead of dumping SQL parameters to the terminal.
        parser.exit(
            2, "Database operation failed; check connectivity and run the migrations.\n"
        )
    except EOFError, KeyboardInterrupt:
        parser.exit(130, "Cancelled\n")


if __name__ == "__main__":
    main()
