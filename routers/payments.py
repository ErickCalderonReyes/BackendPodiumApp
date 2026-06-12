"""
routers/payments.py
───────────────────
Checkout Session con split Stripe Connect + webhook idempotente.

Flujo:
  1. Frontend: usuario elige candidato → elige paquete
  2. POST /payments/create-session → retorna checkout_url
  3. Usuario paga en Stripe Checkout
  4. Stripe llama POST /payments/webhook con checkout.session.completed
  5. Webhook acredita votos en bulk con candidate_id fijo desde metadata
  6. Idempotencia: stripe_payment_intent_id UNIQUE en Transactions

Split automático en cada pago:
  - application_fee_amount = 12% del precio → queda en cuenta Podium
  - transfer_data.destination = tenant.stripe_account_id → va al director
  - Stripe cobra su fee sobre el total antes del split
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import stripe

from config import settings
from core.dependencies import get_db, get_current_user
from core.guards import check_paid_votes_enabled
from core.plans import commission_amount
from db_models import VotePackage, Vote, Transaction, Candidate, Tenant, User
from schemas.payments import CheckoutRequest, CheckoutResponse
from database import AsyncSessionLocal
stripe.api_key = settings.STRIPE_SECRET_KEY

router_payments = APIRouter(prefix="/payments", tags=["payments"])


# ── POST /payments/create-session ───────────────────────────────────────────

@router_payments.post(
    "/create-session",
    response_model=CheckoutResponse,
)
async def create_checkout_session(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(check_paid_votes_enabled),
):
    """
    Crea una Stripe Checkout Session con split automático al director.

    Requisitos:
    - El usuario debe estar autenticado (JWT válido).
    - El tenant debe tener plan Pro y stripe_account_id configurado.
    - El paquete debe ser válido y activo.
    - El candidato debe existir y estar activo en este tenant.

    El candidate_id viaja en metadata → el webhook lo usa para acreditar votos.
    """

    # Validar que el tenant tiene Stripe Connect configurado
    if not tenant.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "STRIPE_NOT_CONNECTED",
                "message": "El director aún no ha conectado su cuenta de pagos. "
                           "Ve al panel y completa el proceso de Stripe Connect.",
            },
        )

    # Validar paquete
    pkg_result = await db.execute(
        select(VotePackage).where(
            VotePackage.id == body.package_id,
            VotePackage.is_active == True,
        )
    )
    pkg = pkg_result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paquete {body.package_id} no encontrado o inactivo.",
        )

    # Validar que el paquete pertenece al tenant (propio o plantilla nacional)
    if pkg.tenant_id is not None and pkg.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El paquete no corresponde a este certamen.",
        )

    # Validar candidato
    cand_result = await db.execute(
        select(Candidate).where(
            Candidate.id == body.candidate_id,
            Candidate.tenant_slug == tenant.slug,
            Candidate.season_year == tenant.season_year,
            Candidate.is_active == True,
        )
    )
    candidate = cand_result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidato {body.candidate_id} no encontrado o inactivo en este certamen.",
        )

    # Calcular fee de Podium (12%)
    fee_cents = commission_amount(pkg.price_cents)

    # Crear Checkout Session en Stripe
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price": pkg.stripe_price_id,
                    "quantity": 1,
                }
            ],
            # Split automático: 12% a Podium, resto al director
            payment_intent_data={
                "application_fee_amount": fee_cents,
                "transfer_data": {
                    "destination": tenant.stripe_account_id,
                },
            },
            # Metadata que el webhook necesita para acreditar votos
            metadata={
                "user_id":      str(current_user.id),
                "package_id":   str(pkg.id),
                "candidate_id": str(body.candidate_id),
                "tenant_slug":  tenant.slug,
                "season_year":  str(tenant.season_year),
                "vote_count":   str(pkg.vote_count),
            },
            success_url=f"{settings.FRONTEND_URL}/pago/exito?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.FRONTEND_URL}/pago/cancelado",
            currency="mxn",
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al crear la sesión de pago: {str(e)}",
        )

    return CheckoutResponse(
        checkout_url=session.url,
        session_id=session.id,
    )


# ── POST /payments/webhook ───────────────────────────────────────────────────

# ── En el endpoint webhook — NO pasar db ────────────────────────────────────
@router_payments.post("/webhook", status_code=200)
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    # db ya NO se inyecta aquí — el background task abre su propia sesión
):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Payload inválido.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Firma de webhook inválida.")

    if event["type"] != "checkout.session.completed":
        return {"received": True}

    session_data = event["data"]["object"]
    # Solo pasa session_data — la función abre su propia sesión de DB
    background_tasks.add_task(_process_completed_payment, session_data)

    return {"received": True}


# ── Función corregida — sesión propia, indentación limpia ───────────────────
async def _process_completed_payment(session_data: dict) -> None:
    """
    Procesa el pago completado:
    1. Extrae metadata de la sesión.
    2. Registra la Transaction (idempotencia por payment_intent UNIQUE).
    3. Inserta votos en bulk con candidate_id fijo.
    """
    async with AsyncSessionLocal() as db:
        meta = session_data.get("metadata", {})

        try:
            user_id      = int(meta["user_id"])
            package_id   = int(meta["package_id"])
            candidate_id = int(meta["candidate_id"])
            tenant_slug  = meta["tenant_slug"]
            season_year  = int(meta["season_year"])
            vote_count   = int(meta["vote_count"])
        except (KeyError, ValueError):
            return  # Metadata corrupta — no se puede procesar

        payment_intent_id = session_data.get("payment_intent")
        amount_total      = session_data.get("amount_total", 0)

        if not payment_intent_id:
            return

        transaction = Transaction(
            user_id=user_id,
            package_id=package_id,
            candidate_id=candidate_id,
            stripe_payment_intent_id=payment_intent_id,
            amount_cents=amount_total,
            votes_credited=vote_count,
            season_year=season_year,
            tenant_slug=tenant_slug,
            status="completed",
        )
        db.add(transaction)

        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return  # Webhook duplicado — ya procesado

        votes = [
            Vote(
                user_id=user_id,
                candidate_id=candidate_id,
                season_year=season_year,
                tenant_slug=tenant_slug,
                is_free=False,
            )
            for _ in range(vote_count)
        ]
        db.add_all(votes)

        try:
            await db.commit()
        except Exception:
            await db.rollback()