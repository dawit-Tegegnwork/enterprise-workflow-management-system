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
