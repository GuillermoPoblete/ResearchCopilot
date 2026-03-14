from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import uuid
from datetime import datetime
from typing import List

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import inspect, text

from app.schemas.chat import ChatRequest
from app.schemas.analysis import AnalysisRunRequest
from app.services.auth import verify_google_token
from app.services.llm_services import stream_chat_completion
from app.services.dataset_store import dataset_store
from app.services.google_sheets import load_first_sheet_dataframe
from app.services.analysis_runtime import generate_analysis_code, execute_analysis_code

from app.db.database import engine, SessionLocal
from app.db.models import Base, Project, Message


app = FastAPI(title="Research Copilot API")


class CreateProjectRequest(BaseModel):
    name: str


class RenameProjectRequest(BaseModel):
    name: str



app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://researchcopilot-production.up.railway.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crear tablas
Base.metadata.create_all(bind=engine)


def _ensure_soft_delete_column():
    # Keep existing local DBs compatible without requiring a migration tool.
    inspector = inspect(engine)
    if "projects" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("projects")}
    if "deleted_at" in columns:
        return
    deleted_col_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE projects ADD COLUMN deleted_at {deleted_col_type}"))


_ensure_soft_delete_column()




@app.exception_handler(Exception)
async def log_exception(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/healthz")
def healthz():
    return {"ok": True}







def _get_google_user(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    return verify_google_token(token)

def _get_user_id(user_payload: dict) -> str:
    return user_payload.get("sub") or user_payload.get("email") or "unknown-user"


def _get_active_project(db, project_id: str, user_id: str):
    return (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.user_id == user_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )


@app.post("/chat/stream")
def chat_stream(request: ChatRequest, user_payload: dict = Depends(_get_google_user)):
    db = SessionLocal()
    user_id = _get_user_id(user_payload)

    # Asegurar proyecto
    project = (
        db.query(Project)
        .filter(
            Project.id == request.project_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if not project:
        project = Project(
            id=request.project_id,
            name=request.project_name or "Unnamed project",
            user_id=user_id,
        )
        db.add(project)
        db.commit()
    elif project.user_id != user_id:
        db.close()
        raise HTTPException(status_code=403, detail="Project not accessible")

    # Guardar mensajes del usuario
    for m in request.messages:
        exists = (
            db.query(Message)
            .filter(
                Message.project_id == request.project_id,
                Message.role == m.role,
                Message.content == m.content,
            )
            .first()
        )
        if not exists:
            db.add(
                Message(
                    id=str(uuid.uuid4()),
                    project_id=request.project_id,
                    role=m.role,
                    content=m.content,
                )
            )
    db.commit()

    def event_generator():
        full_response = ""

        try:
            for token in stream_chat_completion(
                [{"role": m.role, "content": m.content} for m in request.messages]
            ):
                full_response += token
                yield f"data: {token}\n\n"
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            if full_response.strip():
                db.add(
                    Message(
                        id=str(uuid.uuid4()),
                        project_id=request.project_id,
                        role="assistant",
                        content=full_response,
                    )
                )
                db.commit()
                db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@app.get("/projects/{project_id}/messages")
def get_project_messages(
    project_id: str,
    user_payload: dict = Depends(_get_google_user),
) -> List[dict]:
    db = SessionLocal()

    user_id = _get_user_id(user_payload)
    project = _get_active_project(db, project_id, user_id)
    if not project:
        db.close()
        raise HTTPException(status_code=404, detail="Project not found")

    msgs = (
        db.query(Message)
        .filter(Message.project_id == project_id)
        .order_by(Message.created_at)
        .all()
    )

    db.close()

    return [
        {"role": m.role, "content": m.content}
        for m in msgs
    ]



@app.post("/projects")
def create_project(request: CreateProjectRequest, user_payload: dict = Depends(_get_google_user)):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name required")

    db = SessionLocal()
    user_id = _get_user_id(user_payload)

    project = Project(
        id=str(uuid.uuid4()),
        name=name,
        user_id=user_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    result = {"id": project.id, "name": project.name, "user_id": project.user_id}
    db.close()

    return result


@app.patch("/projects/{project_id}")
def rename_project(
    project_id: str,
    request: RenameProjectRequest,
    user_payload: dict = Depends(_get_google_user),
):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name required")

    db = SessionLocal()
    user_id = _get_user_id(user_payload)
    project = _get_active_project(db, project_id, user_id)
    if not project:
        db.close()
        raise HTTPException(status_code=404, detail="Project not found")

    project.name = name
    db.commit()
    db.refresh(project)
    result = {"id": project.id, "name": project.name, "user_id": project.user_id}
    db.close()
    return result


@app.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    user_payload: dict = Depends(_get_google_user),
):
    db = SessionLocal()
    user_id = _get_user_id(user_payload)
    project = _get_active_project(db, project_id, user_id)
    if not project:
        db.close()
        raise HTTPException(status_code=404, detail="Project not found")

    project.deleted_at = datetime.utcnow()
    db.commit()
    db.close()
    return {"ok": True}


@app.post("/projects/{project_id}/restore")
def restore_project(
    project_id: str,
    user_payload: dict = Depends(_get_google_user),
):
    db = SessionLocal()
    user_id = _get_user_id(user_payload)
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.user_id == user_id,
            Project.deleted_at.is_not(None),
        )
        .first()
    )
    if not project:
        db.close()
        raise HTTPException(status_code=404, detail="Project not found")

    project.deleted_at = None
    db.commit()
    db.refresh(project)
    result = {"id": project.id, "name": project.name, "user_id": project.user_id}
    db.close()
    return result


@app.post("/analysis/run")
def run_analysis(
    request: AnalysisRunRequest,
    user_payload: dict = Depends(_get_google_user),
):
    user_id = _get_user_id(user_payload)
    db = SessionLocal()
    project = _get_active_project(db, request.project_id, user_id)
    db.close()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    entry = dataset_store.get(user_id=user_id, project_id=request.project_id)
    if request.sheet_url:
        if not request.google_access_token:
            raise HTTPException(
                status_code=400,
                detail="google_access_token is required when sheet_url is provided",
            )
        df, context = load_first_sheet_dataframe(request.sheet_url, request.google_access_token)
        entry = dataset_store.set(
            user_id=user_id,
            project_id=request.project_id,
            sheet_url=request.sheet_url,
            context=context,
            dataframe=df,
        )

    if not entry:
        raise HTTPException(
            status_code=400,
            detail="No dataset loaded for this project. Provide sheet_url and google_access_token.",
        )

    try:
        code = generate_analysis_code(request.prompt, entry.context)
        execution = execute_analysis_code(
            code=code,
            dataframe=entry.dataframe,
            context=entry.context,
            timeout_sec=30,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    return {
        "status": execution["status"],
        "error": execution["error"],
        "dataset_context": entry.context,
        "generated_code": code,
        "result": execution["result"],
        "stdout": execution["stdout"],
        "stderr": execution["stderr"],
    }

@app.get("/projects")
def list_projects(user_payload: dict = Depends(_get_google_user)):
    try:
        db = SessionLocal()
        user_id = _get_user_id(user_payload)
        projects = (
            db.query(Project)
            .filter(
                Project.user_id == user_id,
                Project.deleted_at.is_(None),
            )
            .order_by(Project.created_at)
            .all()
        )
        db.close()

        return [
            {
                "id": p.id,
                "name": p.name,
                "user_id": p.user_id,
            }
            for p in projects
        ]
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": str(exc)})
