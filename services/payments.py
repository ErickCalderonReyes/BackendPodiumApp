import stripe
from fastapi import HTTPException, Request, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db_models import Vote, Transaction, Tenant, VotePackage, Candidate
from services.packages import get_packages_for_tenant
from core.plans import commission_amount
from config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY


async def create_checkout_session(
    package_id:   int,
    candidate_id: int,
    tenant:       Tenant,
    user_id:      int,
    db:           AsyncSession,
) -> dict:
    """
    Crea una Stripe Checkout Session con split automático via Connect.

    El candidato se fija aquí — viaja en metadata para que el webhook
    sepa a quién acreditar los votos sin ambigüedad.
    """
    # ── Validar que el tenant tenga cuenta Stripe Connect ────────────────
    if not tenant.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code":           "STRIPE_NOT_CONNECTED",
                "message":        "Este certamen aún no ha conectado su cuenta de pagos.",
                "connect_url":    "/dashboard/stripe-connect",
            },
        )

    # ── Obtener el paquete activo del tenant ──────────────────────────────
    packages = await get_packages_for_tenant(tenant, db)
    pkg = next((p for p in packages if p.id == package_id and p.is_active), None)
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paquete no encontrado o no disponible para este certamen",
        )

    # ── Validar que el candidato existe y pertenece a este tenant ─────────
    result = await db.execute(
        select(Candidate).where(
            Candidate.id          == candidate_id,
            Candidate.tenant_slug == tenant.slug,
            Candidate.season_year == tenant.season_year,
            Candidate.is_active   == True,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidato no encontrado o no activo en este certamen",
        )

    # ── Calcular comisión Podium ──────────────────────────────────────────
    fee = commission_amount(pkg.price_cents)   # 12% en centavos

    # ── Crear Checkout Session ────────────────────────────────────────────
    base_url = settings.FRONTEND_URL
    session = stripe.checkout.Session.create(
        mode            = "payment",
        currency        = "mxn",
        line_items      = [{
            "price":    pkg.stripe_price_id,
            "quantity": 1,
        }],
        payment_intent_data = {
            "application_fee_amount": fee,
            "transfer_data":          {"destination": tenant.stripe_account_id},
        },
        metadata = {
            "user_id":      str(user_id),
            "package_id":   str(pkg.id),
            "candidate_id": str(candidate_id),
            "tenant_id":    str(tenant.id),
            "tenant_slug":  tenant.slug,
            "season_year":  str(tenant.season_year),
            "vote_count":   str(pkg.vote_count),
        },
        success_url = f"{base_url}/vote/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url  = f"{base_url}/vote/cancel",
    )

    return {
        "checkout_url": session.url,
        "session_id":   session.id,
    }


# ── Webhook ────────────────────────────────────────────────────────────────

async def handle_webhook(
    request:          Request,
    background_tasks: BackgroundTasks,
    db:               AsyncSession,
) -> dict:
    payload   = await request.body()
    sig_header= request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Firma de webhook inválida",
        )

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        # ← convierte a dict y NO pasa db
        background_tasks.add_task(_process_successful_payment, session.to_dict())

    return {"received": True}


async def _process_successful_payment(session: dict) -> None:
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        meta = session.get("metadata", {})
        try:
            user_id           = int(meta["user_id"])
            package_id        = int(meta["package_id"])
            candidate_id      = int(meta["candidate_id"])
            tenant_slug       = meta["tenant_slug"]
            season_year       = int(meta["season_year"])
            vote_count        = int(meta["vote_count"])
            amount_cents      = session["amount_total"]
            payment_intent_id = session["payment_intent"]
        except (KeyError, ValueError):
            print(f"[webhook] metadata inválida en session {session.get('id')}")
            return

        transaction = Transaction(
            user_id                  = user_id,
            package_id               = package_id,
            candidate_id             = candidate_id,
            stripe_payment_intent_id = payment_intent_id,
            amount_cents             = amount_cents,
            votes_credited           = vote_count,
            season_year              = season_year,
            tenant_slug              = tenant_slug,
            status                   = "completed",
        )
        db.add(transaction)

        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            print(f"[webhook] duplicado ignorado: {payment_intent_id}")
            return

        votes = [
            Vote(
                user_id      = user_id,
                candidate_id = candidate_id,
                season_year  = season_year,
                tenant_slug  = tenant_slug,
                is_free      = False,
            )
            for _ in range(vote_count)
        ]
        db.add_all(votes)
        await db.commit()
        print(f"[webhook] ✅ {vote_count} votos → candidato {candidate_id} ({payment_intent_id})")
