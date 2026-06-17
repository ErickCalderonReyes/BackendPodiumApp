"""
schemas/tickets.py
──────────────────
Pydantic schemas para la venta de boletos.
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ── Respuestas de lectura ──────────────────────────────────────────────────

class TicketZoneOut(BaseModel):
    id:          int
    name:        str
    price_cents: int
    capacity:    Optional[int] = None
    sold:        int = 0          # órdenes confirmadas, calculado en el servicio
    sort_order:  int

    model_config = {"from_attributes": True}


class EventOut(BaseModel):
    id:          int
    name:        str
    event_date:  Optional[datetime] = None
    season_year: int
    is_active:   bool
    zones:       List[TicketZoneOut] = []

    model_config = {"from_attributes": True}


# ── Validación de código de descuento ─────────────────────────────────────

class ValidateCodeRequest(BaseModel):
    tenant_slug: str
    code:        str
    zone_id:     int


class ValidateCodeResponse(BaseModel):
    valid:                bool
    discount_type:        Optional[str] = None
    discount_value:       Optional[int] = None
    original_price_cents: int = 0
    final_price_cents:    int = 0
    message:              str


# ── Checkout de boleto ─────────────────────────────────────────────────────

class TicketCheckoutRequest(BaseModel):
    tenant_slug:   str
    zone_id:       int
    quantity:      int = 1
    discount_code: Optional[str] = None


class TicketCheckoutResponse(BaseModel):
    # None para boletos gratis — el frontend redirige a /boletos/exito directamente
    checkout_url: Optional[str] = None
    session_id:   Optional[str] = None
    amount_cents: int
    is_free:      bool = False
    zone_name:    str
