"""Owner-scoped, immutable image storage with mutable comment collections."""

import asyncio

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.images.contracts import ImageAsset, ImageComment, ImageFailure
from api.models.image_asset import ImageAssetRecord, ImageCommentRecord


def _not_found() -> ImageFailure:
    return ImageFailure("image_not_found", "Image resource not found.", 404)


class InMemoryImageStore:
    """Development store; state is private to one process and lost on restart."""

    def __init__(self) -> None:
        self._assets: dict[str, tuple[str, ImageAsset, bytes]] = {}
        self._comments: dict[str, tuple[str, ImageComment]] = {}
        self._lock = asyncio.Lock()

    def _asset(self, owner: str, asset_id: str) -> tuple[str, ImageAsset, bytes]:
        record = self._assets.get(asset_id)
        if record is None or record[0] != owner:
            raise _not_found()
        return record

    async def create_asset(self, owner: str, asset: ImageAsset, content: bytes) -> None:
        async with self._lock:
            if asset.id in self._assets:
                self._asset(owner, asset.id)
                raise ImageFailure("asset_exists", "Image already exists.", 409)
            if asset.parent_id is not None:
                self._asset(owner, asset.parent_id)
            self._assets[asset.id] = (
                owner,
                asset.model_copy(deep=True),
                bytes(content),
            )

    async def get_asset(self, owner: str, asset_id: str) -> ImageAsset:
        async with self._lock:
            return self._asset(owner, asset_id)[1].model_copy(deep=True)

    async def get_content(self, owner: str, asset_id: str) -> bytes:
        async with self._lock:
            return self._asset(owner, asset_id)[2]

    async def list_assets(self, owner: str, limit: int) -> list[ImageAsset]:
        async with self._lock:
            assets = [
                asset
                for saved_owner, asset, _ in self._assets.values()
                if saved_owner == owner and asset.purpose == "image"
            ]
            assets.sort(key=lambda asset: (asset.created_at, asset.id), reverse=True)
            return [asset.model_copy(deep=True) for asset in assets[: max(0, limit)]]

    async def add_comment(self, owner: str, comment: ImageComment) -> None:
        async with self._lock:
            self._asset(owner, comment.asset_id)
            existing = self._comments.get(comment.id)
            if existing is not None:
                if existing[0] != owner or existing[1].asset_id != comment.asset_id:
                    raise _not_found()
                raise ImageFailure("comment_exists", "Comment already exists.", 409)
            self._comments[comment.id] = owner, comment.model_copy(deep=True)

    async def list_comments(self, owner: str, asset_id: str) -> list[ImageComment]:
        async with self._lock:
            self._asset(owner, asset_id)
            comments = [
                comment
                for saved_owner, comment in self._comments.values()
                if saved_owner == owner and comment.asset_id == asset_id
            ]
            comments.sort(key=lambda comment: (comment.created_at, comment.id))
            return [comment.model_copy(deep=True) for comment in comments]

    async def delete_comment(self, owner: str, asset_id: str, comment_id: str) -> None:
        async with self._lock:
            self._asset(owner, asset_id)
            record = self._comments.get(comment_id)
            if record is None or record[0] != owner or record[1].asset_id != asset_id:
                raise _not_found()
            del self._comments[comment_id]


