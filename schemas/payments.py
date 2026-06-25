from pydantic import BaseModel, Field
from typing import Optional


class CheckoutRequest(BaseModel):
    package_id:   int            = Field(..., description="ID del VotePackage seleccionado")
    candidate_id: int            = Field(..., description="Candidato por quien se vota")
    tenant_slug:  str            = Field(..., description="Slug del certamen (ej. mimx)")
    comment:      Optional[str]  = Field(None, max_length=500, description="Mensaje opcional al candidato")


class CheckoutResponse(BaseModel):
    checkout_url: str = Field(..., description="URL de Stripe Checkout")
    session_id:   str = Field(..., description="ID de la sesión Stripe")