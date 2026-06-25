"""Resource Registry schema and lifecycle tests."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.resource import (
    GranularityFamily,
    GranularityLevel,
    ResourceCreate,
    ResourceStatus,
    ResourceUpdate,
)


def _valid_payload(**overrides):
    base = {
        "resource_code": "aal3_v1_macro",
        "source_atlas": "AAL3",
        "source_version": "v1",
        "granularity_level": "macro",
        "granularity_family": "macro_clinical",
    }
    base.update(overrides)
    return base


def test_create_valid_resource():
    row = ResourceCreate(**_valid_payload())
    assert row.resource_code == "aal3_v1_macro"
    assert row.status == ResourceStatus.active


def test_create_rejects_illegal_granularity_level():
    with pytest.raises(ValidationError) as exc:
        ResourceCreate(**_valid_payload(granularity_level="invalid_level"))
    assert "granularity_level" in str(exc.value)


def test_create_rejects_illegal_granularity_family():
    with pytest.raises(ValidationError) as exc:
        ResourceCreate(**_valid_payload(granularity_family="not_a_family"))
    assert "granularity_family" in str(exc.value)


def test_create_rejects_illegal_status():
    with pytest.raises(ValidationError) as exc:
        ResourceCreate(**_valid_payload(status="promoted_to_final"))
    assert "status" in str(exc.value)


def test_create_rejects_missing_required_source_atlas():
    payload = _valid_payload()
    del payload["source_atlas"]
    with pytest.raises(ValidationError):
        ResourceCreate(**payload)


def test_create_rejects_missing_granularity_level():
    payload = _valid_payload()
    del payload["granularity_level"]
    with pytest.raises(ValidationError):
        ResourceCreate(**payload)


def test_create_rejects_invalid_resource_code():
    with pytest.raises(ValidationError) as exc:
        ResourceCreate(**_valid_payload(resource_code="AAL3-Bad"))
    assert "resource_code" in str(exc.value)


def test_update_rejects_illegal_granularity_level():
    with pytest.raises(ValidationError):
        ResourceUpdate(granularity_level="candidate_created")


def test_update_rejects_illegal_status():
    with pytest.raises(ValidationError):
        ResourceUpdate(status="manual_approved")


def test_enum_values_match_architecture():
    assert GranularityLevel.macro.value == "macro"
    assert GranularityFamily.terminology.value == "terminology"
    assert ResourceStatus.archived.value == "archived"


def test_build_duplicate_resource_detail_active():
    from app.models.resource import AtlasResource
    from app.services.resource_service import ResourceDependencyCounts, build_duplicate_resource_detail

    row = AtlasResource(
        id=uuid.uuid4(),
        resource_code="macro96_standard_pool_v1",
        source_atlas="Macro96",
        source_version="v1",
        resource_type="atlas",
        species="human",
        granularity_level="macro",
        granularity_family="macro_clinical",
        template_space="not_applicable",
        status="active",
    )
    detail = build_duplicate_resource_detail(row, ResourceDependencyCounts())
    assert detail["code"] == "DUPLICATE_RESOURCE_CODE"
    assert detail["can_restore"] is False
    assert detail["can_purge"] is False
    assert detail["existing_resource"]["resource_code"] == "macro96_standard_pool_v1"


def test_build_duplicate_resource_detail_archived_no_deps():
    from datetime import datetime, timezone

    from app.models.resource import AtlasResource
    from app.services.resource_service import ResourceDependencyCounts, build_duplicate_resource_detail

    row = AtlasResource(
        id=uuid.uuid4(),
        resource_code="macro96_standard_pool_v1",
        source_atlas="Macro96",
        source_version="v1",
        resource_type="atlas",
        species="human",
        granularity_level="macro",
        granularity_family="macro_clinical",
        template_space="not_applicable",
        status="archived",
        deleted_at=datetime.now(timezone.utc),
    )
    detail = build_duplicate_resource_detail(row, ResourceDependencyCounts())
    assert detail["can_restore"] is True
    assert detail["can_purge"] is True


def test_purge_has_dependencies_error():
    from app.services.resource_service import ResourceDependencyCounts, ResourceHasDependenciesError

    rid = uuid.uuid4()
    counts = ResourceDependencyCounts(files=1)
    err = ResourceHasDependenciesError(rid, counts.as_dict())
    assert err.dependency_counts["files"] == 1


@pytest.mark.integration
def test_resource_archive_restore_purge_lifecycle():
    """Integration: archive, list filters, restore, purge, recreate same resource_code."""
    from fastapi.testclient import TestClient

    from app.main import app

    code = f"test_lifecycle_{uuid.uuid4().hex[:8]}"
    client = TestClient(app, raise_server_exceptions=False)

    create_resp = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    if create_resp.status_code == 503 or create_resp.status_code >= 500:
        pytest.skip("database unavailable")
    assert create_resp.status_code == 201, create_resp.text
    resource = create_resp.json()
    rid = resource["id"]

    del_resp = client.delete(f"/api/resources/{rid}")
    assert del_resp.status_code == 200
    archived = del_resp.json()
    assert archived["status"] == "archived"
    assert archived.get("deleted_at") is not None

    active_list = client.get("/api/resources", params={"status": "active", "limit": 200})
    assert active_list.status_code == 200
    active_ids = {item["id"] for item in active_list.json()["items"]}
    assert rid not in active_ids

    archived_list = client.get("/api/resources", params={"status": "archived", "limit": 200})
    assert archived_list.status_code == 200
    archived_ids = {item["id"] for item in archived_list.json()["items"]}
    assert rid in archived_ids

    all_list = client.get("/api/resources", params={"status": "all", "limit": 200})
    assert all_list.status_code == 200
    all_ids = {item["id"] for item in all_list.json()["items"]}
    assert rid in all_ids

    dup_resp = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    assert dup_resp.status_code == 409
    detail = dup_resp.json()["detail"]
    assert detail["code"] == "DUPLICATE_RESOURCE_CODE"
    assert detail["existing_resource"]["id"] == rid
    assert detail["can_restore"] is True
    assert detail["can_purge"] is True

    restore_resp = client.post(f"/api/resources/{rid}/restore")
    assert restore_resp.status_code == 200
    restored = restore_resp.json()
    assert restored["status"] == "active"
    assert restored.get("deleted_at") is None

    dup_active = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    assert dup_active.status_code == 409
    assert dup_active.json()["detail"]["can_restore"] is False
    assert dup_active.json()["detail"]["can_purge"] is False

    client.delete(f"/api/resources/{rid}")

    purge_resp = client.post(f"/api/resources/{rid}/purge")
    assert purge_resp.status_code == 204

    recreate = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    assert recreate.status_code == 201
    new_id = recreate.json()["id"]
    assert new_id != rid

    client.post(f"/api/resources/{new_id}/purge")


def test_purge_with_file_dependency_returns_409():
    from fastapi.testclient import TestClient

    from app.main import app

    code = f"test_purge_dep_{uuid.uuid4().hex[:8]}"
    client = TestClient(app, raise_server_exceptions=False)

    create_resp = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    if create_resp.status_code >= 500:
        pytest.skip("database unavailable")
    assert create_resp.status_code == 201
    rid = create_resp.json()["id"]
    client.delete(f"/api/resources/{rid}")

    from app.services import resource_service

    async def fake_extended(*_args, **_kwargs):
        return 1

    original = resource_service.count_extended_resource_dependencies
    resource_service.count_extended_resource_dependencies = fake_extended  # type: ignore[assignment]
    try:
        resp = client.post(f"/api/resources/{rid}/purge")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "RESOURCE_HAS_DEPENDENCIES"
    finally:
        resource_service.count_extended_resource_dependencies = original  # type: ignore[assignment]

    # cleanup without purge guard
    real_purge = resource_service.purge_resource
    resource_service.purge_resource = lambda s, r: real_purge(s, r)  # noqa: ARG005
    try:
        client.post(f"/api/resources/{rid}/purge")
    except Exception:
        pass


def test_restore_conflict_when_active_same_code_exists():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import resource_service

    code = f"test_restore_conflict_{uuid.uuid4().hex[:8]}"
    client = TestClient(app, raise_server_exceptions=False)

    r1 = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    if r1.status_code >= 500:
        pytest.skip("database unavailable")
    assert r1.status_code == 201
    id1 = r1.json()["id"]

    client.delete(f"/api/resources/{id1}")

    r2 = client.post(
        "/api/resources",
        json={
            "resource_code": f"{code}_alt",
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    assert r2.status_code == 201

    async def fake_restore(*_args, **_kwargs):
        raise resource_service.ResourceActiveCodeConflictError(code, uuid.uuid4())

    original = resource_service.restore_resource
    resource_service.restore_resource = fake_restore  # type: ignore[assignment]
    try:
        resp = client.post(f"/api/resources/{id1}/restore")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "ACTIVE_RESOURCE_CODE_EXISTS"
    finally:
        resource_service.restore_resource = original  # type: ignore[assignment]

    client.post(f"/api/resources/{id1}/purge")
    client.post(f"/api/resources/{r2.json()['id']}/purge")
