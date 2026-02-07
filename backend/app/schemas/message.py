from typing import List

@app.get("/projects/{project_id}/messages")
def get_project_messages(project_id: str) -> List[dict]:
    db = SessionLocal()
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
