"""
services/tickets.py
───────────────────
Lógica de negocio para venta de boletos.

Flujo pagado:
  1. validate_discount_code()  → precio final con descuento aplicado
  2. create_ticket_checkout()  → Stripe Session con price_data dinámico (sin stripe_price_id fijo)
  3. Webhook en routers/payments.py detecta payment_type="ticket"
     → llama _process_completed_ticket() como background task
     → crea TicketOrder (idempotencia por stripe_payment_intent_id UNIQUE)
     → incrementa current_uses y desactiva código gemelo

Flujo gratis (discount_type=free):
  - create_ticket_checkout() confirma el TicketOrder directamente
  - stripe_payment_intent_id = "FREE-{uuid4().hex}"
  - No pasa por Stripe Checkout

Exclusividad mutua de códigos en tarjeta de bienvenida:
  - PLATA-A3K9 y ORO-A3K9 comparten el mismo uid "A3K9"
  - Al usar uno, _apply_code_and_deactivate_twin() desactiva el otro
  - Búsqueda: DiscountCode.code LIKE '%-A3K9' AND id != usado
"""
from uuid import uuid4
from datetime import timezone, datetime
from typing import Optional

import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError

from config import settings
from core.plans import commission_amount
from db_models import (
    Event, TicketZone, TicketOrder, DiscountCode,
    Tenant, User, DiscountType,
)
from database import AsyncSessionLocal

stripe.api_key = settings.STRIPE_SECRET_KEY

# Prefijo de folio por zona (consistente con issue_hotel_tickets.py)
#   1 = Final Plata · 2 = Final Oro · 7 = Preliminar General
_FOLIO_PREFIX = {1: "FP", 2: "FO", 7: "PRE"}


async def _assign_folio_ticket(order: "TicketOrder", db: AsyncSession):
    """
    Asigna folio secuencial por zona (FP-001, FO-001, PRE-001) usando SAVEPOINT,
    de modo que una colisión solo reintenta el folio sin perder la orden ya insertada.
    """
    prefix = _FOLIO_PREFIX.get(order.zone_id, "GEN")
    for _ in range(6):
        count = await db.scalar(
            select(func.count(TicketOrder.id)).where(
                TicketOrder.zone_id == order.zone_id,
                TicketOrder.folio.is_not(None),
            )
        ) or 0
        candidate = f"{prefix}-{count + 1:03d}"
        try:
            async with db.begin_nested():   # SAVEPOINT
                order.folio = candidate
                await db.flush()
            return candidate
        except IntegrityError:
            order.folio = None
            continue
    return None


# ── GET /tickets/events ────────────────────────────────────────────────────

async def get_events_for_tenant(tenant_slug: str, db: AsyncSession) -> list:
    """
    Retorna eventos activos con sus zonas y disponibilidad calculada.
    La disponibilidad (sold) se calcula en tiempo real desde ticket_orders.
    """
    events_result = await db.execute(
        select(Event)
        .where(Event.tenant_slug == tenant_slug)
        .order_by(Event.season_year.desc(), Event.id.asc())
    )
    events = events_result.scalars().all()

    output = []
    for ev in events:
        zones_result = await db.execute(
            select(TicketZone)
            .where(TicketZone.event_id == ev.id, TicketZone.is_active == True)
            .order_by(TicketZone.sort_order)
        )
        zones = zones_result.scalars().all()

        zones_out = []
        for z in zones:
            sold = await db.scalar(
                select(func.coalesce(func.sum(TicketOrder.quantity), 0)).where(
                    TicketOrder.zone_id == z.id,
                    TicketOrder.status == "completed",
                )
            ) or 0
            zones_out.append({
                "id":          z.id,
                "name":        z.name,
                "price_cents": z.price_cents,
                "capacity":    z.capacity,
                "sold":        sold,
                "sort_order":  z.sort_order,
            })

        output.append({
            "id":          ev.id,
            "name":        ev.name,
            "event_date":  ev.event_date,
            "season_year": ev.season_year,
            "is_active":   ev.is_active,
            "zones":       zones_out,
        })

    return output


# ── POST /tickets/validate-code ────────────────────────────────────────────

