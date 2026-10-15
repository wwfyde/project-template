from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import Settings, get_settings
from api.core.db import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as asession:
        yield asession
        # session 关闭 归还给连接池, 而不是真的关闭连接


PostgresDep = Annotated[AsyncSession, Depends(get_db)]


SettingsDep = Annotated[Settings, Depends(get_settings)]
