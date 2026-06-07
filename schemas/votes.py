from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class FreeVoteRequest(BaseModel):
    candidate_id: int = Field(..., gt=0)
    season_year: int = Field(..., ge=2020, le=2100)


class FreeVoteResponse(BaseModel):
    success: bool
    message: str
    # Si el voto fue exitoso:
    vote_id: Optional[int] = None
    # Si está en cooldown:
    next_available_at: Optional[datetime] = None
    seconds_remaining: Optional[int] = None