async def validate_discount_code(
    tenant_slug: str,
    code:        str,
    zone_id:     int,
    db:          AsyncSession,
) -> dict:
    """
    Valida un código de descuento y retorna el precio final.
    NO incrementa current_uses — eso ocurre solo al confirmar el pago en el webhook.
    """
    _invalid = lambda msg: {
        "valid": False, "message": msg,
        "original_price_cents": 0, "final_price_cents": 0,
    }

    dc_result = await db.execute(
        select(DiscountCode).where(
            DiscountCode.tenant_slug == tenant_slug,
            DiscountCode.code        == code.upper().strip(),
            DiscountCode.is_active   == True,
        )
    )
    dc = dc_result.scalar_one_or_none()
    if not dc:
        return _invalid("Código no válido o ya utilizado.")

    # Verificar max_uses
    if dc.max_uses is not None and dc.current_uses >= dc.max_uses:
        return _invalid("Este código ya fue utilizado.")

    # Verificar expiración
    if dc.valid_until and dc.valid_until < datetime.now(timezone.utc):
        return _invalid("Este código ha expirado.")

    # Verificar que aplica a esta zona (None = todas las zonas del tenant)
    if dc.applies_to_zone_id is not None and dc.applies_to_zone_id != zone_id:
        return _invalid("Este código no aplica para la zona seleccionada.")

    # Precio base de la zona
    zone_result = await db.execute(
        select(TicketZone).where(TicketZone.id == zone_id, TicketZone.is_active == True)
    )
    zone = zone_result.scalar_one_or_none()
    if not zone:
        return _invalid("Zona no encontrada.")

    # Calcular precio final
    if dc.discount_type == DiscountType.free:
        final_price = 0
    elif dc.discount_type == DiscountType.fixed_amount:
        final_price = max(0, zone.price_cents - (dc.discount_value or 0))
    elif dc.discount_type == DiscountType.percent:
        final_price = int(zone.price_cents * (1 - (dc.discount_value or 0) / 100))
    else:
        final_price = zone.price_cents

    return {
        "valid":                 True,
        "discount_type":         dc.discount_type.value,
        "discount_value":        dc.discount_value,
        "discount_code_id":      dc.id,
        "original_price_cents":  zone.price_cents,
        "final_price_cents":     final_price,
        "message":               "Código aplicado correctamente.",
    }


# ── POST /tickets/create-session ───────────────────────────────────────────

async def create_ticket_checkout(
    zone_id:       int,
    tenant_slug:   str,
    discount_code: Optional[str],
    user:          User,
    db:            AsyncSession,
) -> dict:
    """
    Crea una Stripe Checkout Session para compra de boleto.
    Si el precio final es $0 (boleto gratis), confirma directamente sin Stripe.
    """

    # ── Zona + evento activos ──────────────────────────────────────────────
    row_result = await db.execute(
        select(TicketZone, Event)
        .join(Event, TicketZone.event_id == Event.id)
        .where(
            TicketZone.id        == zone_id,
            TicketZone.is_active == True,
            Event.is_active      == True,
            Event.tenant_slug    == tenant_slug,
        )
    )
    row = row_result.one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Zona no encontrada o ventas cerradas para este certamen.",
        )
    zone, event = row

    # ── Verificar capacity ─────────────────────────────────────────────────
    if zone.capacity is not None:
        sold = await db.scalar(
            select(func.count(TicketOrder.id)).where(
                TicketOrder.zone_id == zone_id,
                TicketOrder.status  == "completed",
            )
        ) or 0
        if sold >= zone.capacity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta zona está agotada. Ponte en contacto con el organizador.",
            )

    # ── Tenant y Stripe Connect ────────────────────────────────────────────
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant or not tenant.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="El certamen no tiene pagos configurados.",
        )

    # ── Descuento ──────────────────────────────────────────────────────────
    final_price      = zone.price_cents
    discount_code_id = None

    if discount_code:
        validation = await validate_discount_code(tenant_slug, discount_code, zone_id, db)
        if not validation["valid"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=validation["message"])
        final_price      = validation["final_price_cents"]
        discount_code_id = validation["discount_code_id"]

    # ── Boleto GRATIS — confirmación directa, sin Stripe ──────────────────
    if final_price == 0:
        synthetic_id = f"FREE-{uuid4().hex}"
        order = TicketOrder(
            user_id                  = user.id,
            zone_id                  = zone_id,
            tenant_slug              = tenant_slug,
            quantity                 = 1,
            amount_cents             = 0,
            discount_code_id         = discount_code_id,
            stripe_payment_intent_id = synthetic_id,
            season_year              = event.season_year,
            status                   = "completed",
        )
        db.add(order)

        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Este boleto ya fue generado.")

        if discount_code_id:
            await _apply_code_and_deactivate_twin(discount_code_id, tenant_slug, db)

        await db.commit()
        return {
            "checkout_url": None,
            "session_id":   synthetic_id,
            "amount_cents": 0,
            "is_free":      True,
            "zone_name":    zone.name,
        }

    # ── Boleto de PAGO — Stripe Checkout Session ───────────────────────────
    # Usa price_data dinámico (no stripe_price_id fijo) porque el precio
    # varía según descuentos aplicados.
    fee_cents = commission_amount(final_price)

    try:
        session = stripe.checkout.Session.create(
            mode     = "payment",
            currency = "mxn",
            line_items = [{
                "price_data": {
                    "currency":     "mxn",
                    "unit_amount":  final_price,
                    "product_data": {
                        "name": f"{zone.name} — {event.name}",
                    },
                },
                "quantity": 1,
            }],
            payment_intent_data = {
                "application_fee_amount": fee_cents,
                "transfer_data":          {"destination": tenant.stripe_account_id},
            },
            # payment_type="ticket" distingue este flujo del de votos en el webhook
            metadata = {
                "payment_type":     "ticket",
                "user_id":          str(user.id),
                "zone_id":          str(zone_id),
                "zone_name":        zone.name,
                "tenant_slug":      tenant_slug,
                "season_year":      str(event.season_year),
                "discount_code_id": str(discount_code_id) if discount_code_id else "",
                "discount_code":    discount_code or "",
            },
            success_url = f"{settings.FRONTEND_URL}/boletos/exito?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url  = f"{settings.FRONTEND_URL}/boletos/cancelado",
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al crear la sesión de pago: {str(e)}",
        )

    return {
        "checkout_url": session.url,
        "session_id":   session.id,
        "amount_cents": final_price,
        "is_free":      False,
        "zone_name":    zone.name,
    }


