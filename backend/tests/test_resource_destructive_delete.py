"""Tests for destructive cascade resource delete."""

from __future__ import annotations

import uuid

import pytest

from app.schemas.resource_delete import ResourceDeleteRequest
from app.services import resource_delete_service


def test_validate_confirmation_mismatch():
    from app.models.resource import AtlasResource

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
    )
    with pytest.raises(resource_delete_service.ResourceDeleteConfirmationError):
        resource_delete_service._validate_request(
            row,
            ResourceDeleteRequest(
                confirmation_text="DELETE wrong_code",
                operator="admin",
                reason="test",
            ),
        )


def test_delete_preview_api():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    code = f"test_preview_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    if create.status_code >= 500:
        pytest.skip("database unavailable")
    assert create.status_code == 201
    rid = create.json()["id"]

    preview = client.get(f"/api/resources/{rid}/delete-preview")
    assert preview.status_code == 200
    body = preview.json()
    assert body["resource_code"] == code
    assert body["delete_mode"] == "destructive_cascade"
    assert body["required_confirmation"] == f"DELETE {code}"
    assert "dependency_counts" in body

    client.post(
        f"/api/resources/{rid}/destructive-delete",
        json={
            "confirmation_text": f"DELETE {code}",
            "operator": "tester",
            "reason": "cleanup preview test",
        },
    )


def test_destructive_delete_wrong_confirmation():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    code = f"test_bad_confirm_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    if create.status_code >= 500:
        pytest.skip("database unavailable")
    assert create.status_code == 201
    rid = create.json()["id"]

    resp = client.post(
        f"/api/resources/{rid}/destructive-delete",
        json={
            "confirmation_text": "DELETE wrong",
            "operator": "admin",
            "reason": "test",
        },
    )
    assert resp.status_code == 400

    ok = client.post(
        f"/api/resources/{rid}/destructive-delete",
        json={
            "confirmation_text": f"DELETE {code}",
            "operator": "admin",
            "reason": "test cleanup",
        },
    )
    assert ok.status_code == 200
    assert ok.json()["resource_code_released"] is True


def test_destructive_delete_recreate_same_code():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    code = f"test_recreate_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "TestAtlas",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    if create.status_code >= 500:
        pytest.skip("database unavailable")
    assert create.status_code == 201
    rid = create.json()["id"]

    del_resp = client.post(
        f"/api/resources/{rid}/destructive-delete",
        json={
            "confirmation_text": f"DELETE {code}",
            "operator": "admin",
            "reason": "recreate test",
        },
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted_counts"]["atlas_resources"] == 1
    assert client.get(f"/api/resources/{rid}?include_archived=true").status_code == 404

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

    client.post(
        f"/api/resources/{new_id}/destructive-delete",
        json={
            "confirmation_text": f"DELETE {code}",
            "operator": "admin",
            "reason": "cleanup",
        },
    )


def test_destructive_delete_archived_resource_with_duplicate_code():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    code = f"test_archived_dup_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "Macro96",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    if create.status_code >= 500:
        pytest.skip("database unavailable")
    rid = create.json()["id"]
    client.delete(f"/api/resources/{rid}")

    dup = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "Macro96",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    assert dup.status_code == 409

    del_resp = client.post(
        f"/api/resources/{rid}/destructive-delete",
        json={
            "confirmation_text": f"DELETE {code}",
            "operator": "admin",
            "reason": "release code",
        },
    )
    assert del_resp.status_code == 200

    recreate = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "Macro96",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    assert recreate.status_code == 201
    client.post(
        f"/api/resources/{recreate.json()['id']}/destructive-delete",
        json={
            "confirmation_text": f"DELETE {code}",
            "operator": "admin",
            "reason": "cleanup",
        },
    )


def test_destructive_delete_empty_operator():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    code = f"test_no_op_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/resources",
        json={
            "resource_code": code,
            "source_atlas": "T",
            "source_version": "v1",
            "granularity_level": "macro",
            "granularity_family": "macro_clinical",
        },
    )
    if create.status_code >= 500:
        pytest.skip("database unavailable")
    rid = create.json()["id"]
    resp = client.post(
        f"/api/resources/{rid}/destructive-delete",
        json={
            "confirmation_text": f"DELETE {code}",
            "operator": "",
            "reason": "x",
        },
    )
    assert resp.status_code == 422

    client.post(
        f"/api/resources/{rid}/destructive-delete",
        json={
            "confirmation_text": f"DELETE {code}",
            "operator": "admin",
            "reason": "cleanup",
        },
    )
