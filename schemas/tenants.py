from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class TenantOut(BaseModel):
    id:                     int
    slug:                   str
    name:                   str
    plan:                   str
    plan_expires_at:        Optional[datetime]
    stripe_account_id:      Optional[str]
    primary_color:          Optional[str]
    secondary_color:        Optional[str]
    logo_url:               Optional[str]
    banner_url:             Optional[str]
    season_year:            int
    is_active:              bool

    model_config = {"from_attributes": True}


class TenantPublic(BaseModel):
    """Lo que el frontend Angular necesita para cargar la marca del certamen."""
    slug:           str
    name:           str
    primary_color:  Optional[str]
    secondary_color: Optional[str]
    logo_url:       Optional[str]
    banner_url:     Optional[str]
    season_year:    int

    model_config = {"from_attributes": True}


class StripeConnectResponse(BaseModel):
    """Respuesta del endpoint que genera el link de onboarding Express."""
    onboarding_url: str
    account_id:     str