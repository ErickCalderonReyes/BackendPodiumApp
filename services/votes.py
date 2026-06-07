import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from datetime import datetime, timezone, timedelta

from db_models import Vote, Candidate
from schemas.votes import FreeVoteRequest, FreeVoteResponse
from config import settings

FREE_VOTE_TTL_SECONDS = 7200  # 2 horas


def _redis_key(user_id: int, candidate_id: int, season_year: int, tenant_slug: str) -> str:
    """
    Clave granular por usuario+candidato+season+tenant.
    Permite votar por distintos candidatos sin interferencia entre ellos.
    """
    return f"free_vote:{tenant_slug}:{season_year}:{user_id}:{candidate_id}"


async def cast_free_vote(
    request: FreeVoteRequest,
    user_id: int,
    db: AsyncSession,
    redis: aioredis.Redis,
    tenant_slug: str = settings.TENANT_SLUG,
) -> FreeVoteResponse:

    # 1. Verificar que el candidato existe y pertenece a este tenant/season
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == request.candidate_id,
            Candidate.season_year == request.season_year,
            Candidate.tenant_slug == tenant_slug,
            Candidate.is_active == True,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidato no encontrado o no activo en esta temporada",
        )

    # 2. Verificar cooldown en Redis
    key = _redis_key(user_id, request.candidate_id, request.season_year, tenant_slug)
    ttl = await redis.ttl(key)

    if ttl > 0:
        # Está en cooldown — calcular next_available_at
        next_available_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        return FreeVoteResponse(
            success=False,
            message="Ya votaste recientemente por este candidato",
            next_available_at=next_available_at,
            seconds_remaining=ttl,
        )

    # 3. Insertar voto en SQL
    vote = Vote(
        user_id=user_id,
        candidate_id=request.candidate_id,
        season_year=request.season_year,
        tenant_slug=tenant_slug,
        is_free=True,
    )
    db.add(vote)
    await db.commit()
    await db.refresh(vote)

    # 4. Activar cooldown en Redis DESPUÉS del commit exitoso
    #    Si el commit falla, la llave Redis nunca se crea — no hay falso bloqueo.
    await redis.setex(key, FREE_VOTE_TTL_SECONDS, "1")

    next_available_at = datetime.now(timezone.utc) + timedelta(seconds=FREE_VOTE_TTL_SECONDS)

    return FreeVoteResponse(
        success=True,
        message="¡Voto registrado exitosamente!",
        vote_id=vote.id,
        next_available_at=next_available_at,
        seconds_remaining=FREE_VOTE_TTL_SECONDS,
    )