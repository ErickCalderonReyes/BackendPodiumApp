"""
routers/packages.py
───────────────────
CRUD de paquetes de votos con lógica de fallback por tenant.

Lógica de visibilidad:
  - tenant_id NULL  → plantilla nacional (solo admin puede crear/editar)
  - tenant_id = FK  → override del director Pro para su certamen

GET /packages?tenant_slug=mimx
  1. Busca paquetes activos donde tenant.slug == tenant_slug   (propios del director)
  2. Si hay al menos uno → los retorna
  3. Si no → fallback a plantillas nacionales (tenant_id IS NULL)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import stripe

from config import settings
from core.dependencies import get_db, get_current_user
from core.guards import require_admin, require_pro
from db_models import VotePackage, Tenant, User
from schemas.packages import (
    VotePackageOut,
    VotePackageCreate,
    VotePackagePatch,
    VotePackageOverrideCreate,
)

stripe.api_key = settings.STRIPE_SECRET_KEY

router_packages = APIRouter(prefix="/packages", tags=["packages"])


# ── Helpers ────────────────────────────────────────────────────────────────

async def _get_tenant_by_slug(slug: str, db: AsyncSession) -> Tenant:
    result = await db.execute(
        select(Tenant).where(Tenant.slug == slug, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certamen '{slug}' no encontrado o inactivo.",
        )
    return tenant


async def _get_package_or_404(package_id: int, db: AsyncSession) -> VotePackage:
    result = await db.execute(
        select(VotePackage).where(VotePackage.id == package_id)
    )
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paquete {package_id} no encontrado.",
        )
    return pkg


def _create_stripe_product_and_price(
    name: str,
    price_cents: int,
    tenant_slug: str | None = None,
) -> str:
    """Crea un Product + Price en Stripe y retorna el stripe_price_id."""
    metadata = {"tenant_slug": tenant_slug or "nacional"}
    product = stripe.Product.create(
        name=name,
        metadata=metadata,
    )
    price = stripe.Price.create(
        unit_amount=price_cents,
        currency="mxn",
        product=product.id,
        metadata=metadata,
    )
    return price.id


# ── GET /packages ───────────────────────────────────────────────────────────

@router_packages.get("", response_model=list[VotePackageOut])
async def list_packages(
    tenant_slug: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna los paquetes activos del certamen.
    Si el certamen tiene paquetes propios → los retorna.
    Si no → fallback a plantillas nacionales (tenant_id IS NULL).
    Si no se pasa tenant_slug → solo plantillas nacionales.
    """
    if tenant_slug:
        tenant = await _get_tenant_by_slug(tenant_slug, db)

        # Paquetes propios del tenant
        result = await db.execute(
            select(VotePackage)
            .where(
                VotePackage.tenant_id == tenant.id,
                VotePackage.is_active == True,
            )
            .order_by(VotePackage.sort_order)
        )
        packages = result.scalars().all()

        if packages:
            return packages

    # Fallback: plantillas nacionales
    result = await db.execute(
        select(VotePackage)
        .where(
            VotePackage.tenant_id == None,
            VotePackage.is_active == True,
        )
        .order_by(VotePackage.sort_order)
    )
    return result.scalars().all()


# ── POST /packages [admin] ──────────────────────────────────────────────────

