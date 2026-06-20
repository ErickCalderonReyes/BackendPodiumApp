"""
routers/tickets.py
──────────────────
Endpoints de venta de boletos.

GET  /tickets/events?tenant_slug=mimx  → eventos activos con zonas y disponibilidad
POST /tickets/validate-code            → valida código de descuento (sin cobrar usos)
POST /tickets/create-session           → Stripe Session o confirmación directa (boleto gratis)

El webhook de checkout.session.completed se maneja en routers/payments.py.
La función _process_completed_ticket() vive en services/tickets.py y se importa
desde el webhook cuando metadata["payment_type"] == "ticket".
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db, get_current_user
from db_models import User
from schemas.tickets import (
    ValidateCodeRequest,
    ValidateCodeResponse,
    TicketCheckoutRequest,
    TicketCheckoutResponse,
)
from services.tickets import (
    get_events_for_tenant,
    validate_discount_code,
    create_ticket_checkout,
)
from schemas.tickets import PublicTicketCheckoutRequest
from services.tickets import create_public_ticket_checkout

router_tickets = APIRouter(prefix="/tickets", tags=["tickets"])


# ── GET /tickets/events ────────────────────────────────────────────────────

@router_tickets.get("/events")
async def list_events(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Lista eventos activos del tenant con zonas y disponibilidad.
    Público — no requiere autenticación.

    Ejemplo: GET /tickets/events?tenant_slug=mimx
    """
    return await get_events_for_tenant(tenant_slug, db)


# ── POST /tickets/validate-code ────────────────────────────────────────────

@router_tickets.post("/validate-code", response_model=ValidateCodeResponse)
async def validate_code(
    body: ValidateCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Valida un código de descuento y retorna el precio ajustado.
    No consume el código — solo previsualiza el descuento.
    Público — el usuario puede probar el código antes de hacer login.
    """
    result = await validate_discount_code(
        tenant_slug = body.tenant_slug,
        code        = body.code,
        zone_id     = body.zone_id,
        db          = db,
    )
    return ValidateCodeResponse(
        valid                = result["valid"],
        discount_type        = result.get("discount_type"),
        discount_value       = result.get("discount_value"),
        original_price_cents = result.get("original_price_cents", 0),
        final_price_cents    = result.get("final_price_cents", 0),
        message              = result["message"],
    )


# ── POST /tickets/create-session ───────────────────────────────────────────

@router_tickets.post(
    "/create-session",
    response_model=TicketCheckoutResponse,
    status_code=status.HTTP_200_OK,
)
async def create_session(
    body: TicketCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crea una Stripe Checkout Session para compra de boleto.

    Si el código de descuento resulta en precio $0 (boleto gratis):
    - Confirma el TicketOrder directamente sin pasar por Stripe.
    - checkout_url será null; el frontend redirige a /boletos/exito.

    Si hay precio > $0:
    - Retorna checkout_url de Stripe.
    - El webhook confirma el TicketOrder al completarse el pago.

    Requiere autenticación (JWT válido).
    """
    result = await create_ticket_checkout(
        zone_id       = body.zone_id,
        tenant_slug   = body.tenant_slug,
        discount_code = body.discount_code,
        user          = current_user,
        db            = db,
    )
    return TicketCheckoutResponse(**result)


# ════════════════════════════════════════════════════════════════════════════
# PARCHE REQUERIDO en routers/payments.py
# ════════════════════════════════════════════════════════════════════════════
#
# Reemplazar en el webhook handler de payments.py el bloque:
#
#   session_dict = json.loads(str(session_obj))
#   background_tasks.add_task(_process_completed_payment, session_dict)
#
# Por:
#
#   session_dict = json.loads(str(session_obj))
#
#   payment_type = session_dict.get("metadata", {}).get("payment_type", "vote")
#   if payment_type == "ticket":
#       from services.tickets import _process_completed_ticket
#       background_tasks.add_task(_process_completed_ticket, session_dict)
#   else:
#       background_tasks.add_task(_process_completed_payment, session_dict)
#
# ════════════════════════════════════════════════════════════════════════════
#
# PARCHE REQUERIDO en main.py
# ════════════════════════════════════════════════════════════════════════════
#
# Agregar junto a los demás routers:
#
#   from routers.tickets import router_tickets
#   app.include_router(router_tickets)
#
# ════════════════════════════════════════════════════════════════════════════
@router_tickets.post("/checkout", response_model=TicketCheckoutResponse)
async def public_checkout(
    body: PublicTicketCheckoutRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Checkout público de boletos como invitado (sin cuenta).
    Devuelve checkout_url de Stripe. El webhook confirma la orden y manda correo.
    """
    result = await create_public_ticket_checkout(
        zone_id     = body.zone_id,
        quantity    = body.quantity,
        tenant_slug = body.tenant_slug,
        guest_name  = body.guest_name,
        guest_email = body.guest_email,
        guest_phone = body.guest_phone,
        db          = db,
    )
    return TicketCheckoutResponse(**result)