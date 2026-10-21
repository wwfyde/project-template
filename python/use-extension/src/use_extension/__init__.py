from my_python_extension import hello
from python_extension_with_rust import hello_from_bin


def main() -> None:

    print(hello())

    print(hello_from_bin())
    print("Hello from use-extension!")
