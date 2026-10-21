from python_extension_with_rust._core import hello_from_bin


def hello() -> str:
    return hello_from_bin()


__all__ = ["hello_from_bin"]
