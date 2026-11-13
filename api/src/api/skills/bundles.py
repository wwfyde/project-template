"""Validate uploaded bundles without extracting or executing their contents."""

import hashlib
import lzma
import mimetypes
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

import yaml

from api.skills.contracts import SkillFailure, SkillFile

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILES = 500
MAX_REQUEST_BYTES = MAX_TOTAL_BYTES + 1024 * 1024
MAX_PREVIEW_BYTES = 256 * 1024


@dataclass(frozen=True)
class SkillBundle:
    name: str
    description: str
    archive: bytes
    files: list[SkillFile]


def invalid(message: str) -> SkillFailure:
    return SkillFailure("invalid_skill_bundle", message, 400)


def validate_path(path: str) -> str:
    parts = path.split("/")
    if (
        not path
        or len(path.encode("utf-8")) > 1024
        or len(parts) > 32
        or any(part in {"", ".", ".."} for part in parts)
        or any(char in path for char in ("\\", ":"))
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
    ):
        raise invalid("File paths must be safe relative paths within one skill folder.")
    return path


class _ManifestLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
        keys: set[str] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in keys:
                raise yaml.YAMLError("Manifest keys must be unique strings")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def _manifest(content: bytes) -> tuple[str, str]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise invalid("SKILL.md must contain UTF-8 text.") from exc
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text[:65536], re.S)
    if match is None:
        raise invalid("SKILL.md requires YAML front matter within its first 64 KiB.")
    try:
        # Bound YAML work and disallow aliases before constructing any objects.
        depth = 0
        for count, event in enumerate(yaml.parse(match[1]), 1):
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
            if isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            if isinstance(event, yaml.AliasEvent) or depth > 20 or count > 5000:
                raise yaml.YAMLError("Manifest is too complex")
        document = yaml.load(match[1], Loader=_ManifestLoader)
    except yaml.YAMLError as exc:
        raise invalid(
            "SKILL.md front matter must be valid YAML without aliases or duplicate keys."
        ) from exc
    if not isinstance(document, dict):
        raise invalid("SKILL.md front matter must be an object.")
    name, description = document.get("name"), document.get("description")
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 64
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None
    ):
        raise invalid("Skill name must be 1–64 lowercase letters, digits or single hyphens.")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise invalid("Skill description must be nonempty text of at most 1024 characters.")
    for field in ("license", "compatibility", "allowed-tools"):
        if field in document and not isinstance(document[field], str):
            raise invalid(f"Manifest {field} must be text.")
    if len(document.get("compatibility", "")) > 500:
        raise invalid("Manifest compatibility must be at most 500 characters.")
    metadata = document.get("metadata", {})
    if not isinstance(metadata, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()
    ):
        raise invalid("Manifest metadata must map strings to strings.")
    return name, description


