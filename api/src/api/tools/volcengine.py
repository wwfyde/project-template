import hashlib
import hmac
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Literal
from urllib.parse import urlencode

import httpx2
from pydantic import BaseModel, Field, model_validator

VISUAL_BASE_URL = "https://visual.volcengineapi.com"
DEFAULT_QUERY_PARAMS = "Action=CVProcess&Version=2022-08-31"


class Params(BaseModel):
    access_key: str
    secret_key: str
    body: dict
    method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
    base_url: str = VISUAL_BASE_URL
    query_params: dict | str = DEFAULT_QUERY_PARAMS
    region: str = "cn-north-1"
    service: str = "cv"
    algorithm: str = "HMAC-SHA256"


class SeedreamVisionServiceIdentity(Enum):
    Portrait = "i2i_portrait_photo"
    General = "high_aes_general_v30l_zt2i"
    ImageEdit = "seededit_v3.0"


class JimengBody(BaseModel):
    pass


class Txt2ImgRequest(BaseModel):
    """
    文档说明: https://www.volcengine.com/docs/85128/1526761#4e552e07
    接口日期: 2025-06-10
    """

    req_key: str = Field(
        SeedreamVisionServiceIdentity.General.value,
        title="算法名称",
        description="算法名称，取固定值为high_aes_general_v30l_zt2i",
        examples=["high_aes_general_v30l_zt2i"],
    )
    prompt: str = Field(
        ...,
        title="提示词",
        description="用于生成图像的提示词 ，中英文均可输入",
    )
    use_pre_llm: bool | None = Field(
        False,
        title="是否开启文本扩写",
        description=(
            "开启文本扩写，会针对输入prompt进行扩写优化，如果输入prompt较短建议开启，"
            "如果输入prompt较长建议关闭, 默认值：false"
        ),
    )
    seed: int | None = Field(-1, title="随机种子")
    scale: float | None = Field(2.5, le=10, ge=1, title="影响文本描述的程度")
    width: int | None = Field(default=1328, ge=512, le=2048)
    height: int | None = Field(default=1328, ge=512, le=2048)
    return_url: bool | None = Field(
        True,
        title="是否返回图片链接",
        description="输出是否返回图片链接 （链接有效期为24小时）",
    )
    logo_info: dict | None = Field(None, title="水印信息")


class ImgPortraitRequest(BaseModel):
    """
    文档说明: https://www.volcengine.com/docs/85128/1602212
    火山引擎::智能视觉服务::智能绘图::图生图
    """

    req_key: str = SeedreamVisionServiceIdentity.Portrait.value
    image_input: str = Field(..., description="图片URL")
    prompt: str | None = Field(None, description="生图提示")
    width: int | None = Field(default=1328, ge=512, le=2048)
    height: int | None = Field(default=1328, ge=512, le=2048)
    gpen: float | None = Field(
        default=0.4,
        ge=0,
        le=1,
        description="高清处理效果，越高人脸清晰度越高，建议使用默认值",
        examples=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1],
    )
    skin: float | None = Field(default=0.3, ge=0, le=1)
    skin_unifi: float | None = Field(default=0, ge=0, le=1)
    gen_mode: Literal["creative", "reference", "reference_char"] | None = Field(
        None,
        description="参考模式；不传时由服务根据是否有 prompt 自动选择",
    )
    seed: int | None = Field(-1, title="随机种子")


class ImageEditRequest(BaseModel):
    """
    文档说明: https://www.volcengine.com/docs/85128/1602254
    火山引擎::智能视觉服务::智能绘图::图生图::指令编辑
    """

    req_key: str = SeedreamVisionServiceIdentity.ImageEdit.value
    image_urls: list[str] | None = Field(None, description="图片 URL，需且仅需输入一张图片")
    binary_data_base64: list[str] | None = Field(None, description="图片文件 Base64，需且仅需输入一张图片")
    prompt: str = Field(..., description="图像编辑指令")
    seed: int | None = Field(-1, title="随机种子")
    scale: float | None = Field(
        0.5,
        ge=0,
        le=1,
        description=(
            "文本描述影响的程度，该值越大代表文本描述影响程度越大，"
            "且输入图片影响程度越小. 默认值：0.5, 取值范围：[0, 1]"
        ),
        examples=[0.5, 0, 1],
    )

    @model_validator(mode="after")
    def validate_single_input_image(self):
        image_count = len(self.image_urls or []) + len(self.binary_data_base64 or [])
        if image_count != 1:
            raise ValueError("SeedEdit 3.0 需且仅需输入一张图片")
        return self


class AsyncResultRequest(BaseModel):
    req_key: str
    task_id: str
    req_json: str | None = None


def sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def get_signature_key(key: str, date: str, region: str, service: str) -> bytes:
    key_bytes = key.encode("utf-8")
    key_date = sign(key_bytes, date)
    key_region = sign(key_date, region)
    key_service = sign(key_region, service)
    key = sign(key_service, "request")
    return key


def get_authorization_string():
    pass


def serialize_body(body: dict) -> str:
    """Serialize the exact request body bytes used by both signing and HTTP."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def get_query_string(query_params: dict | str) -> str:
    if isinstance(query_params, dict):
        return urlencode(sorted(query_params.items()))
    return query_params


def create_volc_header(
    params: Params,
) -> dict:
    """创建Header"""
    signed_headers = "content-type;host;x-content-sha256;x-date"
    content_type = "application/json"
    payload_hash = hashlib.sha256(serialize_body(params.body).encode("utf-8")).hexdigest()
    # current_datetime = datetime.now(timezone.utc).isoformat(timespec="seconds")
    now = datetime.now(UTC)
    current_datetime = now.strftime("%Y%m%dT%H%M%SZ")
    # current_date = now.date().isoformat()
    current_date = now.strftime("%Y%m%d")
    host = httpx2.URL(params.base_url).host
    canonical_headers = (
        f"content-type:{content_type}\nhost:{host}\nx-content-sha256:{payload_hash}\nx-date:{current_datetime}\n"
    )
    credential_scope = f"{current_date}/{params.region}/{params.service}/request"
    canonical_uri = "/"
    # query_string = httpx2.URL(params.base_url, params=params.query_params).query.decode()

    query_string = get_query_string(params.query_params)

    canonical_request = (
        f"{params.method}\n{canonical_uri}\n{query_string}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )
    canonical_request_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = f"{params.algorithm}\n{current_datetime}\n{credential_scope}\n{canonical_request_hash}"
    signing_key = get_signature_key(params.secret_key, current_date, params.region, params.service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization_header = (
        f"{params.algorithm} Credential={params.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "X-Date": current_datetime,
        "Authorization": authorization_header,
        "X-Content-Sha256": payload_hash,
        "Content-Type": content_type,
    }
    return headers


class VisionTools:
    pass
