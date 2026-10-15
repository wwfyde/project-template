import uuid
from datetime import datetime, timezone

import uuid_utils.compat
from sqlalchemy import UUID, DateTime, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Image(Base):
    __tablename__ = "image"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid_utils.compat.uuid7,
        server_default=text("uuidv7()"),
        comment="ID",
    )
    url: Mapped[str] = mapped_column(Text, nullable=False, comment="URL")
    filename: Mapped[str] = mapped_column(Text, nullable=False, comment="文件名")
    width: Mapped[int] = mapped_column(Integer, nullable=False, comment="宽度")
    height: Mapped[int] = mapped_column(Integer, nullable=False, comment="高度")
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原始文件名")
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="文件大小")
    mime_type: Mapped[str] = mapped_column(Text, nullable=False, comment="MIME类型")
    extension: Mapped[str | None] = mapped_column(Text, nullable=True, comment="文件扩展名")
    extra: Mapped[dict | None] = mapped_column(JSONB, server_default="{}", comment="扩展属性")
    storage_key: Mapped[str] = mapped_column(Text, unique=True, nullable=True, comment="")
    bucket_name: Mapped[str] = mapped_column(Text, server_default="dms-upload", comment="Bucket名称")
    sha256: Mapped[str | None] = mapped_column(Text, index=True, unique=True, comment="文件hash(SHA256)")

    user_id: Mapped[str | None] = mapped_column(Text, comment="上传者ID")

    # 时间日期
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), comment="创建日期")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), comment="更新日期"
    )