class PostgresImageStore:
    """Transactions persist bytes and metadata without exposing public URLs."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _require_asset(self, db: AsyncSession, owner: str, asset_id: str) -> None:
        result = await db.execute(
            select(ImageAssetRecord.id).where(
                ImageAssetRecord.id == asset_id, ImageAssetRecord.owner == owner
            )
        )
        if result.scalar_one_or_none() is None:
            raise _not_found()

    async def create_asset(self, owner: str, asset: ImageAsset, content: bytes) -> None:
        try:
            async with self.sessions.begin() as db:
                if asset.parent_id is not None:
                    await self._require_asset(db, owner, asset.parent_id)
                db.add(
                    ImageAssetRecord(
                        id=asset.id,
                        owner=owner,
                        purpose=asset.purpose,
                        document=asset.model_dump(mode="json"),
                        content=bytes(content),
                        created_at=asset.created_at,
                    )
                )
        except IntegrityError as exc:
            # A duplicate belonging to another owner is indistinguishable from
            # an absent resource, including races across API worker processes.
            async with self.sessions.begin() as db:
                await self._require_asset(db, owner, asset.id)
            raise ImageFailure("asset_exists", "Image already exists.", 409) from exc

    async def get_asset(self, owner: str, asset_id: str) -> ImageAsset:
        async with self.sessions.begin() as db:
            result = await db.execute(
                select(ImageAssetRecord.document).where(
                    ImageAssetRecord.id == asset_id, ImageAssetRecord.owner == owner
                )
            )
            document = result.scalar_one_or_none()
            if document is None:
                raise _not_found()
            return ImageAsset.model_validate(document)

    async def get_content(self, owner: str, asset_id: str) -> bytes:
        async with self.sessions.begin() as db:
            result = await db.execute(
                select(ImageAssetRecord.content).where(
                    ImageAssetRecord.id == asset_id, ImageAssetRecord.owner == owner
                )
            )
            content = result.scalar_one_or_none()
            if content is None:
                raise _not_found()
            return bytes(content)

    async def list_assets(self, owner: str, limit: int) -> list[ImageAsset]:
        async with self.sessions.begin() as db:
            result = await db.execute(
                select(ImageAssetRecord.document)
                .where(
                    ImageAssetRecord.owner == owner, ImageAssetRecord.purpose == "image"
                )
                .order_by(
                    ImageAssetRecord.created_at.desc(), ImageAssetRecord.id.desc()
                )
                .limit(max(0, limit))
            )
            return [
                ImageAsset.model_validate(document) for document in result.scalars()
            ]

    async def add_comment(self, owner: str, comment: ImageComment) -> None:
        try:
            async with self.sessions.begin() as db:
                await self._require_asset(db, owner, comment.asset_id)
                db.add(
                    ImageCommentRecord(
                        id=comment.id,
                        asset_id=comment.asset_id,
                        owner=owner,
                        document=comment.model_dump(mode="json"),
                        created_at=comment.created_at,
                    )
                )
        except IntegrityError as exc:
            async with self.sessions.begin() as db:
                result = await db.execute(
                    select(ImageCommentRecord.id).where(
                        ImageCommentRecord.id == comment.id,
                        ImageCommentRecord.asset_id == comment.asset_id,
                        ImageCommentRecord.owner == owner,
                    )
                )
                if result.scalar_one_or_none() is None:
                    raise _not_found() from exc
            raise ImageFailure(
                "comment_exists", "Comment already exists.", 409
            ) from exc

    async def list_comments(self, owner: str, asset_id: str) -> list[ImageComment]:
        async with self.sessions.begin() as db:
            await self._require_asset(db, owner, asset_id)
            result = await db.execute(
                select(ImageCommentRecord.document)
                .where(
                    ImageCommentRecord.asset_id == asset_id,
                    ImageCommentRecord.owner == owner,
                )
                .order_by(ImageCommentRecord.created_at, ImageCommentRecord.id)
            )
            return [
                ImageComment.model_validate(document) for document in result.scalars()
            ]

    async def delete_comment(self, owner: str, asset_id: str, comment_id: str) -> None:
        async with self.sessions.begin() as db:
            await self._require_asset(db, owner, asset_id)
            result = await db.execute(
                delete(ImageCommentRecord)
                .where(
                    ImageCommentRecord.id == comment_id,
                    ImageCommentRecord.asset_id == asset_id,
                    ImageCommentRecord.owner == owner,
                )
                .returning(ImageCommentRecord.id)
            )
            if result.scalar_one_or_none() is None:
                raise _not_found()
