"""Skills HTTP lifecycle with real Cookie/CSRF dependencies and SQL metadata."""

from collections.abc import AsyncIterator, Iterator
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import pytest
from api.routes import skills as routes
from api.skills.bundles import MAX_PREVIEW_BYTES
from fastapi.testclient import TestClient
from httpx2 import ASGITransport, AsyncClient
from test_auth_routes import (
    COOKIE_NAME,
    TENANT_ID,
    USER_ID,
    AuthTestEnvironment,
    login,
)
from test_auth_routes import (
    auth_env as auth_env,
)
from test_skill_service import (
    SkillEnvironment,
    sample_bundle,
)
from test_skill_service import (
    skill_env as skill_env,
)

BASE = "/api/skills"
SKILL_FIELDS = {
    "id",
    "object",
    "created_at",
    "name",
    "description",
    "default_version",
    "latest_version",
}
VERSION_FIELDS = {"id", "object", "created_at", "name", "description", "skill_id", "version"}


@pytest.fixture
def skill_client(
    auth_env: AuthTestEnvironment, skill_env: SkillEnvironment
) -> Iterator[TestClient]:
    auth_env.app.include_router(routes.skills_router, prefix="/api")
    auth_env.app.include_router(routes.skills_router, prefix="/v1")
    auth_env.app.state.skill_service = skill_env.service
    with TestClient(auth_env.app, base_url="https://testserver") as client:
        yield client


