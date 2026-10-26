"""Restrict image references only while executing an HTTP image tool request."""

import ipaddress
import socket
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit

import httpx2
import requests

_http_image_request: ContextVar[bool] = ContextVar("http_image_request", default=False)


class ImageSourceError(ValueError):
    """An HTTP caller supplied a source outside the public image boundary."""


def _public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (
        ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
    )


def validate_public_image_url(source: str) -> None:
    """Resolve on the worker and reject any non-public destination address.

    This is not DNS pinning: transport resolution still happens separately.
    Redirects are disabled by get_image_reference while this guard is enabled.
    """
    if (
        not source.startswith(("https://", "http://"))
        or source != source.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in source)
    ):
        raise ImageSourceError("Image references require a public HTTP(S) URL")
    try:
        parsed = urlsplit(source)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ImageSourceError("Invalid image URL") from None
    if (
        not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        raise ImageSourceError("Image URLs cannot contain credentials or invalid hosts")
    if hostname.rstrip(".").lower() == "localhost" or hostname.rstrip(
        "."
    ).lower().endswith(".localhost"):
        raise ImageSourceError("Image URLs cannot access local or private addresses")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = socket.getaddrinfo(
                hostname,
                port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError, UnicodeError:
            raise ImageSourceError("Could not resolve the image host") from None
        if not addresses or not all(
            isinstance(result[4][0], str) and _public_address(result[4][0])
            for result in addresses
        ):
            raise ImageSourceError(
                "Image URLs cannot access local or private addresses"
            )
    else:
        if not _public_address(hostname):
            raise ImageSourceError(
                "Image URLs cannot access local or private addresses"
            )


def guard_image_source(source: str) -> None:
    """Leave direct Python calls unchanged; HTTP calls allow public URLs/data only."""
    if not _http_image_request.get():
        return
    if source.startswith("data:image/") and ";base64," in source:
        return
    validate_public_image_url(source)


@contextmanager
def http_image_sources(image_urls: object = None) -> Generator[None]:
    """Enable in the API worker around source validation and the entire tool call."""
    token = _http_image_request.set(True)
    try:
        if image_urls is None:
            sources = []
        elif isinstance(image_urls, str):
            sources = (
                [image_urls]
                if image_urls.startswith("data:")
                else [
                    item.strip()
                    for item in image_urls.replace("，", ",").split(",")
                    if item.strip()
                ]
            )
        elif isinstance(image_urls, list):
            sources = image_urls
        else:
            raise ImageSourceError("Image references must be strings")
        for source in sources:
            if not isinstance(source, str):
                raise ImageSourceError("Image references must be strings")
            guard_image_source(source)
        yield
    finally:
        _http_image_request.reset(token)


def get_image_reference(
    source: str,
    *,
    timeout: float = 180,
    client: httpx2.Client | None = None,
) -> requests.Response | httpx2.Response:
    """Fetch a reference, refusing redirects for HTTP tool invocations."""
    protected = _http_image_request.get()
    if protected:
        validate_public_image_url(source)
    if client is not None:
        response = (
            client.get(source, follow_redirects=False)
            if protected
            else client.get(source)
        )
    else:
        response = (
            requests.get(source, timeout=timeout, allow_redirects=False)
            if protected
            else requests.get(source, timeout=timeout)
        )
    if protected and 300 <= response.status_code < 400:
        response.close()
        raise ImageSourceError("Image reference redirects are not allowed")
    return response
