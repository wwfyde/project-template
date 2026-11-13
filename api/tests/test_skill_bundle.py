"""Skill uploads are inspectable archives, never executable filesystem input."""

import hashlib
import stat
import struct
import warnings
import zipfile
import zlib
from io import BytesIO

import pytest
from api.skills import bundles
from api.skills.bundles import bundle_from_files, bundle_from_zip, validate_path
from api.skills.contracts import SkillFailure

MANIFEST = (
    b"---\nname: report-helper\ndescription: Generate a report.\n---\nRead references/style.md.\n"
)


def _zip(
    files: list[tuple[str | zipfile.ZipInfo, bytes]],
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for name, data in files:
                archive.writestr(name, data)
    return output.getvalue()


def test_directory_upload_preserves_files_metadata_and_bundle_structure() -> None:
    files = [
        ("report-helper/scripts/run.py", b"raise RuntimeError('never execute')\n"),
        ("report-helper/SKILL.md", MANIFEST),
        ("report-helper/references/style.md", "保持简洁。".encode()),
        ("report-helper/assets/sample.bin", bytes([0, 255, 128])),
    ]
    bundle = bundle_from_files(files)

    assert (bundle.name, bundle.description) == ("report-helper", "Generate a report.")
    assert [item.path for item in bundle.files] == sorted(name for name, _ in files)
    for item in bundle.files:
        content = dict(files)[item.path]
        assert item.size == len(content)
        assert item.sha256 == hashlib.sha256(content).hexdigest()
    with zipfile.ZipFile(BytesIO(bundle.archive)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == dict(files)


def test_zip_upload_normalizes_archive_and_accepts_explicit_directories() -> None:
    content = _zip(
        [
            ("report-helper/", b""),
            ("report-helper/references/", b""),
            ("report-helper/SkIlL.mD", MANIFEST),
            ("report-helper/references/style.md", b"Style guide"),
        ]
    )

    bundle = bundle_from_zip(content)

    with zipfile.ZipFile(BytesIO(bundle.archive)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == {
            "report-helper/SkIlL.mD": MANIFEST,
            "report-helper/references/style.md": b"Style guide",
        }
    assert len(bundle.files) == 2
    assert bundle.name == "report-helper"


def test_forged_size_and_crc_cannot_preserve_unvalidated_compressed_tail() -> None:
    hidden = b"hidden payload" * 10000
    original = bytearray(_zip([("helper/SKILL.md", MANIFEST + hidden)]))
    # ZipExtFile trusts the advertised size and can validate the CRC of only a prefix.
    for signature, crc_offset, size_offset in [
        (b"PK\x03\x04", 14, 22),
        (b"PK\x01\x02", 16, 24),
    ]:
        start = original.index(signature)
        struct.pack_into("<I", original, start + crc_offset, zlib.crc32(MANIFEST))
        struct.pack_into("<I", original, start + size_offset, len(MANIFEST))

    def decompress_member(content: bytes) -> bytes:
        name_size, extra_size = struct.unpack_from("<HH", content, 26)
        compressed_size = struct.unpack_from("<I", content, 18)[0]
        start = 30 + name_size + extra_size
        return zlib.decompress(content[start : start + compressed_size], -15)

    assert decompress_member(bytes(original)) == MANIFEST + hidden
    bundle = bundle_from_zip(bytes(original))
    assert bundle.files[0].size == len(MANIFEST)
    assert decompress_member(bundle.archive) == MANIFEST


def test_normalization_retains_executable_files_without_special_permission_bits() -> None:
    executable = zipfile.ZipInfo("helper/scripts/run.sh")
    executable.create_system = 3
    executable.external_attr = (stat.S_IFREG | 0o6755) << 16
    content = _zip([("helper/SKILL.md", MANIFEST), (executable, b"#!/bin/sh\necho test\n")])
    bundle = bundle_from_zip(content)
    with zipfile.ZipFile(BytesIO(bundle.archive)) as archive:
        script_mode = archive.getinfo(executable.filename).external_attr >> 16
        manifest_mode = archive.getinfo("helper/SKILL.md").external_attr >> 16
        assert stat.S_IMODE(script_mode) == 0o755
        assert stat.S_IMODE(manifest_mode) == 0o644
        assert stat.S_ISREG(script_mode)


@pytest.mark.parametrize("compression", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_compression_methods_without_bounded_expansion_are_rejected(compression: int) -> None:
    with pytest.raises(SkillFailure, match="Only stored or DEFLATE"):
        bundle_from_zip(_zip([("helper/SKILL.md", MANIFEST)], compression=compression))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/report-helper/SKILL.md",
        "../report-helper/SKILL.md",
        "report-helper/../outside.txt",
        "report-helper/./SKILL.md",
        "report-helper//SKILL.md",
        "report-helper/SKILL.md/",
        r"report-helper\SKILL.md",
        "C:/report-helper/SKILL.md",
        "report-helper/file:stream",
        "report-helper/\0hidden",
        "report-helper/line\nname",
        "report-helper/\x7fhidden",
        "/".join(["folder"] * 33),
        "report-helper/" + "文" * 342,
    ],
)
def test_unsafe_and_unbounded_paths_are_rejected(path: str) -> None:
    with pytest.raises(SkillFailure) as error:
        validate_path(path)
    assert error.value.status == 400


@pytest.mark.parametrize(
    "files",
    [
        [],
        [("SKILL.md", MANIFEST)],
        [("one/SKILL.md", MANIFEST), ("two/file.txt", b"outside")],
        [("one/references/SKILL.md", MANIFEST)],
        [("one/SKILL.md", MANIFEST), ("one/skill.md", MANIFEST)],
        [("one/SKILL.md", MANIFEST), ("one/nested/skill.md", MANIFEST)],
        [("one/SKILL.md", MANIFEST), ("one/SKILL.md", MANIFEST)],
        [("one/SKILL.md", MANIFEST), ("one/a", b"file"), ("one/a/b", b"child")],
    ],
)
def test_bundle_requires_one_root_manifest_without_conflicting_files(
    files: list[tuple[str, bytes]],
) -> None:
    with pytest.raises(SkillFailure):
        bundle_from_files(files)
    with pytest.raises(SkillFailure):
        bundle_from_zip(_zip(files))


@pytest.mark.parametrize(
    "frontmatter",
    [
        "name: Invalid\ndescription: Test",
        "name: two--hyphens\ndescription: Test",
        "name: -leading\ndescription: Test",
        "name: trailing-\ndescription: Test",
        "name: has_underscore\ndescription: Test",
        "name: 12\ndescription: Test",
        'name: ""\ndescription: Test',
        "name: " + "a" * 65 + "\ndescription: Test",
        "description: Missing name",
        "name: helper",
        "name: helper\ndescription: false",
        "name: helper\ndescription: '   '",
        "name: helper\ndescription: " + "x" * 1025,
        "name: helper\nname: duplicate\ndescription: Test",
        "name: &name helper\ndescription: *name",
        "name: helper\ndescription: Test\nmetadata: [a, b]",
        "name: helper\ndescription: Test\nmetadata:\n  revision: 1",
        "name: helper\ndescription: Test\ncompatibility: [python]",
        "name: helper\ndescription: Test\nlicense: [MIT]",
        "name: helper\ndescription: Test\nallowed-tools: [bash]",
        "name: helper\ndescription: Test\ncompatibility: " + "x" * 501,
        "- one\n- two",
        "name: [unterminated",
        "!!python/object/apply:os.system ['echo should-not-run']",
    ],
)
def test_invalid_or_unsafe_yaml_is_rejected(frontmatter: str) -> None:
    content = f"---\n{frontmatter}\n---\nInstructions\n".encode()
    with pytest.raises(SkillFailure) as error:
        bundle_from_files([("helper/SKILL.md", content)])
    assert error.value.code == "invalid_skill_bundle"


def test_frontmatter_supports_utf8_bom_crlf_and_block_description() -> None:
    content = (
        "\ufeff---\r\nname: report-helper\r\ndescription: >-\r\n"
        "  Summarize reports\r\n  with references.\r\n"
        "metadata:\r\n  owner: team\r\n---\r\nInstructions\r\n"
    ).encode()
    bundle = bundle_from_files([("helper/skill.md", content)])
    assert bundle.description == "Summarize reports with references."


@pytest.mark.parametrize("content", [b"No frontmatter", b"---\nname: helper\n", b"\xff"])
def test_manifest_must_be_utf8_with_complete_frontmatter(content: bytes) -> None:
    with pytest.raises(SkillFailure):
        bundle_from_files([("helper/SKILL.md", content)])


def test_frontmatter_complexity_is_bounded() -> None:
    nested = "[" * 21 + "x" + "]" * 21
    content = b"---\nname: helper\ndescription: Test\nmetadata: " + nested.encode() + b"\n---\n"
    with pytest.raises(SkillFailure):
        bundle_from_files([("helper/SKILL.md", content)])


def test_file_count_limit_includes_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundles, "MAX_FILES", 2)
    files = [("helper/SKILL.md", MANIFEST), ("helper/a", b"a"), ("helper/b", b"b")]
    with pytest.raises(SkillFailure):
        bundle_from_files(files)
    with pytest.raises(SkillFailure):
        bundle_from_zip(_zip(files))


def test_uncompressed_file_and_total_limits_apply_to_both_upload_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bundles, "MAX_FILE_BYTES", 100)
    monkeypatch.setattr(bundles, "MAX_TOTAL_BYTES", 150)
    for files in [
        [("helper/SKILL.md", MANIFEST), ("helper/large", b"x" * 101)],
        [("helper/SKILL.md", MANIFEST), ("helper/a", b"x" * 75), ("helper/b", b"x" * 75)],
    ]:
        with pytest.raises(SkillFailure):
            bundle_from_files(files)
        with pytest.raises(SkillFailure):
            bundle_from_zip(_zip(files))


