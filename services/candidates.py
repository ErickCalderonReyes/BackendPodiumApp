from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import NoResultFound
from fastapi import HTTPException, status
from typing import Optional

from db_models import Candidate, Vote
from schemas.candidates import CandidateCreate, CandidatePatch
from config import settings


# ──────────────────────────────────────────
# LECTURA
# ──────────────────────────────────────────

async def get_candidates(
    db: AsyncSession,
    season_year: int,
    include_inactive: bool = False,
    tenant_slug: str = settings.TENANT_SLUG,
) -> list[dict]:
    """
    Retorna candidatos con su conteo de votos para el season/tenant dado.
    Se usa tanto en el endpoint público como en el admin.
    """
    # Subquery: total votos por candidato en este season
    votes_sq = (
        select(Vote.candidate_id, func.count(Vote.id).label("vote_count"))
        .where(Vote.season_year == season_year, Vote.tenant_slug == tenant_slug)
        .group_by(Vote.candidate_id)
        .subquery()
    )

    stmt = (
        select(Candidate, func.coalesce(votes_sq.c.vote_count, 0).label("vote_count"))
        .outerjoin(votes_sq, Candidate.id == votes_sq.c.candidate_id)
        .where(
            Candidate.season_year == season_year,
            Candidate.tenant_slug == tenant_slug,
        )
    )

    if not include_inactive:
        stmt = stmt.where(Candidate.is_active == True)

    stmt = stmt.order_by(votes_sq.c.vote_count.desc())

    result = await db.execute(stmt)
    rows = result.all()

    # Armamos los dicts a mano porque el join nos da tuplas (Candidate, int)
    return [
        {**row.Candidate.__dict__, "vote_count": row.vote_count}
        for row in rows
    ]


async def get_candidate_by_id(
    candidate_id: int,
    db: AsyncSession,
    tenant_slug: str = settings.TENANT_SLUG,
) -> Candidate:
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_slug == tenant_slug,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidato {candidate_id} no encontrado",
        )
    return candidate


# ──────────────────────────────────────────
# ESCRITURA (protegida por rol en el router)
# ──────────────────────────────────────────

async def create_candidate(
    data: CandidateCreate,
    db: AsyncSession,
    tenant_slug: str = settings.TENANT_SLUG,
) -> Candidate:
    candidate = Candidate(**data.model_dump(), tenant_slug=tenant_slug)
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def patch_candidate(
    candidate_id: int,
    data: CandidatePatch,
    db: AsyncSession,
    tenant_slug: str = settings.TENANT_SLUG,
) -> Candidate:
    candidate = await get_candidate_by_id(candidate_id, db, tenant_slug)

    # Solo actualiza campos que llegaron explícitamente (exclude_unset)
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se enviaron campos para actualizar",
        )

    for field, value in updates.items():
        setattr(candidate, field, value)

    await db.commit()
    await db.refresh(candidate)
    return candidate


async def delete_candidate(
    candidate_id: int,
    db: AsyncSession,
    tenant_slug: str = settings.TENANT_SLUG,
) -> None:
    """
    Soft delete: marca is_active=False en lugar de borrar la fila.
    Los votos ya emitidos quedan intactos en la tabla votes.
    """
    candidate = await get_candidate_by_id(candidate_id, db, tenant_slug)
    candidate.is_active = False
    await db.commit()