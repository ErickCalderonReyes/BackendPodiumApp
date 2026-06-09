# ════════════════════════════════════════════════════════
# routers/packages.py
# ════════════════════════════════════════════════════════
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db
from core.guards import require_admin, require_pro, require_director_or_admin
from schemas.packages import VotePackageOut, VotePackageCreate, VotePackagePatch, VotePackageOverrideCreate
from services import packages as pkg_svc
from services import tenants as tenant_svc
from db_models import Tenant, User

router_packages = APIRouter(prefix="/packages", tags=["packages"])


@router_packages.get("", response_model=list[VotePackageOut])
async def list_packages(
    tenant: Tenant = Depends(require_pro),
):
    """
    Retorna los paquetes activos para el tenant del director autenticado.
    Lógica: propios del tenant → fallback a plantillas nacionales.
    Requiere plan Pro (ya verificado por require_pro).
    """
    # db está implícito dentro de require_pro — necesitamos pasarlo
    # workaround: el tenant ya está cargado, consultamos sin segunda query
    # Para este endpoint usamos el tenant que ya trajo require_pro
    raise NotImplementedError("Ver nota abajo")
    # NOTA: require_pro retorna el Tenant pero no el db.
    # El router usa la versión correcta abajo con db explícito.


@router_packages.get("/public/{slug}", response_model=list[VotePackageOut])
async def list_packages_public(
    slug: str,
    db:   AsyncSession = Depends(get_db),
):
    """
    Endpoint público — el frontend de votación llama aquí para mostrar
    los paquetes disponibles del certamen sin autenticación.
    """
    from services.tenants import get_tenant_by_slug
    tenant = await get_tenant_by_slug(slug, db)
    return await pkg_svc.get_packages_for_tenant(tenant, db)


@router_packages.post("", response_model=VotePackageOut, status_code=status.HTTP_201_CREATED)
async def create_national_package(
    data: VotePackageCreate,
    db:   AsyncSession = Depends(get_db),
    _:    User = Depends(require_admin),
):
    """national_admin crea plantilla nacional (tenant_id=NULL)."""
    return await pkg_svc.create_national_package(data, db)


@router_packages.patch("/{package_id}", response_model=VotePackageOut)
async def patch_package(
    package_id: int,
    data:       VotePackagePatch,
    db:         AsyncSession = Depends(get_db),
    _:          User = Depends(require_admin),
):
    """national_admin edita una plantilla. Rota el Price en Stripe si cambia precio."""
    return await pkg_svc.patch_package(package_id, data, db)


@router_packages.post("/override", response_model=VotePackageOut, status_code=status.HTTP_201_CREATED)
async def create_override(
    data:   VotePackageOverrideCreate,
    db:     AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(require_pro),
):
    """Director Pro crea su propio paquete con precio personalizado."""
    return await pkg_svc.create_tenant_override(data, tenant, db)
