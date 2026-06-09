from pydantic import BaseModel, Field
from typing import Optional


class CheckoutRequest(BaseModel):
    package_id:   int = Field(..., description="ID del VotePackage seleccionado")
    candidate_id: int = Field(..., description="Candidato por quien se vota — se fija antes del pago")


class CheckoutResponse(BaseModel):
    checkout_url: str  = Field(..., description="URL de Stripe Checkout — redirect en el frontend")
    session_id:   str  = Field(..., description="ID de la sesión Stripe para verificación")
