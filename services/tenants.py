import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db_models import Tenant
from config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY


async def get_tenant_by_slug(slug: str, db: AsyncSession) -> Tenant:
    result = await db.execute(
        select(Tenant).where(Tenant.slug == slug, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certamen '{slug}' no encontrado",
        )
    return tenant


async def get_tenant_by_owner(owner_id: int, db: AsyncSession) -> Tenant:
    result = await db.execute(
        select(Tenant).where(Tenant.owner_id == owner_id, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró un certamen activo asociado a tu cuenta",
        )
    return tenant


async def create_stripe_connect_link(
    tenant: Tenant,
    db: AsyncSession,
) -> dict:
    """
    Genera (o reutiliza) una cuenta Stripe Express para el director
    y retorna un AccountLink de onboarding.

    Flujo:
      1. Si el tenant ya tiene stripe_account_id → solo genera nuevo link
         (útil si el director no completó el onboarding la primera vez)
      2. Si no tiene → crea la cuenta Express primero

    El director completa el formulario de Stripe (~10 min) con RFC,
    datos fiscales y CLABE. Sin asistencia técnica requerida.
    """
    # ── Crear cuenta Express si no existe ────────────────────────────────
    if not tenant.stripe_account_id:
        account = stripe.Account.create(
            type="express",
            country="MX",
            capabilities={
                "card_payments": {"requested": True},
                "transfers":     {"requested": True},
            },
        )
        tenant.stripe_account_id = account.id
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

    # ── Generar AccountLink ───────────────────────────────────────────────
    base_url = settings.FRONTEND_URL  # ej: https://mrintmx.podiumapp.com
    account_link = stripe.AccountLink.create(
        account    = tenant.stripe_account_id,
        refresh_url= f"{base_url}/dashboard/stripe-connect?refresh=1",
        return_url = f"{base_url}/dashboard/stripe-connect?success=1",
        type       = "account_onboarding",
    )

    return {
        "onboarding_url": account_link.url,
        "account_id":     tenant.stripe_account_id,
    }
