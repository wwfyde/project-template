"""Public API for mylib."""

__all__ = ["hello"]


def hello() -> str:
    """Return a greeting to verify the library is installed and working."""
    return "Hello from mylib!"
