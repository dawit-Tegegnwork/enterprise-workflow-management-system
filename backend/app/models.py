from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlmodel import Column, JSON, Field as SQLField, SQLModel, Session, create_engine, select

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class Settings(BaseSettings):
    secret_key: str = "portfolio-demo-secret-change-in-production"
    database_url: str = "sqlite:///./workflow.db"
    token_expire_minutes: int = 60

    model_config = SettingsConfigDict(env_prefix="WORKFLOW_")


settings = Settings()


class Role(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    STAFF = "staff"
    AUDITOR = "auditor"


class RequestStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    email: str = SQLField(unique=True, index=True)
    full_name: str
    role: Role
    password_hash: str
    department: str = "Operations"


class WorkflowRequest(SQLModel, table=True):
    __tablename__ = "workflow_requests"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    title: str
    description: str
    requester_id: UUID = SQLField(foreign_key="users.id")
    department: str
    status: RequestStatus = RequestStatus.DRAFT
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class RequestComment(SQLModel, table=True):
    __tablename__ = "request_comments"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    request_id: UUID = SQLField(foreign_key="workflow_requests.id")
    author_id: UUID = SQLField(foreign_key="users.id")
    body: str
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class StatusHistory(SQLModel, table=True):
    __tablename__ = "status_history"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    request_id: UUID = SQLField(foreign_key="workflow_requests.id")
    from_status: Optional[str] = None
    to_status: str
    actor_id: UUID = SQLField(foreign_key="users.id")
    note: str = ""
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    action: str
    actor_id: Optional[UUID] = None
    entity_type: str = ""
    entity_id: Optional[str] = None
    metadata_json: dict = SQLField(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


class LoginInput(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    full_name: str


class RequestCreateInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    department: str = Field(default="Operations", max_length=100)


class TransitionInput(BaseModel):
    action: str = Field(description="approve, reject, request_changes, submit")
    note: str = ""


def seed_users(session: Session) -> None:
    if session.exec(select(User)).first():
        return
    users = [
        ("admin@demo.local", "Admin User", Role.ADMIN, "IT"),
        ("manager@demo.local", "Manager User", Role.MANAGER, "Operations"),
        ("staff@demo.local", "Staff User", Role.STAFF, "Operations"),
        ("auditor@demo.local", "Auditor User", Role.AUDITOR, "Compliance"),
    ]
    for email, name, role, dept in users:
        session.add(
            User(
                email=email,
                full_name=name,
                role=role,
                department=dept,
                password_hash=hash_password("Demo123!"),
            )
        )
    session.commit()
