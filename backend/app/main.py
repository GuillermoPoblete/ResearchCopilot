from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import uuid
from typing import List

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from app.schemas.chat import ChatRequest
from app.services.auth import verify_google_token
from app.services.llm_services import stream_chat_completion

from app.db.database import engine, SessionLocal
from app.db.models import Base, Project, Message


app = FastAPI(title="Research Copilot API")


class CreateProjectRequest(BaseModel):
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

@app.post("/chat/stream")
def chat_stream(request: ChatRequest, user_payload: dict = Depends(_get_google_user)):
    db = SessionLocal()
    user_id = _get_user_id(user_payload)

    # Asegurar proyecto
    project = db.query(Project).filter(Project.id == request.project_id).first()
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
        except Exception as exc:
            import traceback
            traceback.print_exc()
            err_text = f"[error] {type(exc).__name__}: {exc}"
            yield f"data: {err_text}\n\n"
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
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or project.user_id != user_id:
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

@app.get("/projects")
def list_projects(user_payload: dict = Depends(_get_google_user)):
    try:
        db = SessionLocal()
        user_id = _get_user_id(user_payload)
        projects = (
            db.query(Project)
            .filter(Project.user_id == user_id)
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