def _validate_files(files: list[tuple[str, bytes]]) -> tuple[str, str, list[SkillFile]]:
    if not 1 <= len(files) <= MAX_FILES:
        raise invalid("A skill version must contain 1–500 files.")
    paths: set[str] = set()
    folders: set[str] = set()
    manifests: list[tuple[str, bytes]] = []
    manifest: list[SkillFile] = []
    total = 0
    for path, content in files:
        validate_path(path)
        parts = path.split("/")
        if len(parts) < 2:
            raise invalid("All files must be inside a single top-level folder.")
        if path in paths:
            raise invalid("Duplicate file paths are not allowed.")
        paths.add(path)
        folders.add(parts[0])
        if len(content) > MAX_FILE_BYTES:
            raise invalid("Each uncompressed file must be at most 25 MiB.")
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise invalid("The total uncompressed bundle must be at most 50 MiB.")
        if parts[-1].lower() == "skill.md":
            manifests.append((path, content))
        manifest.append(
            SkillFile(
                path=path,
                size=len(content),
                media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    if len(folders) != 1:
        raise invalid("A bundle must contain a single top-level folder.")
    for path in paths:
        if any(str(parent) in paths for parent in PurePosixPath(path).parents):
            raise invalid("A file cannot also be a directory.")
    if len(manifests) != 1 or len(manifests[0][0].split("/")) != 2:
        raise invalid("Exactly one SKILL.md must exist at the root of the skill folder.")
    name, description = _manifest(manifests[0][1])
    return name, description, sorted(manifest, key=lambda item: item.path)


def _pack(files: list[tuple[str, bytes]], executable: set[str]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(files):
            entry = zipfile.ZipInfo(path)
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | (0o755 if path in executable else 0o644)) << 16
            archive.writestr(entry, content)
    content = output.getvalue()
    if len(content) > MAX_ARCHIVE_BYTES:
        raise invalid("The ZIP bundle must be at most 50 MiB.")
    return content


def bundle_from_files(files: list[tuple[str, bytes]]) -> SkillBundle:
    name, description, manifest = _validate_files(files)
    return SkillBundle(name, description, _pack(files, set()), manifest)


def bundle_from_zip(content: bytes) -> SkillBundle:
    if len(content) > MAX_ARCHIVE_BYTES:
        raise invalid("The ZIP bundle must be at most 50 MiB.")
    files: list[tuple[str, bytes]] = []
    directories: set[str] = set()
    executable: set[str] = set()
    seen: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES * 33:
                raise invalid("The ZIP bundle contains too many entries.")
            for entry in entries:
                # orig_filename preserves embedded NULs that ZipInfo otherwise strips.
                path = validate_path(
                    entry.orig_filename.removesuffix("/") if entry.is_dir() else entry.orig_filename
                )
                mode = stat.S_IFMT(entry.external_attr >> 16)
                # ZipExtFile bounds DEFLATE output, while other decompressors may
                # allocate the full expansion before checking a forged file_size.
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise invalid("Only stored or DEFLATE-compressed ZIP entries are supported.")
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                    raise invalid("Links, special files and encrypted ZIP entries are not allowed.")
                if path in seen:
                    raise invalid("Duplicate ZIP paths are not allowed.")
                seen.add(path)
                if entry.is_dir():
                    directories.add(path)
                    continue
                if mode == stat.S_IFDIR:
                    raise invalid("ZIP file type does not match its path.")
                if (entry.external_attr >> 16) & 0o111:
                    executable.add(path)
                if len(files) >= MAX_FILES or entry.file_size > MAX_FILE_BYTES:
                    raise invalid("A version supports at most 500 files, each at most 25 MiB.")
                total += entry.file_size
                if total > MAX_TOTAL_BYTES:
                    raise invalid("The total uncompressed bundle must be at most 50 MiB.")
                with archive.open(entry) as source:
                    data = source.read(MAX_FILE_BYTES + 1)
                if len(data) != entry.file_size or len(data) > MAX_FILE_BYTES:
                    raise invalid("Invalid uncompressed file size.")
                files.append((path, data))
    except (
        zipfile.BadZipFile,
        NotImplementedError,
        RuntimeError,
        ValueError,
        OSError,
        EOFError,
        lzma.LZMAError,
        zlib.error,
    ) as exc:
        raise invalid("The uploaded file must be a valid, supported ZIP bundle.") from exc
    name, description, manifest = _validate_files(files)
    file_paths = {item.path for item in manifest}
    root = manifest[0].path.split("/")[0]
    if any(path.split("/")[0] != root for path in directories) or any(
        path in file_paths
        or any(str(parent) in file_paths for parent in PurePosixPath(path).parents)
        for path in directories
    ):
        raise invalid(
            "ZIP directories must belong to the skill folder and not conflict with files."
        )
    # Canonicalize the accepted bytes: ZIP headers can understate the true
    # expansion and CRC of a member. Never serve an unvalidated compressed tail.
    return SkillBundle(name, description, _pack(files, executable), manifest)
