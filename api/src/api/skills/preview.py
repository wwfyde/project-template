"""Data-only previews; clients must render file content as escaped text."""

import codecs
import hashlib
import lzma
import zipfile
import zlib
from io import BytesIO
from typing import Literal

from pydantic import BaseModel, Field

from api.skills.bundles import MAX_PREVIEW_BYTES, validate_path
from api.skills.contracts import SkillFailure, StoredVersion


class SkillTreeNode(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int | None = None
    media_type: str | None = None
    children: list["SkillTreeNode"] = Field(default_factory=list)


class SkillTree(BaseModel):
    object: Literal["skill.tree"] = "skill.tree"
    skill_id: str
    version: str
    nodes: list[SkillTreeNode]
    file_count: int
    total_bytes: int


class SkillFilePreview(BaseModel):
    object: Literal["skill.file"] = "skill.file"
    skill_id: str
    version: str
    path: str
    size: int
    media_type: str
    encoding: Literal["utf-8"] | None = None
    content: str | None = None
    truncated: bool = False
    reason: str | None = None


def build_tree(stored: StoredVersion) -> SkillTree:
    nodes: dict[str, SkillTreeNode] = {}
    roots: list[SkillTreeNode] = []
    for file in stored.files:
        parts = file.path.split("/")
        siblings = roots
        for index, name in enumerate(parts):
            path = "/".join(parts[: index + 1])
            node = nodes.get(path)
            if node is None:
                is_file = index == len(parts) - 1
                node = SkillTreeNode(
                    name=name,
                    path=path,
                    type="file" if is_file else "directory",
                    size=file.size if is_file else None,
                    media_type=file.media_type if is_file else None,
                )
                nodes[path] = node
                siblings.append(node)
            siblings = node.children

    def sort(items: list[SkillTreeNode]) -> None:
        items.sort(key=lambda node: (node.type != "directory", node.name.casefold(), node.name))
        for node in items:
            sort(node.children)

    sort(roots)
    return SkillTree(
        skill_id=stored.version.skill_id,
        version=stored.version.version,
        nodes=roots,
        file_count=len(stored.files),
        total_bytes=sum(file.size for file in stored.files),
    )


def preview_file(stored: StoredVersion, archive: bytes, path: str) -> SkillFilePreview:
    validate_path(path)
    file = next((file for file in stored.files if file.path == path), None)
    if file is None:
        raise SkillFailure("skill_file_not_found", "Skill file not found.", 404)
    try:
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            with bundle.open(path) as source:
                content = source.read(file.size + 1)
        if len(content) != file.size or hashlib.sha256(content).hexdigest() != file.sha256:
            raise ValueError("File integrity mismatch")
    except (
        zipfile.BadZipFile,
        KeyError,
        RuntimeError,
        ValueError,
        OSError,
        EOFError,
        NotImplementedError,
        lzma.LZMAError,
        zlib.error,
    ) as exc:
        raise SkillFailure(
            "skill_content_unavailable", "Skill content is unavailable.", 503
        ) from exc
    result = SkillFilePreview(
        skill_id=stored.version.skill_id,
        version=stored.version.version,
        path=path,
        size=file.size,
        media_type=file.media_type,
    )
    sample = content[:MAX_PREVIEW_BYTES]
    truncated = len(content) > MAX_PREVIEW_BYTES
    try:
        text = codecs.getincrementaldecoder("utf-8")().decode(sample, final=not truncated)
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            raise ValueError("Binary content")
    except UnicodeDecodeError, ValueError:
        result.reason = "binary_or_non_utf8"
        return result
    result.content, result.encoding, result.truncated = text, "utf-8", truncated
    return result