# ── Webhook background task ────────────────────────────────────────────────

async def _process_completed_ticket(session_data: dict) -> None:
    """
    Webhook de pago de boleto público. Crea UNA orden (quantity=N) con folio
    y datos de invitado. Idempotente por stripe_payment_intent_id UNIQUE.
    Luego manda el correo de confirmación.
    """
    meta = session_data.get("metadata", {})
    try:
        zone_id           = int(meta["zone_id"])
        tenant_slug       = meta["tenant_slug"]
        season_year       = int(meta["season_year"])
        quantity          = int(meta.get("quantity", "1"))
        payment_intent_id = session_data["payment_intent"]
        amount_total      = session_data.get("amount_total", 0)
    except (KeyError, ValueError):
        return

    guest_name  = meta.get("guest_name")  or None
    guest_email = meta.get("guest_email") or None
    guest_phone = meta.get("guest_phone") or None

    folio_val = None
    async with AsyncSessionLocal() as db:
        order = TicketOrder(
            user_id                  = None,
            zone_id                  = zone_id,
            tenant_slug              = tenant_slug,
            quantity                 = quantity,
            amount_cents             = amount_total,
            stripe_payment_intent_id = payment_intent_id,
            season_year              = season_year,
            status                   = "completed",
            guest_name               = guest_name,
            guest_email              = guest_email,
            guest_phone              = guest_phone,
            source                   = "public",
        )
        db.add(order)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return  # webhook duplicado — ya procesado

        folio_val = await _assign_folio_ticket(order, db)

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            return

    # Correo de confirmación (fuera de la transacción)
    if guest_email:
        try:
            from services.email import send_public_ticket_confirmation
            async with AsyncSessionLocal() as db2:
                ze = (await db2.execute(
                    select(TicketZone, Event)
                    .join(Event, TicketZone.event_id == Event.id)
                    .where(TicketZone.id == zone_id)
                )).one_or_none()
            zone_name  = ze[0].name if ze else "Zona"
            event_name = ze[1].name if ze else "Evento"
            send_public_ticket_confirmation(
                to=guest_email, name=guest_name or "asistente",
                event_name=event_name, zone_name=zone_name,
                quantity=quantity, folio=folio_val, amount_cents=amount_total,
            )
            print(f"[webhook-ticket] OK orden {folio_val} x{quantity} | PI: {payment_intent_id}")
        except Exception as e:
            print(f"[webhook-ticket] orden creada pero correo falló: {e}")


