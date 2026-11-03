"""Smoke tests for the installed package, without adding src to sys.path."""

from importlib import import_module
from importlib.resources import files

from mylib import hello


def test_public_api() -> None:
    assert hello() == "Hello from mylib!"


def test_package_resources() -> None:
    assert files("mylib").joinpath("py.typed").is_file()
    assert import_module("mylib.helpers").__package__ == "mylib.helpers"
    assert import_module("mylib.lib").__package__ == "mylib.lib"
