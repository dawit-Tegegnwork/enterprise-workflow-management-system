import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ["WORKFLOW_DATABASE_URL"] = f"sqlite:///{uuid4().hex}.db"

from app.main import app  # noqa: E402
from app.models import init_db, seed_users, engine  # noqa: E402
from sqlmodel import Session  # noqa: E402

with Session(engine) as _session:
    init_db()
    seed_users(_session)

client = TestClient(app)


def _login(email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "Demo123!"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_workflow_transition_submit_to_approve() -> None:
    staff_token = _login("staff@demo.local")
    manager_token = _login("manager@demo.local")

    create = client.post(
        "/api/v1/requests",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"title": "Laptop request", "description": "Synthetic equipment request", "department": "Operations"},
    )
    assert create.status_code == 200
    request_id = create.json()["id"]

    submit = client.post(
        f"/api/v1/requests/{request_id}/transition",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"action": "submit", "note": "Ready for review"},
    )
    assert submit.status_code == 200
    assert submit.json()["status"] == "submitted"

    approve = client.post(
        f"/api/v1/requests/{request_id}/transition",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"action": "approve", "note": "Approved for demo"},
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    summary = client.get("/api/v1/dashboard/summary", headers={"Authorization": f"Bearer {manager_token}"})
    assert summary.status_code == 200
    assert summary.json()["counts_by_status"]["approved"] >= 1


def test_staff_cannot_approve() -> None:
    staff_token = _login("staff@demo.local")
    create = client.post(
        "/api/v1/requests",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"title": "Denied approval", "description": "Synthetic", "department": "Ops"},
    )
    request_id = create.json()["id"]
    client.post(
        f"/api/v1/requests/{request_id}/transition",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"action": "submit"},
    )
    denied = client.post(
        f"/api/v1/requests/{request_id}/transition",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"action": "approve"},
    )
    assert denied.status_code == 403


def _create_submitted_request(staff_token: str) -> str:
    create = client.post(
        "/api/v1/requests",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"title": "Workflow item", "description": "Synthetic", "department": "Ops"},
    )
    request_id = create.json()["id"]
    client.post(
        f"/api/v1/requests/{request_id}/transition",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"action": "submit"},
    )
    return request_id


def test_manager_can_reject_request() -> None:
    staff_token = _login("staff@demo.local")
    manager_token = _login("manager@demo.local")
    request_id = _create_submitted_request(staff_token)

    reject = client.post(
        f"/api/v1/requests/{request_id}/transition",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"action": "reject", "note": "Not approved for demo"},
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"


def test_csv_export_for_auditor() -> None:
    auditor_token = _login("auditor@demo.local")
    response = client.get(
        "/api/v1/requests/export.csv",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    body = response.text
    assert "id,title,department,status,created_at" in body


def test_audit_log_for_admin() -> None:
    admin_token = _login("admin@demo.local")
    response = client.get(
        "/api/v1/audit",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    events = response.json()
    assert isinstance(events, list)


def test_staff_cannot_export_csv() -> None:
    staff_token = _login("staff@demo.local")
    response = client.get(
        "/api/v1/requests/export.csv",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert response.status_code == 403


def test_auditor_cannot_approve() -> None:
    staff_token = _login("staff@demo.local")
    auditor_token = _login("auditor@demo.local")
    request_id = _create_submitted_request(staff_token)

    denied = client.post(
        f"/api/v1/requests/{request_id}/transition",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={"action": "approve"},
    )
    assert denied.status_code == 403


def test_list_requests_returns_seeded_demo() -> None:
    manager_token = _login("manager@demo.local")
    response = client.get(
        "/api/v1/requests",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 3
    assert any(item["status"] == "submitted" for item in items)


def test_reject_from_draft_is_rejected() -> None:
    staff_token = _login("staff@demo.local")
    manager_token = _login("manager@demo.local")
    create = client.post(
        "/api/v1/requests",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"title": "Draft only", "description": "Synthetic", "department": "Ops"},
    )
    request_id = create.json()["id"]
    denied = client.post(
        f"/api/v1/requests/{request_id}/transition",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"action": "reject"},
    )
    assert denied.status_code == 400
