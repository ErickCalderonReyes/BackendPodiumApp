import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db_models import VotePackage, Tenant
from schemas.packages import VotePackageCreate, VotePackagePatch, VotePackageOverrideCreate
from config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY


# ── Helpers privados ───────────────────────────────────────────────────────

async def _create_stripe_price(name: str, price_cents: int) -> str:
    """Crea un Product + Price en Stripe y retorna el price_id."""
    product = stripe.Product.create(name=f"Podium — {name}")
    price = stripe.Price.create(
        product    = product.id,
        unit_amount= price_cents,
        currency   = "mxn",
    )
    return price.id


async def _deactivate_stripe_price(price_id: str) -> None:
    """Archiva el Price en Stripe cuando se actualiza el precio."""
    if price_id:
        stripe.Price.modify(price_id, active=False)


async def _get_package_or_404(package_id: int, db: AsyncSession) -> VotePackage:
    result = await db.execute(
        select(VotePackage).where(VotePackage.id == package_id)
    )
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paquete {package_id} no encontrado",
        )
    return pkg


# ── Lectura pública ────────────────────────────────────────────────────────

async def get_packages_for_tenant(
    tenant: Tenant,
    db: AsyncSession,
) -> list[VotePackage]:
    """
    Retorna los paquetes activos para un tenant.
    Lógica: paquetes propios del tenant → si no tiene, fallback a plantillas nacionales (tenant_id IS NULL).
    """
    # Paquetes propios del director
    result = await db.execute(
        select(VotePackage).where(
            VotePackage.tenant_id == tenant.id,
            VotePackage.is_active == True,
        ).order_by(VotePackage.sort_order)
    )
    own_packages = result.scalars().all()

    if own_packages:
        return list(own_packages)

    # Fallback: plantillas nacionales
    result = await db.execute(
        select(VotePackage).where(
            VotePackage.tenant_id == None,
            VotePackage.is_active == True,
        ).order_by(VotePackage.sort_order)
    )
    return list(result.scalars().all())


# ── Admin: plantillas nacionales ───────────────────────────────────────────

async def create_national_package(
    data: VotePackageCreate,
    db: AsyncSession,
) -> VotePackage:
    """national_admin crea una plantilla nacional (tenant_id=NULL)."""
    price_id = await _create_stripe_price(data.name, data.price_cents)

    pkg = VotePackage(
        tenant_id      = None,
        name           = data.name,
        price_cents    = data.price_cents,
        vote_count     = data.vote_count,
        stripe_price_id= price_id,
        sort_order     = data.sort_order,
        is_active      = True,
    )
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return pkg


async def patch_package(
    package_id: int,
    data: VotePackagePatch,
    db: AsyncSession,
) -> VotePackage:
    """
    Edita un paquete. Si cambia price_cents → archiva el Price viejo en Stripe
    y crea uno nuevo.
    """
    pkg = await _get_package_or_404(package_id, db)
    updates = data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se enviaron campos para actualizar",
        )

    if "price_cents" in updates and updates["price_cents"] != pkg.price_cents:
        # Archivar Price viejo, crear nuevo
        await _deactivate_stripe_price(pkg.stripe_price_id)
        new_price_id = await _create_stripe_price(
            updates.get("name", pkg.name),
            updates["price_cents"],
        )
        updates["stripe_price_id"] = new_price_id

    for field, value in updates.items():
        setattr(pkg, field, value)

    await db.commit()
    await db.refresh(pkg)
    return pkg


# ── Director Pro: override por tenant ─────────────────────────────────────

async def create_tenant_override(
    data: VotePackageOverrideCreate,
    tenant: Tenant,
    db: AsyncSession,
) -> VotePackage:
    """
    El director Pro crea su propio paquete basado en una plantilla nacional,
    con precio personalizado. Se crea un Price propio en Stripe.
    """
    base = await _get_package_or_404(data.base_package_id, db)

    # El paquete base debe ser una plantilla nacional
    if base.tenant_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo puedes crear overrides de plantillas nacionales (tenant_id=NULL)",
        )

    price_id = await _create_stripe_price(
        f"{base.name} — {tenant.slug}", data.price_cents
    )

    override = VotePackage(
        tenant_id      = tenant.id,
        name           = base.name,
        price_cents    = data.price_cents,
        vote_count     = base.vote_count,
        stripe_price_id= price_id,
        sort_order     = base.sort_order,
        is_active      = True,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return override
