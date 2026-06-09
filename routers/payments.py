# ════════════════════════════════════════════════════════
# routers/payments.py
# ════════════════════════════════════════════════════════
from fastapi import APIRouter, Depends, BackgroundTasks, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db, get_current_user
from core.guards import require_pro
from schemas.payments import CheckoutRequest, CheckoutResponse
from services import payments as pay_svc
from db_models import User, Tenant

router_payments = APIRouter(prefix="/payments", tags=["payments"])


@router_payments.post("/create-session", response_model=CheckoutResponse)
async def create_checkout(
    body:   CheckoutRequest,
    db:     AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(require_pro),
    user:   User   = Depends(get_current_user),
):
    """
    Crea Stripe Checkout con candidato fijo y split automático al director.
    Requiere plan Pro + Stripe Connect conectado.
    """
    result = await pay_svc.create_checkout_session(
        package_id  = body.package_id,
        candidate_id= body.candidate_id,
        tenant      = tenant,
        user_id     = user.id,
        db          = db,
    )
    return result


@router_payments.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request:          Request,
    background_tasks: BackgroundTasks,
    db:               AsyncSession = Depends(get_db),
):
    """
    Recibe eventos de Stripe. NO requiere JWT — Stripe firma cada request.
    Siempre retorna 200 para que Stripe no reintente.
    La acreditación de votos ocurre en BackgroundTask (no bloquea la respuesta).
    """
    return await pay_svc.handle_webhook(request, background_tasks, db)