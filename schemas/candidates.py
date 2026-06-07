from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from datetime import datetime


class CandidateBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    state: str = Field(..., min_length=2, max_length=100)
    bio: Optional[str] = None
    photo_url: Optional[str] = Field(None, max_length=500)
    season_year: int = Field(..., ge=2020, le=2100)
    is_active: bool = True


class CandidateCreate(CandidateBase):
    pass


class CandidatePatch(BaseModel):
    """Todos los campos opcionales — solo se actualiza lo que llega."""
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    state: Optional[str] = Field(None, min_length=2, max_length=100)
    bio: Optional[str] = None
    photo_url: Optional[str] = Field(None, max_length=500)
    season_year: Optional[int] = Field(None, ge=2020, le=2100)
    is_active: Optional[bool] = None


class CandidateOut(CandidateBase):
    id: int
    tenant_slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateVoteSummary(CandidateOut):
    """Para el endpoint público de votación — incluye conteo de votos."""
    vote_count: int = 0