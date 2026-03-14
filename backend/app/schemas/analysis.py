from pydantic import BaseModel, Field


class AnalysisRunRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    sheet_url: str | None = None
    google_access_token: str | None = None