@router_packages.post(
    "",
    response_model=VotePackageOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_package(
    body: VotePackageCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Crea una plantilla nacional (tenant_id NULL).
    Solo national_admin. Crea el Price en Stripe automáticamente.
    """
    stripe_price_id = _create_stripe_product_and_price(
        name=body.name,
        price_cents=body.price_cents,
        tenant_slug=None,
    )

    pkg = VotePackage(
        tenant_id=None,
        name=body.name,
        price_cents=body.price_cents,
        vote_count=body.vote_count,
        stripe_price_id=stripe_price_id,
        sort_order=body.sort_order,
        is_active=True,
    )
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return pkg


# ── POST /packages/override [director Pro] ──────────────────────────────────

@router_packages.post(
    "/override",
    response_model=VotePackageOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_package_override(
    body: VotePackageOverrideCreate,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(require_pro),
):
    """
    El director Pro crea un paquete con precio personalizado para su tenant.
    Hereda nombre y vote_count del paquete base nacional.
    Crea un Price nuevo en Stripe para el tenant.
    """
    base = await _get_package_or_404(body.base_package_id, db)
    if base.tenant_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede hacer override de plantillas nacionales (tenant_id NULL).",
        )

    # Verificar que no exista ya un override activo para este base_package en este tenant
    existing = await db.execute(
        select(VotePackage).where(
            VotePackage.tenant_id == tenant.id,
            VotePackage.name == base.name,
            VotePackage.is_active == True,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un paquete activo con nombre '{base.name}' para tu certamen. Usa PATCH para editarlo.",
        )

    stripe_price_id = _create_stripe_product_and_price(
        name=base.name,
        price_cents=body.price_cents,
        tenant_slug=tenant.slug,
    )

    override = VotePackage(
        tenant_id=tenant.id,
        name=base.name,
        price_cents=body.price_cents,
        vote_count=base.vote_count,
        stripe_price_id=stripe_price_id,
        sort_order=base.sort_order,
        is_active=True,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return override


# ── PATCH /packages/{package_id} ────────────────────────────────────────────

@router_packages.patch("/{package_id}", response_model=VotePackageOut)
async def update_package(
    package_id: int,
    body: VotePackagePatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Edita un paquete.
    - national_admin: puede editar cualquier paquete.
    - state_director Pro: solo sus paquetes propios (tenant_id == su tenant).
    Si cambia el precio → desactiva el Price viejo en Stripe y crea uno nuevo.
    """
    pkg = await _get_package_or_404(package_id, db)

    # Verificar permisos
    if user.role == "national_admin":
        pass  # puede todo
    elif user.role == "state_director":
        # Obtener su tenant para validar ownership
        result = await db.execute(
            select(Tenant).where(
                Tenant.owner_id == user.id,
                Tenant.is_active == True,
            )
        )
        tenant = result.scalar_one_or_none()
        if not tenant or pkg.tenant_id != tenant.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes editar los paquetes de tu propio certamen.",
            )
        if tenant.plan == "free":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PLAN_LIMIT",
                    "message": "Necesitas el plan Pro para editar paquetes.",
                    "upgrade_url": "/billing/upgrade",
                },
            )
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado.")

    price_changed = body.price_cents is not None and body.price_cents != pkg.price_cents

    # Aplicar cambios de campos
    if body.name is not None:
        pkg.name = body.name
    if body.vote_count is not None:
        pkg.vote_count = body.vote_count
    if body.sort_order is not None:
        pkg.sort_order = body.sort_order
    if body.is_active is not None:
        pkg.is_active = body.is_active

    # Si cambia el precio → rotar Price en Stripe
    if price_changed:
        # Desactivar el Price anterior (no se puede eliminar si ya fue usado)
        if pkg.stripe_price_id:
            try:
                stripe.Price.modify(pkg.stripe_price_id, active=False)
            except stripe.error.StripeError:
                pass  # No crítico — continuar con el nuevo Price

        # Determinar tenant_slug para metadata
        tenant_slug = None
        if pkg.tenant_id:
            t_result = await db.execute(select(Tenant).where(Tenant.id == pkg.tenant_id))
            t = t_result.scalar_one_or_none()
            tenant_slug = t.slug if t else None

        pkg.price_cents = body.price_cents
        pkg.stripe_price_id = _create_stripe_product_and_price(
            name=pkg.name,
            price_cents=body.price_cents,
            tenant_slug=tenant_slug,
        )

    await db.commit()
    await db.refresh(pkg)
    return pkg


# ── DELETE lógico: PATCH is_active=False ────────────────────────────────────
# No hay DELETE físico — los paquetes usados en transacciones históricas
# deben conservarse. Usar PATCH /packages/{id} con {"is_active": false}.