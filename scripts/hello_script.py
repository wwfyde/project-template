"""这是一个示例脚本"""

# /// script
# requires-python = ">=3.14"
# dependencies = [
#    "httpx2",
# ]
# ///

import urllib

import httpx2


def main() -> None:
    url = "https://ifconfig.me/ip"
    response = httpx2.get(url)
    response.raise_for_status()
    print(response.text)


if __name__ == "__main__":
    main()
