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
DEFAULT_OBSERVE_MINUTES = 30
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "processor": {"role": "writer", "password_hash": pwd.hash("herb123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def observe_due_at(started_at: datetime, minutes: float) -> datetime:
    """到期时刻。观察分钟为 0 时视为立即到期（到期时刻即出锅时刻）。"""
    return started_at + timedelta(minutes=float(minutes))


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


class ObserveMinutesIn(BaseModel):
    minutes: float = Field(ge=0, le=10080)


app = FastAPI(title="饮片炮制记录台")


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
        raise HTTPException(status_code=403, detail="仅炮制员可操作")
    return user


def get_setting(conn, key: str, default):
    row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
    if row is None:
        return default
    if isinstance(default, bool):
        return row["value"].lower() in ("1", "true", "yes")
    return type(default)(row["value"])


def get_observe_minutes(conn) -> float:
    return get_setting(conn, "observe_minutes", float(DEFAULT_OBSERVE_MINUTES))


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
                created_at timestamptz NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS observations (
                id serial PRIMARY KEY,
                batch_id integer NOT NULL REFERENCES batches(id),
                started_at timestamptz NOT NULL,
                observe_minutes numeric(8,1) NOT NULL CHECK (observe_minutes >= 0),
                due_at timestamptz NOT NULL,
                completed_at timestamptz,
                created_by text NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS app_settings (
                key text PRIMARY KEY,
                value text NOT NULL
            )"""
        )
        exists = conn.execute("SELECT 1 FROM app_settings WHERE key = 'observe_minutes'").fetchone()
        if exists is None:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES ('observe_minutes', %s)",
                (str(DEFAULT_OBSERVE_MINUTES),),
            )

        # 空库播种样例批次（甘草放行、黄芩温度过低未放行）
        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            now = utcnow()
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

        # 给没有观察行的批次补行：历史样例视为早已冷却完成，不占观察中列表
        minutes = get_observe_minutes(conn)
        missing = conn.execute(
            """SELECT b.id, b.created_at FROM batches b
               LEFT JOIN observations o ON o.batch_id = b.id
               WHERE o.id IS NULL ORDER BY b.id"""
        ).fetchall()
        for b in missing:
            conn.execute(
                """INSERT INTO observations (batch_id, started_at, observe_minutes, due_at, completed_at, created_by)
                   VALUES (%s, %s, %s, %s, %s, 'processor')""",
                (b["id"], b["created_at"], minutes, observe_due_at(b["created_at"], minutes), b["created_at"]),
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
    exp = utcnow() + timedelta(hours=8)
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
    now = utcnow()
    with connect() as conn:
        minutes = get_observe_minutes(conn)
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, created_by""",
            (body.herb.strip(), json.dumps(doc, ensure_ascii=False), verdict, reason, user["username"], now),
        ).fetchone()
        # 出锅即入冷却观察簿，按当前设置的观察分钟起算
        conn.execute(
            """INSERT INTO observations (batch_id, started_at, observe_minutes, due_at, created_by)
               VALUES (%s, %s, %s, %s, %s)""",
            (row["id"], now, minutes, observe_due_at(now, minutes), user["username"]),
        )
        conn.commit()
    return row


@app.get("/api/observation-setting")
def get_observation_setting(_user: dict = Depends(current_user)):
    with connect() as conn:
        minutes = get_observe_minutes(conn)
    return {"observe_minutes": float(minutes)}


@app.put("/api/observation-setting")
def set_observation_setting(body: ObserveMinutesIn, user: dict = Depends(require_writer)):
    with connect() as conn:
        conn.execute(
            """INSERT INTO app_settings (key, value) VALUES ('observe_minutes', %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (str(body.minutes),),
        )
        conn.commit()
    return {"observe_minutes": float(body.minutes)}


@app.get("/api/observations")
def list_observations(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            """SELECT o.id, o.batch_id, b.herb, b.verdict,
                      o.started_at, o.observe_minutes, o.due_at, o.completed_at, o.created_by
               FROM observations o JOIN batches b ON b.id = o.batch_id
               ORDER BY o.id DESC"""
        ).fetchall()
    now = utcnow()
    result = []
    for r in rows:
        remaining = (r["due_at"] - now).total_seconds()
        result.append(
            {
                "id": r["id"],
                "batch_id": r["batch_id"],
                "herb": r["herb"],
                "verdict": r["verdict"],
                "started_at": r["started_at"].isoformat(),
                "observe_minutes": float(r["observe_minutes"]),
                "due_at": r["due_at"].isoformat(),
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
                "remaining_seconds": max(0, round(remaining)),
                "eligible": remaining <= 0 or r["completed_at"] is not None,
                "created_by": r["created_by"],
            }
        )
    return result


@app.patch("/api/observations/{obs_id}/minutes")
def update_observation_minutes(obs_id: int, body: ObserveMinutesIn, user: dict = Depends(require_writer)):
    with connect() as conn:
        row = conn.execute("SELECT started_at, completed_at FROM observations WHERE id = %s", (obs_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="观察记录不存在")
        if row["completed_at"] is not None:
            raise HTTPException(status_code=400, detail="已完成的观察不能改分钟")
        new_due = observe_due_at(row["started_at"], body.minutes)
        updated = conn.execute(
            """UPDATE observations SET observe_minutes = %s, due_at = %s
               WHERE id = %s
               RETURNING id, started_at, observe_minutes, due_at, completed_at""",
            (body.minutes, new_due, obs_id),
        ).fetchone()
        conn.commit()
    now = utcnow()
    remaining = (updated["due_at"] - now).total_seconds()
    return {
        "id": updated["id"],
        "started_at": updated["started_at"].isoformat(),
        "observe_minutes": float(updated["observe_minutes"]),
        "due_at": updated["due_at"].isoformat(),
        "completed_at": updated["completed_at"].isoformat() if updated["completed_at"] else None,
        "remaining_seconds": max(0, round(remaining)),
        "eligible": remaining <= 0,
    }


@app.post("/api/observations/{obs_id}/complete", status_code=200)
def complete_observation(obs_id: int, user: dict = Depends(require_writer)):
    with connect() as conn:
        row = conn.execute(
            "SELECT id, due_at, completed_at FROM observations WHERE id = %s", (obs_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="观察记录不存在")
        if row["completed_at"] is not None:
            raise HTTPException(status_code=400, detail="该观察已完成")
        now = utcnow()
        if now < row["due_at"]:
            remain = int((row["due_at"] - now).total_seconds()) + 1
            raise HTTPException(status_code=400, detail=f"冷却观察未满时，还差 {remain} 秒，不能完成观察")
        conn.execute("UPDATE observations SET completed_at = %s WHERE id = %s", (now, obs_id))
        conn.commit()
    return {"id": obs_id, "completed_at": now.isoformat()}
