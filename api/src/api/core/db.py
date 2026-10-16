import logging
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.core import  settings
logger = logging.getLogger(__name__)
engine = create_async_engine(
    settings.postgres_dsn,
    connect_args={},
    pool_size=settings.postgres.pool_size or 30,  # 连接池的大小
    max_overflow=60,  # 连接池中允许的最大溢出连接数量
    pool_recycle=3600,  # 在指定秒数后回收连接
    pool_pre_ping=True,  # 启用 pre_ping 参数
    # echo=True,
    # json_serializer=dumps,
)

# async_session = async_sessionmaker(
#     async_engine,
#     autoflush=True,
#     expire_on_commit=False)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    # autoflush=False,
    # autocommit=False,
    expire_on_commit=False,
)
logger.debug("Postgres engine created")
