"""Public reference guards run only for HTTP tool work and never fetch redirects."""

import socket
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from pytest import MonkeyPatch

from api.images import source_access
from api.images.source_access import (
    ImageSourceError,
    get_image_reference,
    guard_image_source,
    http_image_sources,
    validate_public_image_url,
)
from api.tools.images import gemini


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "/tmp/image.png",
        "../private.png",
        "http://user:secret@public.example/a.png",
        "http://@public.example/a.png",
        "http://127.0.0.1/a.png",
        "http://10.0.0.5/a.png",
        "http://172.16.0.1/a.png",
        "http://192.168.1.1/a.png",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/a.png",
        "http://0.0.0.0/a.png",
        "http://224.0.0.1/a.png",
        "http://240.0.0.1/a.png",
        "http://[::1]/a.png",
        "http://[fe80::1]/a.png",
        "http://[fc00::1]/a.png",
        "http://[::ffff:127.0.0.1]/a.png",
        "http://localhost/a.png",
        "http://localhost./a.png",
        "http://images.localhost/a.png",
        "https://public.example:0/a.png",
        "https://public.example:99999/a.png",
        " https://public.example/a.png",
        "https://public.example/\nimage.png",
    ],
)
def test_non_public_or_invalid_sources_are_rejected_before_dns(
    monkeypatch: MonkeyPatch, url: str
) -> None:
    resolver = Mock(side_effect=AssertionError("DNS should not be needed"))
    monkeypatch.setattr(source_access.socket, "getaddrinfo", resolver)
    with pytest.raises(ImageSourceError):
        validate_public_image_url(url)
    resolver.assert_not_called()


def _addresses(*addresses: str) -> list[tuple]:
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 443),
        )
        for address in addresses
    ]


@pytest.mark.parametrize(
    "addresses",
    [("10.2.3.4",), ("1.1.1.1", "192.168.1.1"), ("2606:4700:4700::1111", "::1")],
)
def test_every_dns_address_must_be_public(
    monkeypatch: MonkeyPatch, addresses: tuple[str, ...]
) -> None:
    monkeypatch.setattr(
        source_access.socket, "getaddrinfo", Mock(return_value=_addresses(*addresses))
    )
    with pytest.raises(ImageSourceError):
        validate_public_image_url("https://images.example/a.png")


def test_public_literal_and_public_dns_are_allowed(monkeypatch: MonkeyPatch) -> None:
    resolver = Mock(return_value=_addresses("1.1.1.1", "2606:4700:4700::1111"))
    monkeypatch.setattr(source_access.socket, "getaddrinfo", resolver)
    validate_public_image_url("https://1.1.1.1/a.png")
    validate_public_image_url("https://[2606:4700:4700::1111]/a.png")
    resolver.assert_not_called()
    validate_public_image_url("https://images.example/a.png")
    resolver.assert_called_once_with("images.example", 443, type=socket.SOCK_STREAM)


@pytest.mark.parametrize("result", [[], OSError("DNS private diagnostic")])
def test_unresolved_hosts_fail_closed(monkeypatch: MonkeyPatch, result: object) -> None:
    resolver = (
        Mock(side_effect=result)
        if isinstance(result, OSError)
        else Mock(return_value=result)
    )
    monkeypatch.setattr(source_access.socket, "getaddrinfo", resolver)
    with pytest.raises(ImageSourceError) as failure:
        validate_public_image_url("https://images.example/a.png")
    assert "private diagnostic" not in str(failure.value)


def test_context_validates_pass_through_sources_and_resets_after_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    resolver = Mock(return_value=_addresses("1.1.1.1"))
    monkeypatch.setattr(source_access.socket, "getaddrinfo", resolver)
    with http_image_sources("data:image/png;base64,aGVsbG8="):
        guard_image_source("data:image/png;base64,aGVsbG8=")
        with pytest.raises(ImageSourceError):
            guard_image_source("/tmp/local.png")
    resolver.assert_not_called()
    # Failed preflight must also reset the ContextVar.
    with pytest.raises(ImageSourceError):
        with http_image_sources(["http://127.0.0.1/a.png"]):
            raise AssertionError("Invalid source entered the tool")
    guard_image_source("/tmp/local.png")
    with http_image_sources(
        "https://first.example/a.png，https://second.example/b.png"
    ):
        pass
    assert resolver.call_count == 2


def test_requests_redirect_is_not_followed(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_access.socket, "getaddrinfo", Mock(return_value=_addresses("1.1.1.1"))
    )
    response = SimpleNamespace(
        status_code=302,
        close=Mock(),
        headers={"Location": "http://127.0.0.1/private.png"},
    )
    download = Mock(return_value=response)
    monkeypatch.setattr(source_access.requests, "get", download)
    with http_image_sources():
        with pytest.raises(ImageSourceError, match="redirects"):
            get_image_reference("https://images.example/a.png", timeout=20)
    download.assert_called_once_with(
        "https://images.example/a.png", timeout=20, allow_redirects=False
    )
    response.close.assert_called_once_with()


def test_httpx_redirect_is_not_followed(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_access.socket, "getaddrinfo", Mock(return_value=_addresses("1.1.1.1"))
    )
    response = SimpleNamespace(status_code=307, close=Mock())
    client = Mock()
    client.get.return_value = response
    with http_image_sources():
        with pytest.raises(ImageSourceError, match="redirects"):
            get_image_reference("https://images.example/a.png", client=client)
    client.get.assert_called_once_with(
        "https://images.example/a.png", follow_redirects=False
    )
    response.close.assert_called_once_with()


def test_guard_rechecks_dns_before_download(monkeypatch: MonkeyPatch) -> None:
    resolver = Mock(side_effect=[_addresses("1.1.1.1"), _addresses("127.0.0.1")])
    monkeypatch.setattr(source_access.socket, "getaddrinfo", resolver)
    download = Mock(side_effect=AssertionError("Private address must not be fetched"))
    monkeypatch.setattr(source_access.requests, "get", download)
    with http_image_sources(["https://images.example/a.png"]):
        with pytest.raises(ImageSourceError):
            get_image_reference("https://images.example/a.png")
    download.assert_not_called()


def test_direct_python_calls_keep_local_and_existing_http_behavior(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    output = BytesIO()
    Image.new("RGB", (2, 3), "red").save(output, format="PNG")
    image = output.getvalue()
    local = tmp_path / "local.png"
    local.write_bytes(image)
    resolver = Mock(
        side_effect=AssertionError("Direct tools do not resolve through the guard")
    )
    download = Mock(
        return_value=SimpleNamespace(content=image, raise_for_status=Mock())
    )
    monkeypatch.setattr(source_access.socket, "getaddrinfo", resolver)
    monkeypatch.setattr(source_access.requests, "get", download)
    assert gemini._image_part(str(local)).inline_data.data == image
    assert gemini._image_part("http://127.0.0.1/image.png").inline_data.data == image
    download.assert_called_once_with("http://127.0.0.1/image.png", timeout=175)
    resolver.assert_not_called()
    with http_image_sources():
        with pytest.raises(ImageSourceError):
            gemini._image_part(str(local))
