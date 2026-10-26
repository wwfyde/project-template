"""Image provider wire protocols; credentials and transport stay on the server."""

import asyncio
import base64
import binascii
import copy
import importlib.util
import json
import threading
import time
from io import BytesIO
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

import httpx2
from PIL import Image, ImageOps

from api.images.contracts import (
    ImageFailure,
    ImageProvider,
    ProviderId,
    ProviderInfo,
    ProviderInput,
)

if TYPE_CHECKING:
    from volcengine.imagex.v2.imagex_service import ImagexService

    from api.core.config import LLMConfig, Settings


def _invalid_response() -> ImageFailure:
    return ImageFailure(
        "provider_invalid_response",
        "The image provider returned an invalid result",
        502,
    )


def _decode_image(value: object, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > ((maximum + 2) // 3) * 4:
        raise _invalid_response()
    try:
        result = base64.b64decode(value, validate=True)
    except ValueError, binascii.Error:
        raise _invalid_response() from None
    if not result or len(result) > maximum:
        raise _invalid_response()
    return result


def _upstream_status(status: int) -> None:
    if status == 429:
        raise ImageFailure(
            "provider_rate_limited", "The image provider is busy; try again later", 503
        )
    if status < 200 or status >= 300:
        # Never expose response bodies: they may contain credentials, prompts, or image data.
        raise ImageFailure(
            "provider_failed", "The image provider could not complete the edit", 502
        )


def _check_request(info: ProviderInfo, request: ProviderInput) -> None:
    if not info.configured:
        raise ImageFailure(
            "provider_unavailable",
            info.unavailable_reason or "The image provider is not configured",
            503,
        )
    if request.operation not in info.operations:
        raise ImageFailure(
            "unsupported_operation",
            "This provider does not support the requested operation",
            422,
        )
    if request.model not in info.models:
        raise ImageFailure(
            "unsupported_model", "The selected model is not enabled", 422
        )
    if request.operation == "erase" and not request.mask:
        raise ImageFailure("mask_required", "Erase requires a mask", 422)


def _prompt(request: ProviderInput, *, reference_mask: bool = False) -> str:
    if request.operation == "remove_background":
        prompt = "Remove the background and return the isolated foreground with true transparency. Preserve the subject, original composition, colors, and image dimensions."
    else:
        prompt = "Remove the objects in the selected region and reconstruct a natural matching background. Preserve the original composition and dimensions."
        if reference_mask:
            prompt += " The first image is the original. The second image is a selection mask: white pixels identify the region to erase and black pixels must remain unchanged. Do not render the mask in the output."
        else:
            prompt += " Edit only the transparent region of the supplied mask."
    if request.prompt:
        prompt += "\nAdditional instruction: " + request.prompt
    return prompt


def _alpha_mask(content: bytes) -> bytes:
    with Image.open(BytesIO(content)) as source:
        alpha = ImageOps.invert(source.convert("L"))
        mask = Image.new("RGBA", source.size, (0, 0, 0, 255))
        mask.putalpha(alpha)
        output = BytesIO()
        mask.save(output, format="PNG")
        return output.getvalue()


class HTTPImageProvider:
    def __init__(
        self, info: ProviderInfo, config: "LLMConfig | None", settings: "Settings"
    ) -> None:
        self.info = info
        self.config = config
        self.timeout = settings.images.edit_timeout_seconds
        self.maximum = settings.images.max_upload_bytes
        self.proxy = settings.proxy_url

    async def _json(self, url: str, **kwargs: object) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self.timeout):
                async with httpx2.AsyncClient(
                    timeout=self.timeout,
                    proxy=self.proxy,
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    async with client.stream("POST", url, **kwargs) as response:
                        _upstream_status(response.status_code)
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > self.maximum * 2 + 65536:
                                raise _invalid_response()
            result = json.loads(content)
            if not isinstance(result, dict):
                raise _invalid_response()
            return result
        except TimeoutError, httpx2.TimeoutException:
            raise ImageFailure(
                "provider_timeout", "The image provider timed out", 504
            ) from None
        except httpx2.HTTPError:
            raise ImageFailure(
                "provider_failed", "Could not connect to the image provider", 502
            ) from None
        except ValueError, UnicodeError:
            raise _invalid_response() from None

    def _bearer(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.config.api_key.get_secret_value()}


class GPTImageProvider(HTTPImageProvider):
    async def edit(self, request: ProviderInput) -> bytes:
        _check_request(self.info, request)
        files = {"image": ("source.png", request.image, "image/png")}
        if request.mask:
            files["mask"] = ("mask.png", _alpha_mask(request.mask), "image/png")
        data = {
            "model": request.model,
            "prompt": _prompt(request),
            "output_format": "png",
            "n": "1",
            "size": "auto",
        }
        if request.operation == "remove_background":
            data["background"] = "transparent"
        result = await self._json(
            self.config.base_url.rstrip("/") + "/images/edits",
            headers=self._bearer(),
            files=files,
            data=data,
        )
        try:
            return _decode_image(result["data"][0]["b64_json"], self.maximum)
        except KeyError, IndexError, TypeError:
            raise _invalid_response() from None


class GeminiImageProvider(HTTPImageProvider):
    async def edit(self, request: ProviderInput) -> bytes:
        _check_request(self.info, request)
        parts: list[dict[str, Any]] = [{"text": _prompt(request, reference_mask=True)}]
        for content in (request.image, request.mask):
            if content:
                parts.append(
                    {
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": base64.b64encode(content).decode("ascii"),
                        }
                    }
                )
        base = self.config.base_url.rstrip("/")
        if base.endswith("/openai"):
            base = base.removesuffix("/openai")
        if not urlsplit(base).path.rstrip("/"):
            base += "/v1beta"
        result = await self._json(
            base + "/models/" + quote(request.model, safe="") + ":generateContent",
            headers={"x-goog-api-key": self.config.api_key.get_secret_value()},
            json={
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
        )
        try:
            for candidate in result["candidates"]:
                for part in candidate["content"]["parts"]:
                    inline = part.get("inlineData")
                    if inline and not part.get("thought", False):
                        if inline.get("mimeType") not in {
                            "image/png",
                            "image/jpeg",
                            "image/webp",
                        }:
                            raise _invalid_response()
                        return _decode_image(inline["data"], self.maximum)
        except KeyError, IndexError, TypeError, AttributeError:
            raise _invalid_response() from None
        raise _invalid_response()


class SeedreamImageProvider(HTTPImageProvider):
    async def edit(self, request: ProviderInput) -> bytes:
        _check_request(self.info, request)
        images = [
            "data:image/png;base64," + base64.b64encode(content).decode("ascii")
            for content in (request.image, request.mask)
            if content
        ]
        result = await self._json(
            self.config.base_url.rstrip("/") + "/images/generations",
            headers=self._bearer(),
            json={
                "model": request.model,
                "prompt": _prompt(request, reference_mask=True),
                "image": images,
                "size": "2K",
                "response_format": "b64_json",
                "watermark": True,
            },
        )
        try:
            return _decode_image(result["data"][0]["b64_json"], self.maximum)
        except KeyError, IndexError, TypeError:
            raise _invalid_response() from None


class _BoundedSDKSession:
    """Use the official SDK's signing/upload logic with bounded HTTP responses."""

    def __init__(
        self, client: httpx2.Client, deadline: float, cancelled: threading.Event
    ) -> None:
        self.client, self.deadline, self.cancelled = client, deadline, cancelled

    def _request(self, method: str, url: str, **kwargs: object) -> httpx2.Response:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self.cancelled.is_set():
            raise TimeoutError()
        kwargs.pop(
            "timeout", None
        )  # The SDK supplies a requests-specific timeout tuple.
        if isinstance(kwargs.get("data"), (str, bytes)):
            kwargs["content"] = kwargs.pop("data")
        with self.client.stream(method, url, timeout=remaining, **kwargs) as response:
            _upstream_status(response.status_code)
            content = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() >= self.deadline or self.cancelled.is_set():
                    raise TimeoutError()
                content.extend(chunk)
                if len(content) > 1024 * 1024:
                    raise _invalid_response()
            headers = {
                key: value
                for key, value in response.headers.items()
                if key not in {"content-encoding", "content-length"}
            }
            return httpx2.Response(
                response.status_code, headers=headers, content=bytes(content)
            )

    def get(self, url: str, **kwargs: object) -> httpx2.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> httpx2.Response:
        return self._request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: object) -> httpx2.Response:
        return self._request("PUT", url, **kwargs)


def _veimagex_sdk(region: str) -> "ImagexService":
    from volcengine.imagex.v2.imagex_service import ImagexService

    class IsolatedImagexService(ImagexService):
        def init(self) -> None:
            # This service exclusively uses configured credentials, never ~/.volc files.
            pass

    sdk = IsolatedImagexService(region=region)
    # The SDK constructor directly references its base class's module-level map.
    # Copy before setting credentials so concurrent requests never share secrets.
    sdk.service_info = copy.deepcopy(sdk.service_info)
    return sdk


class VeImageXProvider:
    def __init__(self, info: ProviderInfo, settings: "Settings") -> None:
        self.info = info
        self.config = settings.images.veimagex
        self.timeout = settings.images.edit_timeout_seconds
        self.maximum = settings.images.max_upload_bytes
        self.proxy = settings.proxy_url

    async def edit(self, request: ProviderInput) -> bytes:
        _check_request(self.info, request)
        if len(request.image) > 10 * 1024 * 1024:
            raise ImageFailure(
                "provider_input_limit", "veImageX accepts images up to 10 MB", 422
            )
        with Image.open(BytesIO(request.image)) as source:
            if min(source.size) > 4320 or max(source.size) > 7680:
                raise ImageFailure(
                    "provider_input_limit",
                    "veImageX accepts a short edge up to 4320 and long edge up to 7680 pixels",
                    422,
                )
        cancelled = threading.Event()
        try:
            return await asyncio.to_thread(self._edit_sync, request, cancelled)
        except ImageFailure:
            raise
        except TimeoutError, httpx2.TimeoutException:
            raise ImageFailure(
                "provider_timeout", "The image provider timed out", 504
            ) from None
        except Exception:
            # The upstream SDK includes request/response details in its exceptions.
            raise ImageFailure(
                "provider_failed", "veImageX could not complete the edit", 502
            ) from None
        finally:
            # A cancelled synchronous HTTP call can finish, but must not begin another stage.
            cancelled.set()

    def _edit_sync(self, request: ProviderInput, cancelled: threading.Event) -> bytes:
        deadline = time.monotonic() + self.timeout
        sdk = _veimagex_sdk(self.config.region)
        sdk.session.close()
        sdk.set_ak(self.config.access_key.get_secret_value())
        sdk.set_sk(self.config.secret_key.get_secret_value())
        with httpx2.Client(
            timeout=self.timeout,
            proxy=self.proxy,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            sdk.session = _BoundedSDKSession(client, deadline, cancelled)
            uploaded = sdk.upload_image_data(
                {"ServiceId": self.config.service_id, "ContentTypes": ["image/png"]},
                [request.image],
            )
            try:
                entry = uploaded["Results"][0]
                if entry["UriStatus"] != 2000:
                    raise _invalid_response()
                uri = entry["Uri"]
                segmented = sdk.get_segment_image(
                    {"ServiceId": self.config.service_id},
                    {
                        "StoreUri": uri,
                        "Class": request.model,
                        "Refine": True,
                        "TransBg": False,
                        "OutFormat": "png",
                    },
                )
                result_uri = segmented["Result"]["ResUri"]
                resource = sdk.get_resource_url(
                    {
                        "ServiceId": self.config.service_id,
                        "Domain": self.config.domain,
                        "URI": result_uri,
                        "Tpl": self.config.template,
                        "Proto": "https",
                    }
                )
                url = resource["Result"]["URL"]
                parsed = urlsplit(url)
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != self.config.domain
                    or parsed.port not in {None, 443}
                    or parsed.username
                    or parsed.password
                ):
                    raise _invalid_response()
                remaining = deadline - time.monotonic()
                if remaining <= 0 or cancelled.is_set():
                    raise TimeoutError()
                with client.stream("GET", url, timeout=remaining) as response:
                    _upstream_status(response.status_code)
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline or cancelled.is_set():
                            raise TimeoutError()
                        content.extend(chunk)
                        if len(content) > self.maximum:
                            raise _invalid_response()
                    if not content:
                        raise _invalid_response()
                    return bytes(content)
            except KeyError, IndexError, TypeError, ValueError:
                raise _invalid_response() from None


class LocalImageProvider:
    info = ProviderInfo(
        id="local", label="Local", configured=True, operations=["markup", "resize"]
    )

    async def edit(self, request: ProviderInput) -> bytes:
        raise ImageFailure(
            "unsupported_operation", "This operation requires an AI image provider", 422
        )


def build_providers(settings: "Settings") -> dict[ProviderId, ImageProvider]:
    providers: dict[ProviderId, ImageProvider] = {"local": LocalImageProvider()}
    entries = [
        (
            "gpt",
            "GPT Image",
            "openai",
            GPTImageProvider,
            ["remove_background", "erase"],
            "native",
        ),
        ("gemini", "Gemini", "google", GeminiImageProvider, ["erase"], "reference"),
        (
            "seedream",
            "Seedream",
            "volcengine",
            SeedreamImageProvider,
            ["erase"],
            "reference",
        ),
    ]
    for (
        provider_id,
        label,
        setting_name,
        provider_type,
        operations,
        mask_mode,
    ) in entries:
        config = getattr(settings.providers, setting_name)
        models = list(getattr(settings.images, provider_id + "_models"))
        preferred = getattr(config, "image_model", None)
        if preferred and preferred not in models:
            models.append(preferred)
        configured = bool(
            config and config.base_url and config.api_key.get_secret_value()
        )
        reason = None if configured else "Provider credentials are not configured"
        if provider_id == "gemini" and getattr(config, "use_vertexai", False):
            configured, reason = (
                False,
                "This adapter requires a Gemini Developer API key; Vertex AI is not enabled",
            )
        info = ProviderInfo(
            id=provider_id,
            label=label,
            configured=configured,
            models=models,
            default_model=preferred or models[0],
            operations=operations,
            mask_mode=mask_mode,
            unavailable_reason=reason,
        )
        providers[provider_id] = provider_type(info, config, settings)
    config = settings.images.veimagex
    configured = bool(
        config.access_key
        and config.secret_key
        and config.access_key.get_secret_value()
        and config.secret_key.get_secret_value()
        and config.service_id
        and config.domain
        and config.template
    )
    reason = (
        None
        if configured
        else "veImageX requires AK/SK, service ID, domain, and an original-image template"
    )
    if importlib.util.find_spec("volcengine") is None:
        configured, reason = False, "The official volcengine SDK is not installed"
    info = ProviderInfo(
        id="veimagex",
        label="veImageX",
        configured=configured,
        models=["productv2", "humanv2"],
        default_model="productv2",
        operations=["remove_background"],
        unavailable_reason=reason,
    )
    providers["veimagex"] = VeImageXProvider(info, settings)
    return providers
