from pydantic import BaseModel
from typing import List, Literal, Optional


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    project_id: str
    messages: List[Message]
    project_name: Optional[str] = None
