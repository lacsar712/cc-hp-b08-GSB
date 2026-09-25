import json
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from rules import judge

SECRET = os.environ.get("JWT_SECRET", "herb-process-dev-secret")
DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54393/herb")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "processor": {"role": "writer", "password_hash": pwd.hash("herb123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class StepIn(BaseModel):
    name: str
    temp_c: float
    minutes: float


class BatchIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    steps: list[StepIn]


class MinutesIn(BaseModel):
    minutes: float = Field(ge=0, le=10000)


DEFAULT_OBSERVE_MINUTES = 30.0


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=401, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def require_writer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail="仅炮制员可写入记录")
    return user


app = FastAPI(title="饮片炮制记录台")


@app.on_event("startup")
def startup():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batches (
                id serial PRIMARY KEY,
                herb text NOT NULL,
                doc jsonb NOT NULL,
                verdict text NOT NULL,
                reason text NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL,
                observe_completed_at timestamptz
            )"""
        )
        conn.execute(
            "ALTER TABLE batches ADD COLUMN IF NOT EXISTS observe_completed_at timestamptz"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                key text PRIMARY KEY,
                value double precision NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('observe_minutes', %s) "
            "ON CONFLICT (key) DO NOTHING",
            (DEFAULT_OBSERVE_MINUTES,),
        )
        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("甘草", {"steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}),
                ("黄芩", {"steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}),
            ]
            for herb, doc in samples:
                verdict, reason = judge(doc)
                conn.execute(
                    """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
                       VALUES (%s, %s::jsonb, %s, %s, %s, %s)""",
                    (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, "processor", now),
                )
        conn.commit()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "herb-process-record"}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = USERS.get(body.username.strip())
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username.strip(), "role": user["role"], "exp": exp}, SECRET, algorithm="HS256")
    return {"access_token": token, "username": body.username.strip(), "role": user["role"]}


@app.get("/api/batches")
def list_batches(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute("SELECT id, herb, doc, verdict, reason, created_by FROM batches ORDER BY id DESC").fetchall()
    return rows


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, user: dict = Depends(require_writer)):
    doc = {"steps": [s.model_dump() for s in body.steps]}
    verdict, reason = judge(doc)
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, created_by""",
            (body.herb.strip(), json.dumps(doc, ensure_ascii=False), verdict, reason, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row


def _observe_minutes(conn) -> float:
    row = conn.execute("SELECT value FROM settings WHERE key = 'observe_minutes'").fetchone()
    return float(row["value"]) if row else DEFAULT_OBSERVE_MINUTES


def _serialize_observation(row: dict, minutes: float) -> dict:
    due_at = row["created_at"] + timedelta(minutes=minutes)
    return {
        "id": row["id"],
        "herb": row["herb"],
        "verdict": row["verdict"],
        "reason": row["reason"],
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat(),
        "observe_minutes": minutes,
        "due_at": due_at.isoformat(),
        "observe_completed_at": row["observe_completed_at"].isoformat() if row["observe_completed_at"] else None,
    }


@app.get("/api/observation")
def observation_book(_user: dict = Depends(current_user)):
    with connect() as conn:
        minutes = _observe_minutes(conn)
        rows = conn.execute(
            """SELECT id, herb, verdict, reason, created_by, created_at, observe_completed_at
               FROM batches ORDER BY id DESC"""
        ).fetchall()
    observing = [_serialize_observation(r, minutes) for r in rows if r["observe_completed_at"] is None]
    completed = [_serialize_observation(r, minutes) for r in rows if r["observe_completed_at"] is not None]
    return {"minutes": minutes, "observing": observing, "completed": completed}


@app.put("/api/observation/minutes")
def set_observe_minutes(body: MinutesIn, user: dict = Depends(require_writer)):
    with connect() as conn:
        conn.execute(
            """INSERT INTO settings (key, value) VALUES ('observe_minutes', %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (body.minutes,),
        )
        conn.commit()
    return {"minutes": body.minutes}


@app.post("/api/observation/{batch_id}/complete")
def complete_observation(batch_id: int, user: dict = Depends(require_writer)):
    now = datetime.now(timezone.utc)
    with connect() as conn:
        minutes = _observe_minutes(conn)
        row = conn.execute(
            "SELECT id, created_at, observe_completed_at FROM batches WHERE id = %s",
            (batch_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="记录不存在")
        if row["observe_completed_at"] is not None:
            raise HTTPException(status_code=409, detail="该行已完成观察")
        created_at = row["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if now < created_at + timedelta(minutes=minutes):
            raise HTTPException(status_code=409, detail=f"未满观察分钟（{minutes:g} 分钟），禁止完成观察")
        updated = conn.execute(
            "UPDATE batches SET observe_completed_at = %s WHERE id = %s "
            "RETURNING observe_completed_at",
            (now, batch_id),
        ).fetchone()
        conn.commit()
    return {"id": batch_id, "observe_completed_at": updated["observe_completed_at"].isoformat()}
