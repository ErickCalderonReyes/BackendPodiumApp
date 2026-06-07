from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db, get_current_user, require_admin
from schemas.candidates import CandidateCreate, CandidatePatch, CandidateVoteSummary, CandidateOut
from services import candidates as svc
from db_models import User
from config import settings

router = APIRouter(prefix="/candidates", tags=["candidates"])


# ── PÚBLICO ──────────────────────────────────────────────────────────────────

@router.get("", response_model=list[CandidateVoteSummary])
async def list_candidates(
    season_year: int = Query(..., description="Año del certamen, ej: 2026"),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista candidatos activos con su conteo de votos, ordenados por votos desc.
    Este endpoint es público — no requiere JWT.
    """
    return await svc.get_candidates(db, season_year=season_year)


# ── ADMIN ─────────────────────────────────────────────────────────────────────

@router.post("", response_model=CandidateOut, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    data: CandidateCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return await svc.create_candidate(data, db)


@router.patch("/{candidate_id}", response_model=CandidateOut)
async def patch_candidate(
    candidate_id: int,
    data: CandidatePatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return await svc.patch_candidate(candidate_id, data, db)


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    await svc.delete_candidate(candidate_id, db)