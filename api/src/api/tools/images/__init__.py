"""Image tools are loaded independently of optional SDKs and provider credentials."""

from importlib import import_module

_EXPORTS = {
    "image_create_with_seedream": "seedream",
    "image_create_with_seedream3": "seedream3",
    "image_create_with_seedream4_5": "seedream4_5",
    "image_create_with_seedream5_lite": "seedream5_lite",
    "image_create_with_seedream5_pro": "seedream5_pro",
    "image_create_with_gemini": "gemini",
    "image_create_with_gemini_flash": "gemini",
    "image_create_with_gemini_flash_2": "gemini",
    "image_create_with_gemini_flash_2_1": "gemini",
    "image_create_with_gpt_image_2": "gpt_evolink",
    "image_create_with_gpt_image_2_5": "gpt_evolink",
    "image_edit_with_qwen": "qwen",
    "image_generate_with_qwen": "qwen",
    "rembg_with_url": "remove_background",
    "magic_generate_with_gemini": "gemini",
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value