def _login(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": str(login(client)["csrf_token"])}


def _create(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        BASE,
        headers=headers,
        files={"files": ("skill.zip", sample_bundle().archive, "application/zip")},
    )
    assert response.status_code == 200, response.text
    assert set(response.json()) == SKILL_FIELDS
    assert "no-store" in response.headers["cache-control"]
    return response.json()


def test_complete_skill_version_upload_preview_download_and_delete_lifecycle(
    skill_client: TestClient, skill_env: SkillEnvironment
) -> None:
    headers = _login(skill_client)
    skill = _create(skill_client, headers)
    original_archive = skill_env.objects.data[skill_env.objects.puts[0]]
    path = f"{BASE}/{skill['id']}"
    assert (skill["object"], skill["default_version"], skill["latest_version"]) == (
        "skill",
        "1",
        "1",
    )
    assert skill_client.get(f"/v1/skills/{skill['id']}").json() == skill
    page = skill_client.get(BASE, params={"limit": 1}).json()
    assert page == {
        "object": "list",
        "data": [skill],
        "first_id": skill["id"],
        "last_id": skill["id"],
        "has_more": False,
    }

    new_manifest = (
        b"---\nname: new-version\ndescription: Updated report.\n---\nUpdated instructions.\n"
    )
    new_files = [
        ("files[]", ("report-helper/SKILL.md", new_manifest, "text/markdown")),
        ("files[]", ("report-helper/scripts/run.py", b"print('preview only')", "text/plain")),
    ]
    response = skill_client.post(f"{path}/versions", headers=headers, files=new_files)
    assert response.status_code == 200, response.text
    second = response.json()
    assert set(second) == VERSION_FIELDS and second["version"] == "2"
    assert skill_client.get(path).json()["name"] == "report-helper"
    assert skill_client.get(f"{path}/versions/2").json() == second
    listed = skill_client.get(f"{path}/versions", params={"limit": 1}).json()
    assert listed["last_id"] == second["id"] and listed["has_more"]
    first = skill_client.get(f"{path}/versions", params={"after": second["id"]}).json()["data"][0]
    assert first["version"] == "1"
    assert skill_client.delete(f"{path}/versions/1", headers=headers).status_code == 400

    changed = skill_client.post(path, headers=headers, json={"default_version": "2"})
    assert changed.status_code == 200 and changed.json()["name"] == "new-version"
    assert changed.json()["default_version"] == "2"
    reads_before_tree = len(skill_env.objects.gets)
    tree = skill_client.get(f"{path}/tree").json()
    assert tree["version"] == "2" and tree["file_count"] == 2
    assert tree["nodes"][0]["children"][0]["name"] == "scripts"
    assert len(skill_env.objects.gets) == reads_before_tree
    assert skill_client.get(f"{path}/versions/1/tree").json()["file_count"] == 1
    preview = skill_client.get(f"{path}/files", params={"path": "report-helper/SKILL.md"})
    assert preview.status_code == 200 and preview.json()["content"] == new_manifest.decode()
    assert (
        skill_client.get(
            f"{path}/versions/1/files", params={"path": "report-helper/SKILL.md"}
        ).json()["version"]
        == "1"
    )

    downloaded = skill_client.get(f"{path}/content")
    assert downloaded.headers["content-type"] == "application/zip"
    assert "attachment" in downloaded.headers["content-disposition"]
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    with ZipFile(BytesIO(downloaded.content)) as archive:
        assert archive.read("report-helper/SKILL.md") == new_manifest
    assert skill_client.get(f"{path}/versions/1/content").content == original_archive

    deleted = skill_client.delete(f"{path}/versions/1", headers=headers).json()
    assert deleted == {
        "id": first["id"],
        "object": "skill.version.deleted",
        "deleted": True,
        "version": "1",
    }
    assert skill_client.delete(f"{path}/versions/2", headers=headers).status_code == 200
    assert skill_client.get(path).status_code == 404
    assert skill_client.get(BASE).json()["data"] == []
    assert skill_client.portal is not None
    skill_client.portal.call(skill_env.service.cleanup)
    assert not skill_env.objects.data

    replacement = _create(skill_client, headers)
    response = skill_client.delete(f"{BASE}/{replacement['id']}", headers=headers)
    assert response.json() == {"id": replacement["id"], "object": "skill.deleted", "deleted": True}


def test_authentication_csrf_and_owner_isolation_precede_resource_access(
    skill_client: TestClient, skill_env: SkillEnvironment
) -> None:
    assert skill_client.get(BASE).status_code == 401
    assert skill_client.post(BASE, json={}).status_code == 401
    headers = _login(skill_client)
    assert skill_client.post(BASE, json={}).status_code == 403
    assert skill_client.post(BASE, headers={"X-CSRF-Token": "wrong"}, json={}).status_code == 403
    assert not skill_env.objects.puts
    assert skill_client.portal is not None

    for owner in [f"user:other-account:{USER_ID}", f"user:{TENANT_ID}:other-user"]:
        foreign = skill_client.portal.call(skill_env.service.create, owner, sample_bundle())
        path = f"{BASE}/{foreign.id}"
        gets_before, puts_before = len(skill_env.objects.gets), len(skill_env.objects.puts)
        for suffix in [
            "",
            "/content",
            "/tree",
            "/versions",
            "/versions/1",
            "/versions/1/content",
            "/versions/1/tree",
        ]:
            assert skill_client.get(path + suffix).status_code == 404
        for suffix in ["/files", "/versions/1/files"]:
            assert (
                skill_client.get(
                    path + suffix, params={"path": "report-helper/SKILL.md"}
                ).status_code
                == 404
            )
        assert (
            skill_client.post(path, headers=headers, json={"default_version": "1"}).status_code
            == 404
        )
        assert skill_client.post(f"{path}/versions", headers=headers, json={}).status_code == 404
        assert skill_client.delete(path, headers=headers).status_code == 404
        assert skill_client.delete(f"{path}/versions/1", headers=headers).status_code == 404
        assert (len(skill_env.objects.gets), len(skill_env.objects.puts)) == (
            gets_before,
            puts_before,
        )
    assert skill_client.get(BASE).json()["data"] == []


def test_invalid_fields_and_conflicting_upload_methods_leave_storage_unchanged(
    skill_client: TestClient, skill_env: SkillEnvironment
) -> None:
    headers = _login(skill_client)
    skill = _create(skill_client, headers)
    path = f"{BASE}/{skill['id']}"
    archive = sample_bundle().archive
    zip_part = ("files", ("skill.zip", archive, "application/zip"))
    assert (
        skill_client.post(BASE, headers=headers, json={"files": "/etc/passwd"}).status_code == 415
    )
    for parts in [
        [zip_part, ("files[]", ("helper/SKILL.md", b"manifest"))],
        [zip_part, ("unexpected", (None, "field"))],
        [zip_part, ("default", (None, "true"))],
    ]:
        assert skill_client.post(BASE, headers=headers, files=parts).status_code == 400
    assert (
        skill_client.post(
            f"{path}/versions",
            headers=headers,
            files=[zip_part, ("default", (None, "true")), ("default", (None, "false"))],
        ).status_code
        == 400
    )
    for body in [{"default_version": 1}, {"default_version": "1", "name": "override"}]:
        assert skill_client.post(path, headers=headers, json=body).status_code == 422
    assert skill_client.get(BASE, params={"limit": 101}).status_code == 422
    assert skill_client.get(f"{path}/files", params={"path": "../server-file"}).status_code == 400
    assert len(skill_env.objects.puts) == 1


def test_previews_truncate_utf8_and_return_binary_and_html_as_data(
    skill_client: TestClient, skill_env: SkillEnvironment
) -> None:
    headers = _login(skill_client)
    large = b"a" * (MAX_PREVIEW_BYTES - 1) + "中尾".encode()
    html = b"<script>alert(document.cookie)</script><img src=x onerror=alert(1)>"
    bundle = sample_bundle(
        extra=[
            ("report-helper/large.txt", large),
            ("report-helper/image.bin", bytes([0, 255, 128])),
            ("report-helper/index.html", html),
        ]
    )
    created = skill_client.post(
        BASE, headers=headers, files={"files": ("skill.zip", bundle.archive)}
    )
    path = f"{BASE}/{created.json()['id']}/files"
    response = skill_client.get(path, params={"path": "report-helper/large.txt"})
    assert response.json()["truncated"] is True
    assert response.json()["content"] == "a" * (MAX_PREVIEW_BYTES - 1)
    binary = skill_client.get(path, params={"path": "report-helper/image.bin"}).json()
    assert binary["content"] is None and binary["reason"] == "binary_or_non_utf8"
    response = skill_client.get(path, params={"path": "report-helper/index.html"})
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["content"] == html.decode()
    skill_env.objects.data[skill_env.objects.puts[0]] = b"broken stored zip"
    assert skill_client.get(path, params={"path": "report-helper/index.html"}).status_code == 503


@pytest.mark.asyncio
async def test_chunked_upload_is_bounded_without_content_length(
    skill_client: TestClient,
    auth_env: AuthTestEnvironment,
    skill_env: SkillEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(skill_client)
    monkeypatch.setattr(routes, "MAX_REQUEST_BYTES", 256)

    async def content() -> AsyncIterator[bytes]:
        yield (
            b'--boundary\r\nContent-Disposition: form-data; name="files"; '
            b'filename="skill.zip"\r\n\r\n'
        )
        yield b"x" * 128
        yield b"x" * 128
        yield b"\r\n--boundary--\r\n"

    async with AsyncClient(
        transport=ASGITransport(app=auth_env.app), base_url="https://testserver"
    ) as client:
        response = await client.post(
            BASE,
            content=content(),
            headers={
                **headers,
                "Cookie": f"{COOKIE_NAME}={skill_client.cookies[COOKIE_NAME]}",
                "Content-Type": "multipart/form-data; boundary=boundary",
            },
        )
    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "request_too_large"
    assert not skill_env.objects.puts
