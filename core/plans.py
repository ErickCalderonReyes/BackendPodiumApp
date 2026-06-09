"""
core/plans.py
─────────────
Fuente única de verdad para los límites de cada plan.

Cambiar un límite = tocar este archivo, nada más.
Los guards en core/guards.py leen estas constantes.
"""

from typing import Optional


# ── Definición de límites por plan ─────────────────────────────────────────

PLAN_LIMITS: dict[str, dict] = {
    "free": {
        "max_candidates":  5,       # máximo de candidatos activos por season
        "max_sponsors":    3,       # máximo de patrocinadores activos
        "paid_votes":      False,   # bloquea Stripe Checkout + paquetes de pago
        "stripe_connect":  False,   # bloquea onboarding Express
        "custom_packages": False,   # bloquea override de paquetes por tenant
    },
    "pro": {
        "max_candidates":  None,    # None = sin límite
        "max_sponsors":    None,
        "paid_votes":      True,
        "stripe_connect":  True,
        "custom_packages": True,
    },
}

# Días de trial Pro automático al registrar un nuevo certamen
PRO_TRIAL_DAYS = 14

# Comisión que retiene Podium sobre cada voto de pago (12%)
PODIUM_COMMISSION_RATE = 0.12


# ── Helpers ────────────────────────────────────────────────────────────────

def get_limit(plan: str, key: str):
    """Retorna el límite para el plan y la clave dados.
    Lanza KeyError si el plan o la clave no existen.
    """
    return PLAN_LIMITS[plan][key]


def is_feature_enabled(plan: str, feature: str) -> bool:
    """True si el feature booleano está habilitado para el plan."""
    value = PLAN_LIMITS.get(plan, {}).get(feature)
    return bool(value)


def within_limit(plan: str, key: str, current_count: int) -> bool:
    """True si current_count no supera el límite del plan.
    Si el límite es None (sin límite), siempre retorna True.
    """
    limit: Optional[int] = PLAN_LIMITS.get(plan, {}).get(key)
    if limit is None:
        return True
    return current_count < limit


def commission_amount(price_cents: int) -> int:
    """Calcula el application_fee_amount para Stripe Connect.
    Retorna centavos (int) que Podium retiene de cada pago.

    Ejemplo: price_cents=50000 (MXN $500) → retorna 6000 (MXN $60)
    """
    return int(price_cents * PODIUM_COMMISSION_RATE)