def test_zip_size_limit_applies_to_original_and_generated_archives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = [("helper/SKILL.md", MANIFEST)]
    archive = _zip(files)
    monkeypatch.setattr(bundles, "MAX_ARCHIVE_BYTES", len(archive) - 1)
    with pytest.raises(SkillFailure):
        bundle_from_zip(archive)
    with pytest.raises(SkillFailure):
        bundle_from_files(files)


@pytest.mark.parametrize("file_type", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK])
def test_zip_special_files_and_links_are_rejected(file_type: int) -> None:
    entry = zipfile.ZipInfo("helper/link")
    entry.create_system = 3
    entry.external_attr = (file_type | 0o777) << 16
    content = _zip([("helper/SKILL.md", MANIFEST), (entry, b"/etc/passwd")])
    with pytest.raises(SkillFailure):
        bundle_from_zip(content)


@pytest.mark.parametrize(
    "extra",
    [
        [("outside/", b"")],
        [("helper/SKILL.md/", b"")],
        [("helper/SKILL.md/child/", b"")],
        [("helper/a/", b""), ("helper/a/", b"")],
        [("helper/../outside/", b"")],
    ],
)
def test_explicit_zip_directories_cannot_escape_duplicate_or_conflict(
    extra: list[tuple[str, bytes]],
) -> None:
    with pytest.raises(SkillFailure):
        bundle_from_zip(_zip([("helper/SKILL.md", MANIFEST), *extra]))


