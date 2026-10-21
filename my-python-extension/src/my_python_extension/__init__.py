from my_python_extension._my_python_extension import hello_from_bin


def hello() -> str:
    return hello_from_bin()


__all__ = ["hello_from_bin", "hello"]
