from datetime import datetime

from pydantic import BaseModel, Field


class EmailTemplateRead(BaseModel):
    key: str
    subject: str
    body_html: str
    description: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmailTemplateUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    body_html: str | None = Field(default=None, min_length=1)
    description: str | None = None
