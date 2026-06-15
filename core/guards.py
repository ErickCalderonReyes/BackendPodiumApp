"""
core/guards.py
──────────────
Guards de FastAPI para enforcement de plan freemium.

Uso como dependencia:
    @router.post("/candidates")
    async def create_candidate(
        ...,
        _: None = Depends(check_candidates_limit),
    ):

Todos los guards retornan un error estructurado con upgrade_url
para que el frontend pueda mostrar el banner de upgrade correcto.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.dependencies import get_db, get_current_user
from core.plans import PLAN_LIMITS, within_limit, is_feature_enabled
from db_models import User, Tenant, Candidate
from schemas.payments import CheckoutRequest

# ── Helper interno ─────────────────────────────────────────────────────────

def _plan_limit_error(message: str, feature_key: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code":        "PLAN_LIMIT",
            "message":     message,
            "feature":     feature_key,
            "upgrade_url": "/billing/upgrade",
        },
    )


async def _get_tenant_for_user(user: User, db: AsyncSession) -> Tenant:
    """Obtiene el tenant del director autenticado.
    Solo state_director y national_admin tienen tenant.
    """
    result = await db.execute(
        select(Tenant).where(
            Tenant.owner_id == user.id,
            Tenant.is_active == True,
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró un certamen activo asociado a tu cuenta.",
        )
    return tenant


# ── Guards de rol ──────────────────────────────────────────────────────────

async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Solo national_admin puede pasar."""
    if user.role != "national_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol national_admin",
        )
    return user


async def require_director_or_admin(
    user: User = Depends(get_current_user),
) -> User:
    """state_director o national_admin."""
    if user.role not in ("state_director", "national_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol state_director o national_admin",
        )
    return user


# ── Guards de plan ─────────────────────────────────────────────────────────

async def require_pro(
    user: User = Depends(require_director_or_admin),
    db:   AsyncSession = Depends(get_db),
) -> Tenant:
    """Bloquea si el tenant está en plan Free.
    Retorna el tenant para que el endpoint lo use sin una segunda query.
    """
    tenant = await _get_tenant_for_user(user, db)
    if tenant.plan == "free":
        raise _plan_limit_error(
            "Esta función requiere el plan Pro. "
            "Actualiza para recibir pagos directos a tu cuenta.",
            "paid_votes",
        )
    return tenant


async def check_candidates_limit(
    user: User = Depends(require_director_or_admin),
    db:   AsyncSession = Depends(get_db),
) -> None:
    """Bloquea POST /candidates si el tenant Free ya alcanzó su límite."""
    tenant = await _get_tenant_for_user(user, db)

    # Contar candidatos activos del tenant en la season actual
    result = await db.execute(
        select(func.count()).where(
            Candidate.tenant_slug == tenant.slug,
            Candidate.season_year == tenant.season_year,
            Candidate.is_active   == True,
        )
    )
    current = result.scalar_one()

    if not within_limit(tenant.plan, "max_candidates", current):
        limit = PLAN_LIMITS[tenant.plan]["max_candidates"]
        raise _plan_limit_error(
            f"El plan Free permite hasta {limit} candidatos activos por temporada. "
            "Actualiza a Pro para candidatos ilimitados.",
            "max_candidates",
        )


async def check_sponsors_limit(
    user: User = Depends(require_director_or_admin),
    db:   AsyncSession = Depends(get_db),
) -> None:
    """Bloquea POST /sponsors si el tenant Free ya alcanzó su límite.
    Cuando exista el modelo Sponsor, importarlo y usarlo aquí igual que
    check_candidates_limit.  Por ahora levanta un placeholder.
    """
    tenant = await _get_tenant_for_user(user, db)

    # TODO: reemplazar 0 con count real cuando exista modelo Sponsor
    current = 0

    if not within_limit(tenant.plan, "max_sponsors", current):
        limit = PLAN_LIMITS[tenant.plan]["max_sponsors"]
        raise _plan_limit_error(
            f"El plan Free permite hasta {limit} patrocinadores activos. "
            "Actualiza a Pro para patrocinadores ilimitados.",
            "max_sponsors",
        )


async def resolve_paid_votes_tenant(
    body: "CheckoutRequest",
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> Tenant:
    """Guard para POST /payments/create-session.

    A diferencia de require_pro, el comprador es un VOTER (no el dueño del
    certamen), así que el tenant NO se resuelve por owner_id sino por el
    tenant_slug que el votante está votando. Solo exige JWT válido — sin rol.

    Verifica que el certamen exista, esté activo y tenga plan Pro.
    """
    result = await db.execute(
        select(Tenant).where(
            Tenant.slug == body.tenant_slug,
            Tenant.is_active == True,
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certamen no encontrado o inactivo.",
        )
    if tenant.plan == "free":
        raise _plan_limit_error(
            "Este certamen no tiene habilitados los votos de pago.",
            "paid_votes",
        )
    return tenant