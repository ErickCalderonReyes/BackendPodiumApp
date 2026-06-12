"""
routers/tenants.py
──────────────────
Gestión de tenants + onboarding Stripe Express.

Endpoints:
  GET  /tenants/{slug}                     → TenantPublic para Angular
  GET  /tenants/me                         → TenantOut completo (director autenticado)
  POST /tenants/connect-stripe             → genera link de onboarding Express [Pro]
  GET  /tenants/connect-stripe/return      → callback post-onboarding (guarda account_id)
  GET  /tenants/connect-stripe/refresh     → regenera link si expiró
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import stripe

from config import settings
from core.dependencies import get_db, get_current_user
from core.guards import require_pro, require_director_or_admin
from db_models import Tenant, User
from schemas.tenants import TenantOut, TenantPublic, StripeConnectResponse

stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(prefix="/tenants", tags=["tenants"])


# ── Helpers ────────────────────────────────────────────────────────────────

async def _get_tenant_by_slug_or_404(slug: str, db: AsyncSession) -> Tenant:
    result = await db.execute(
        select(Tenant).where(Tenant.slug == slug, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certamen '{slug}' no encontrado.",
        )
    return tenant


async def _get_tenant_for_owner(user: User, db: AsyncSession) -> Tenant:
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


def _build_onboarding_url(account_id: str, tenant_slug: str) -> str:
    """Genera un AccountLink de onboarding Express para el account_id dado."""
    base = settings.FRONTEND_URL
    account_link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=f"{base}/panel/stripe-connect/refresh",
        return_url=f"{base}/panel/stripe-connect/exito",
        type="account_onboarding",
    )
    return account_link.url


# ── GET /tenants/{slug} — público para Angular ──────────────────────────────

@router.get("/{slug}", response_model=TenantPublic)
async def get_tenant_public(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna la información de marca del certamen.
    Usado por Angular en APP_INITIALIZER para cargar colores, logo y nombre.
    No requiere autenticación.
    """
    return await _get_tenant_by_slug_or_404(slug, db)


# ── GET /tenants/me — para el panel del director ────────────────────────────

@router.get("/me/detail", response_model=TenantOut)
async def get_my_tenant(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_director_or_admin),
):
    """Retorna el tenant completo del director autenticado (para su panel)."""
    return await _get_tenant_for_owner(user, db)


# ── POST /tenants/connect-stripe ────────────────────────────────────────────

@router.post("/connect-stripe", response_model=StripeConnectResponse)
async def connect_stripe(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(require_pro),
):
    """
    Genera el link de onboarding Stripe Express para el director.

    Flujo:
    1. Si el tenant ya tiene stripe_account_id → regenera el AccountLink.
    2. Si no → crea una cuenta Express nueva, guarda el account_id, genera link.

    El director visita la URL y completa el formulario Stripe guiado (~10 min):
    RFC, datos fiscales y CLABE. Al terminar, Stripe redirige al return_url.
    """
    if tenant.stripe_account_id:
        # Cuenta ya existe — solo regenerar el link (útil si expiró o no completó)
        try:
            onboarding_url = _build_onboarding_url(
                account_id=tenant.stripe_account_id,
                tenant_slug=tenant.slug,
            )
        except stripe.error.StripeError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error al generar link de Stripe: {str(e)}",
            )
        return StripeConnectResponse(
            onboarding_url=onboarding_url,
            account_id=tenant.stripe_account_id,
        )

    # Crear cuenta Express nueva para México
    try:
        account = stripe.Account.create(
            type="express",
            country="MX",
            email=tenant.owner.email if tenant.owner else None,
            capabilities={
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
            metadata={
                "tenant_slug": tenant.slug,
                "tenant_id": str(tenant.id),
            },
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al crear cuenta Stripe: {str(e)}",
        )

    # Guardar account_id inmediatamente (antes de que el director complete el form)
    tenant.stripe_account_id = account.id
    await db.commit()

    # Generar link de onboarding
    try:
        onboarding_url = _build_onboarding_url(
            account_id=account.id,
            tenant_slug=tenant.slug,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al generar link de onboarding: {str(e)}",
        )

    return StripeConnectResponse(
        onboarding_url=onboarding_url,
        account_id=account.id,
    )


# ── GET /tenants/connect-stripe/return ──────────────────────────────────────
# Este endpoint es el return_url del AccountLink.
# Stripe redirige aquí cuando el director TERMINA el formulario.
# IMPORTANTE: Stripe puede redirigir aquí incluso si el onboarding no está
# 100% completo. Verificar con stripe.Account.retrieve() el campo
# details_submitted para confirmar que la cuenta está lista para recibir pagos.

@router.get("/connect-stripe/return")
async def stripe_connect_return(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_director_or_admin),
):
    """
    Callback post-onboarding Express.
    Verifica que la cuenta está completamente configurada.
    Retorna el estado para que el frontend muestre el mensaje correcto.
    """
    tenant = await _get_tenant_for_owner(user, db)

    if not tenant.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay cuenta Stripe asociada. Inicia el proceso desde el panel.",
        )

    # Verificar estado real de la cuenta en Stripe
    try:
        account = stripe.Account.retrieve(tenant.stripe_account_id)
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al verificar cuenta Stripe: {str(e)}",
        )

    details_submitted = account.get("details_submitted", False)
    charges_enabled   = account.get("charges_enabled", False)

    return {
        "account_id":        tenant.stripe_account_id,
        "details_submitted": details_submitted,
        "charges_enabled":   charges_enabled,
        "ready":             details_submitted and charges_enabled,
        "message": (
            "Tu cuenta está lista para recibir pagos."
            if details_submitted and charges_enabled
            else "Tu cuenta aún está en proceso de verificación. "
                 "Stripe te enviará un email cuando esté activa."
        ),
    }


# ── GET /tenants/connect-stripe/refresh ─────────────────────────────────────

@router.get("/connect-stripe/refresh")
async def stripe_connect_refresh(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_director_or_admin),
):
    """
    Regenera el link de onboarding si expiró (AccountLinks duran ~5 min).
    Stripe redirige aquí cuando el link del director ya caducó.
    """
    tenant = await _get_tenant_for_owner(user, db)

    if not tenant.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay cuenta Stripe. Inicia el proceso desde el panel.",
        )

    try:
        onboarding_url = _build_onboarding_url(
            account_id=tenant.stripe_account_id,
            tenant_slug=tenant.slug,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al regenerar link: {str(e)}",
        )

    return StripeConnectResponse(
        onboarding_url=onboarding_url,
        account_id=tenant.stripe_account_id,
    )