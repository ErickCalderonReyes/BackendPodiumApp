from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from core.dependencies import get_db, get_current_user
from core.redis import get_redis          # lo definimos abajo
from schemas.votes import FreeVoteRequest, FreeVoteResponse
from services import votes as svc
from db_models import User

router = APIRouter(prefix="/votes", tags=["votes"])


@router.post("/free", response_model=FreeVoteResponse, status_code=status.HTTP_200_OK)
async def cast_free_vote(
    request: FreeVoteRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    current_user: User = Depends(get_current_user),
):
    """
    Emite un voto gratuito. Bloqueado por Redis TTL de 2h por usuario+candidato.
    Retorna `seconds_remaining` y `next_available_at` cuando está en cooldown
    para que el frontend active el countdown sin hacer polling.
    """
    return await svc.cast_free_vote(
        request=request,
        user_id=current_user.id,
        db=db,
        redis=redis,
    )