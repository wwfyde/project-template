"""Verify an artifact's installed API, metadata and typing marker."""

import sys
import tomllib
from importlib import import_module
from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path

import mylib


def main() -> None:
    project = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["project"]
    installed = distribution(project["name"])

    assert installed.version == project["version"], installed.version
    assert installed.metadata["Requires-Python"] == project["requires-python"]
    assert installed.metadata["Description-Content-Type"] == "text/markdown"
    assert mylib.hello() == "Hello from mylib!"
    assert files("mylib").joinpath("py.typed").is_file()
    assert mylib.__file__ is not None
    module_path = Path(mylib.__file__).resolve()
    source_root = Path(sys.argv[1]).resolve().parent / "src"
    assert not module_path.is_relative_to(source_root), module_path
    assert module_path == Path(installed.locate_file("mylib/__init__.py")).resolve()
    assert installed.read_text("WHEEL") is not None
    for module in ("mylib.helpers", "mylib.lib"):
        import_module(module)

    print(f"Installed {project['name']} {installed.version}: {mylib.__file__}")


if __name__ == "__main__":
    main()
