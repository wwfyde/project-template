"""Bounded, deterministic raster operations. Coordinates use oriented image space."""

import warnings
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from api.images.config import ImagesConfig
from api.images.contracts import EditRequest, ImageFailure


def encode_png(image: Image.Image, config: ImagesConfig) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    content = output.getvalue()
    if len(content) > config.max_upload_bytes:
        raise ImageFailure(
            "image_too_large", "The normalized PNG exceeds the image byte limit.", 413
        )
    return content


def decode_image(content: bytes, config: ImagesConfig) -> Image.Image:
    if not content or len(content) > config.max_upload_bytes:
        raise ImageFailure(
            "image_too_large", "Image is empty or exceeds the byte limit.", 413
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if (
                    source.format not in {"PNG", "JPEG", "WEBP"}
                    or getattr(source, "n_frames", 1) != 1
                ):
                    raise ImageFailure(
                        "unsupported_image",
                        "Upload a single-frame PNG, JPEG or WebP image.",
                        415,
                    )
                if (
                    source.width * source.height > config.max_pixels
                    or max(source.size) > 8192
                ):
                    raise ImageFailure(
                        "image_too_large",
                        "Image dimensions exceed the pixel limit.",
                        413,
                    )
                source.load()
                return ImageOps.exif_transpose(source).convert("RGBA")
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ImageFailure(
            "image_too_large", "Image dimensions exceed the pixel limit.", 413
        ) from error
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ImageFailure(
            "invalid_image", "Image could not be decoded.", 422
        ) from error


def normalize_image(content: bytes, config: ImagesConfig) -> tuple[bytes, int, int]:
    image = decode_image(content, config)
    return encode_png(image, config), image.width, image.height


def _font(
    size: int, text: str, config: ImagesConfig
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if config.font_path is not None:
        try:
            return ImageFont.truetype(str(config.font_path), size)
        except OSError as error:
            raise ImageFailure(
                "font_unavailable", "The configured markup font is unavailable.", 503
            ) from error
    for path in (
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    if not text.isascii():
        raise ImageFailure(
            "font_required",
            "Configure images.font_path with a font supporting this text.",
            503,
        )
    return ImageFont.load_default(size=size)


def local_edit(
    content: bytes, request: EditRequest, config: ImagesConfig
) -> tuple[bytes, int, int]:
    image = decode_image(content, config)
    if request.operation == "resize":
        assert request.width is not None and request.height is not None
        size = (request.width, request.height)
        if size[0] * size[1] > config.max_pixels:
            raise ImageFailure(
                "image_too_large", "Requested dimensions exceed the pixel limit.", 413
            )
        if request.fit == "stretch":
            image = image.resize(size, Image.Resampling.LANCZOS)
        elif request.fit == "cover":
            image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
        else:
            fitted = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
            canvas = Image.new(
                "RGBA",
                size,
                request.background
                if request.background != "transparent"
                else (0, 0, 0, 0),
            )
            canvas.alpha_composite(
                fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2)
            )
            image = canvas
    elif request.operation == "markup":
        draw = ImageDraw.Draw(image)
        for item in request.markup or []:
            points = [
                (
                    round(point.x * (image.width - 1)),
                    round(point.y * (image.height - 1)),
                )
                for point in item.points
            ]
            if item.kind == "path":
                if len(points) > 1:
                    draw.line(points, fill=item.color, width=item.width, joint="curve")
                radius = item.width / 2
                for x, y in points[:1] + points[-1:]:
                    draw.ellipse(
                        (x - radius, y - radius, x + radius, y + radius),
                        fill=item.color,
                    )
            elif item.kind == "text":
                draw.text(
                    points[0],
                    item.text or "",
                    fill=item.color,
                    font=_font(item.width, item.text or "", config),
                    anchor="lt",
                )
            else:
                (x1, y1), (x2, y2) = points
                bounds = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
                method = draw.rectangle if item.kind == "rectangle" else draw.ellipse
                method(bounds, outline=item.color, width=item.width)
    return encode_png(image, config), image.width, image.height


def validate_mask(content: bytes, size: tuple[int, int], config: ImagesConfig) -> bytes:
    mask = decode_image(content, config)
    if mask.size != size:
        raise ImageFailure(
            "invalid_mask", "Mask dimensions must match the source image.", 422
        )
    if mask.getchannel("A").getextrema()[0] != 255:
        raise ImageFailure(
            "invalid_mask",
            "Use an opaque grayscale mask: white edits, black preserves.",
            422,
        )
    gray = mask.convert("L")
    if gray.getextrema()[1] == 0:
        raise ImageFailure("empty_mask", "Select an area to erase.", 422)
    return encode_png(gray, config)


def finish_provider_edit(
    source: bytes, output: bytes, mask: bytes | None, config: ImagesConfig
) -> tuple[bytes, int, int]:
    original = decode_image(source, config)
    edited = decode_image(output, config)
    if edited.size != original.size:
        edited = edited.resize(original.size, Image.Resampling.LANCZOS)
    if mask is not None:
        selection = decode_image(mask, config).convert("L")
        # Even reference-mask providers cannot change pixels outside the selection.
        edited = Image.composite(edited, original, selection)
    elif (
        edited.getchannel("A").getextrema()[0] == 255
        or edited.getchannel("A").getextrema()[1] == 0
    ):
        raise ImageFailure(
            "invalid_transparency",
            "Provider did not return a usable transparent cutout.",
            502,
        )
    return encode_png(edited, config), edited.width, edited.height
