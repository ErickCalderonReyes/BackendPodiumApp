from pydantic import BaseModel, Field, model_validator
from typing import Optional


class VotePackageOut(BaseModel):
    id:              int
    tenant_id:       Optional[int]
    name:            str
    price_cents:     int
    vote_count:      int
    stripe_price_id: Optional[str]
    is_active:       bool
    sort_order:      int

    # Campo calculado para el frontend — evita que Angular haga la división
    @property
    def price_mxn(self) -> float:
        return self.price_cents / 100

    model_config = {"from_attributes": True}


class VotePackageCreate(BaseModel):
    """Solo national_admin puede crear plantillas nacionales."""
    name:        str  = Field(..., min_length=2, max_length=100)
    price_cents: int  = Field(..., gt=0, description="Precio en centavos MXN, ej: 50000 = $500")
    vote_count:  int  = Field(..., gt=0)
    sort_order:  int  = Field(default=0)


class VotePackagePatch(BaseModel):
    """Para editar nombre, precio o votos de un paquete."""
    name:        Optional[str] = Field(None, min_length=2, max_length=100)
    price_cents: Optional[int] = Field(None, gt=0)
    vote_count:  Optional[int] = Field(None, gt=0)
    sort_order:  Optional[int] = None
    is_active:   Optional[bool] = None


class VotePackageOverrideCreate(BaseModel):
    """
    El director Pro crea un override del paquete nacional para su tenant.
    Hereda nombre y votos del paquete base, solo puede cambiar el precio.
    """
    base_package_id: int  = Field(..., description="ID del paquete nacional que se sobreescribe")
    price_cents:     int  = Field(..., gt=0, description="Precio personalizado en centavos MXN")