def test_encrypted_zip_entries_are_rejected_before_reading() -> None:
    content = bytearray(_zip([("helper/SKILL.md", MANIFEST)]))
    # Set the encrypted bit in both local and central headers without needing a password.
    for signature, flag_offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
        index = content.index(signature) + flag_offset
        flags = struct.unpack_from("<H", content, index)[0]
        struct.pack_into("<H", content, index, flags | 1)
    with pytest.raises(SkillFailure, match="encrypted"):
        bundle_from_zip(bytes(content))


@pytest.mark.parametrize("content", [b"not a zip", b"PK\x03\x04", _zip([])])
def test_malformed_and_empty_archives_return_validation_errors(content: bytes) -> None:
    with pytest.raises(SkillFailure) as error:
        bundle_from_zip(content)
    assert error.value.status == 400


@pytest.mark.parametrize("compression", [zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_corrupted_compressed_data_is_a_client_error(compression: int) -> None:
    content = bytearray(_zip([("helper/SKILL.md", MANIFEST)], compression=compression))
    name_size, extra_size = struct.unpack_from("<HH", content, 26)
    payload_start = 30 + name_size + extra_size
    content[payload_start : payload_start + 8] = b"\xff" * 8
    with pytest.raises(SkillFailure) as error:
        bundle_from_zip(bytes(content))
    assert error.value.status == 400
