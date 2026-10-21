"""这是一个简单脚本"""

# /// script
# requires-python = ">=3.11"
# dependencies = []
# [tool.uv]
# exclude-newer = "P7D"
# require-build-hashes = true
# preview-features = ["build-dependency-hashes"]
# ///

import argparse
from unittest import result


def run():
    pass


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=8000)
    parser.add_argument("-d", "--debug", action="store_true")


def main():

    args = parse_args()
    result = run()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(error)
        raise SystemExit(1) from error
