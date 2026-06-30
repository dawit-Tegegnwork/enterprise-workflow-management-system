from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import StringIO
from uuid import UUID

import csv
from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from jose import JWTError, jwt
from sqlmodel import Session, func, select

from app.landing import render_landing
from app.models import (
    AuditLog,
    LoginInput,
    RequestComment,
    RequestCreateInput,
    RequestStatus,
    Role,
    Settings,
    StatusHistory,
    TokenResponse,
    TransitionInput,
    User,
    WorkflowRequest,
    create_token,
    engine,
    init_db,
    seed_demo_requests,
    seed_users,
    settings,
    verify_password,
)


def get_session():
    with Session(engine) as session:
        yield session


def get_current_user(authorization: str = Header(default=""), session: Session = Depends(get_session)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = UUID(payload["sub"])
    except (JWTError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_roles(*roles: Role):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user

    return checker


def audit(session: Session, action: str, actor: User | None, entity_type: str, entity_id: str, metadata: dict | None = None):
    session.add(
        AuditLog(
            action=action,
            actor_id=actor.id if actor else None,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata or {},
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        seed_users(session)
        seed_demo_requests(session)
    yield


app = FastAPI(title="Enterprise Workflow Management System", version="0.1.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def landing_page():
    return render_landing(
        "Enterprise Workflow Management System",
        "Production-style portfolio API — JWT, RBAC, approvals, audit trail, CSV export.",
        "No employer or production workflow data. Demo accounts and requests only.",
        "enterprise-workflow-management-system",
        quick_steps=[
            'Check <a href="/health">/health</a>',
            'Open <a href="/docs">/docs</a> and login as <code>staff@demo.local</code> / <code>Demo123!</code>',
            "<code>GET /api/v1/requests</code> — view seeded workflow requests",
            "Login as <code>manager@demo.local</code> and approve a submitted request",
        ],
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(payload: LoginInput, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=create_token(user), role=user.role, full_name=user.full_name)


@app.post("/api/v1/requests")
def create_request(
    payload: RequestCreateInput,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    req = WorkflowRequest(
        title=payload.title,
        description=payload.description,
        requester_id=user.id,
        department=payload.department,
        status=RequestStatus.DRAFT,
    )
    session.add(req)
    session.commit()
    session.refresh(req)
    audit(session, "request.create", user, "workflow_request", str(req.id), {"title": req.title})
    session.commit()
    return {
        "id": str(req.id),
        "title": req.title,
        "description": req.description,
        "department": req.department,
        "status": req.status.value,
        "requester_id": str(req.requester_id),
    }


@app.post("/api/v1/requests/{request_id}/transition")
def transition_request(
    request_id: UUID,
    payload: TransitionInput,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    req = session.get(WorkflowRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    action = payload.action
    old = req.status
    if action == "submit" and user.role in {Role.STAFF, Role.MANAGER, Role.ADMIN}:
        if req.status != RequestStatus.DRAFT:
            raise HTTPException(status_code=400, detail="Only draft requests can be submitted")
        req.status = RequestStatus.SUBMITTED
    elif action == "approve" and user.role in {Role.MANAGER, Role.ADMIN}:
        if req.status not in {RequestStatus.SUBMITTED, RequestStatus.CHANGES_REQUESTED}:
            raise HTTPException(status_code=400, detail="Invalid transition for approve")
        req.status = RequestStatus.APPROVED
    elif action == "reject" and user.role in {Role.MANAGER, Role.ADMIN}:
        if req.status not in {RequestStatus.SUBMITTED, RequestStatus.CHANGES_REQUESTED}:
            raise HTTPException(status_code=400, detail="Invalid transition for reject")
        req.status = RequestStatus.REJECTED
    elif action == "request_changes" and user.role in {Role.MANAGER, Role.ADMIN}:
        if req.status != RequestStatus.SUBMITTED:
            raise HTTPException(status_code=400, detail="Invalid transition for request_changes")
        req.status = RequestStatus.CHANGES_REQUESTED
    else:
        raise HTTPException(status_code=403, detail="Transition not allowed")

    req.updated_at = datetime.now(UTC)
    session.add(req)
    session.add(
        StatusHistory(
            request_id=req.id,
            from_status=old.value,
            to_status=req.status.value,
            actor_id=user.id,
            note=payload.note,
        )
    )
    if payload.note:
        session.add(RequestComment(request_id=req.id, author_id=user.id, body=payload.note))
    audit(session, f"request.{action}", user, "workflow_request", str(req.id), {"from": old.value, "to": req.status.value})
    session.commit()
    session.refresh(req)
    return {
        "id": str(req.id),
        "status": req.status.value,
        "title": req.title,
    }


def _request_payload(req: WorkflowRequest) -> dict:
    return {
        "id": str(req.id),
        "title": req.title,
        "description": req.description,
        "department": req.department,
        "status": req.status.value,
        "requester_id": str(req.requester_id),
        "created_at": req.created_at.isoformat(),
        "updated_at": req.updated_at.isoformat(),
    }


@app.get("/api/v1/requests")
def list_requests(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    rows = session.exec(select(WorkflowRequest).order_by(WorkflowRequest.created_at.desc())).all()
    return [_request_payload(row) for row in rows]


@app.get("/api/v1/requests/export.csv")
def export_csv(session: Session = Depends(get_session), user: User = Depends(require_roles(Role.MANAGER, Role.ADMIN, Role.AUDITOR))):
    rows = session.exec(select(WorkflowRequest)).all()
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "title", "department", "status", "created_at"])
    for row in rows:
        writer.writerow([str(row.id), row.title, row.department, row.status.value, row.created_at.isoformat()])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=requests.csv"})


@app.get("/api/v1/requests/{request_id}")
def get_request(
    request_id: UUID,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    req = session.get(WorkflowRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return _request_payload(req)


@app.get("/api/v1/requests/{request_id}/history")
def request_history(
    request_id: UUID,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    req = session.get(WorkflowRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    history = session.exec(
        select(StatusHistory)
        .where(StatusHistory.request_id == request_id)
        .order_by(StatusHistory.created_at.asc())
    ).all()
    return [
        {
            "id": str(row.id),
            "from_status": row.from_status,
            "to_status": row.to_status,
            "actor_id": str(row.actor_id),
            "note": row.note,
            "created_at": row.created_at.isoformat(),
        }
        for row in history
    ]


@app.get("/api/v1/dashboard/summary")
def dashboard_summary(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    counts = {}
    for status in RequestStatus:
        counts[status.value] = session.exec(
            select(func.count()).select_from(WorkflowRequest).where(WorkflowRequest.status == status)
        ).one()
    return {"counts_by_status": counts, "viewer_role": user.role.value}


@app.get("/api/v1/audit")
def list_audit(session: Session = Depends(get_session), user: User = Depends(require_roles(Role.AUDITOR, Role.ADMIN))):
    events = session.exec(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)).all()
    return events