# ── Helper compartido: uso de código + gemelo ──────────────────────────────

async def _apply_code_and_deactivate_twin(
    discount_code_id: int,
    tenant_slug:      str,
    db:               AsyncSession,
) -> None:
    """
    Incrementa current_uses del código usado y desactiva su gemelo en la
    misma tarjeta de bienvenida.

    Los dos códigos de una tarjeta comparten el mismo sufijo uid:
      PLATA-A3K9  →  ORO-A3K9   (y viceversa)
    Al usar uno, el otro queda is_active=False.

    Para códigos de director (DIR-SONORA-7F2B) no existe gemelo —
    el UPDATE afecta 0 filas y no produce error.
    """
    dc_result = await db.execute(select(DiscountCode).where(DiscountCode.id == discount_code_id))
    dc = dc_result.scalar_one_or_none()
    if not dc:
        return

    dc.current_uses += 1
    if dc.max_uses is not None and dc.current_uses >= dc.max_uses:
        dc.is_active = False

    # Sufijo compartido entre los dos códigos de la tarjeta
    uid_suffix = dc.code.rsplit("-", 1)[-1]   # "A3K9" de "PLATA-A3K9"

    await db.execute(
        update(DiscountCode)
        .where(
            DiscountCode.tenant_slug == tenant_slug,
            DiscountCode.code.like(f"%-{uid_suffix}"),
            DiscountCode.id          != dc.id,
        )
        .values(is_active=False)
    )

async def create_public_ticket_checkout(
    zone_id:     int,
    quantity:    int,
    tenant_slug: str,
    guest_name:  str,
    guest_email: str,
    guest_phone: Optional[str],
    db:          AsyncSession,
) -> dict:
    """
    Checkout público como invitado (sin cuenta). Una orden = un pago = N lugares.
    Siempre pasa por Stripe (el público no usa códigos).
    """
    if quantity < 1 or quantity > 10:
        raise HTTPException(status_code=400, detail="Cantidad inválida (1 a 10).")

    row = (await db.execute(
        select(TicketZone, Event)
        .join(Event, TicketZone.event_id == Event.id)
        .where(
            TicketZone.id        == zone_id,
            TicketZone.is_active == True,
            Event.is_active      == True,
            Event.tenant_slug    == tenant_slug,
        )
    )).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Zona no encontrada o ventas cerradas.")
    zone, event = row

    # Aforo: suma de cantidades, no conteo de órdenes
    if zone.capacity is not None:
        sold = await db.scalar(
            select(func.coalesce(func.sum(TicketOrder.quantity), 0)).where(
                TicketOrder.zone_id == zone_id,
                TicketOrder.status  == "completed",
            )
        ) or 0
        if sold + quantity > zone.capacity:
            raise HTTPException(
                status_code=409,
                detail="Lugares digitales agotados. Contacta al organizador.",
            )

    tenant = (await db.execute(
        select(Tenant).where(Tenant.slug == tenant_slug)
    )).scalar_one_or_none()
    if not tenant or not tenant.stripe_account_id:
        raise HTTPException(status_code=402, detail="El certamen no tiene pagos configurados.")

    unit  = zone.price_cents
    total = unit * quantity
    fee   = commission_amount(total)

    try:
        session = stripe.checkout.Session.create(
            mode="payment", currency="mxn",
            line_items=[{
                "price_data": {
                    "currency":     "mxn",
                    "unit_amount":  unit,
                    "product_data": {"name": f"{zone.name} — {event.name}"},
                },
                "quantity": quantity,
            }],
            payment_intent_data={
                "application_fee_amount": fee,
                "transfer_data": {"destination": tenant.stripe_account_id},
            },
            customer_email=guest_email,
            metadata={
                "payment_type": "ticket",
                "zone_id":      str(zone_id),
                "tenant_slug":  tenant_slug,
                "season_year":  str(event.season_year),
                "quantity":     str(quantity),
                "guest_name":   guest_name,
                "guest_email":  guest_email,
                "guest_phone":  guest_phone or "",
            },
            success_url=f"{settings.FRONTEND_URL}/boletos/exito?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.FRONTEND_URL}/boletos/cancelado",
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Error al crear la sesión de pago: {str(e)}")

    return {
        "checkout_url": session.url,
        "session_id":   session.id,
        "amount_cents": total,
        "is_free":      False,
        "zone_name":    zone.name,
        "folio":        None,
    }