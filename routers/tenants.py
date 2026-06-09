# ════════════════════════════════════════════════════════
# routers/tenants.py
# ════════════════════════════════════════════════════════
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db, get_current_user
from core.guards import require_director_or_admin
from schemas.tenants import TenantOut, TenantPublic, StripeConnectResponse
from services import tenants as svc
from db_models import User

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/{slug}", response_model=TenantPublic)
async def get_tenant_public(slug: str, db: AsyncSession = Depends(get_db)):
    """
    Endpoint público — Angular lo llama al arrancar para cargar la marca.
    Lee window.location.hostname, extrae el slug y llama aquí.
    """
    tenant = await svc.get_tenant_by_slug(slug, db)
    return tenant


@router.get("/me/dashboard", response_model=TenantOut)
async def get_my_tenant(
    user: User = Depends(require_director_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard del director — retorna el tenant completo con estado del plan."""
    tenant = await svc.get_tenant_by_owner(user.id, db)
    return tenant


@router.post("/connect-stripe", response_model=StripeConnectResponse)
async def connect_stripe(
    user: User = Depends(require_director_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Genera el link de onboarding Stripe Express para el director.
    El botón en el panel dice "Recibe pagos directo a tu cuenta".
    Si ya tiene cuenta Express → genera nuevo link (re-onboarding).
    """
    tenant = await svc.get_tenant_by_owner(user.id, db)
    result = await svc.create_stripe_connect_link(tenant, db)
    return result