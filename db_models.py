from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    ForeignKey, Numeric, Text, Index, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from database import Base


# ── Enums ──────────────────────────────────────────────────────────────────

class PlanType(str, enum.Enum):
    free = "free"
    pro  = "pro"


class DiscountType(str, enum.Enum):
    percent      = "percent"
    fixed_amount = "fixed_amount"
    free         = "free"


# ── Tenant ─────────────────────────────────────────────────────────────────

class Tenant(Base):
    __tablename__ = "tenants"

    id                      = Column(Integer, primary_key=True, index=True)
    slug                    = Column(String(63), unique=True, nullable=False, index=True)
    name                    = Column(String(255), nullable=False)

    # Plan freemium
    plan                    = Column(SAEnum(PlanType), nullable=False, default=PlanType.free)
    plan_expires_at         = Column(DateTime(timezone=True), nullable=True)
    stripe_subscription_id  = Column(String(255), nullable=True)

    # Stripe Connect — cuenta del director
    stripe_account_id       = Column(String(255), nullable=True)

    # Branding
    primary_color           = Column(String(7),   nullable=True, default="#C9A84C")
    secondary_color         = Column(String(7),   nullable=True, default="#0A0A0A")
    logo_url                = Column(String(500), nullable=True)
    banner_url              = Column(String(500), nullable=True)

    # Ownership
    owner_id                = Column(Integer, ForeignKey("users.id"), nullable=False)
    season_year             = Column(Integer, nullable=False)

    is_active               = Column(Boolean, default=True)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())
    updated_at              = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner         = relationship("User",        back_populates="tenants")
    vote_packages = relationship("VotePackage", back_populates="tenant")


# ── User ───────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name       = Column(String(255), nullable=True)
    role            = Column(String(50), default="voter")  # voter | state_director | national_admin
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    votes         = relationship("Vote",        back_populates="user")
    transactions  = relationship("Transaction", back_populates="user")
    tenants       = relationship("Tenant",      back_populates="owner")
    ticket_orders = relationship("TicketOrder", back_populates="user")   # ← nuevo


# ── Candidate ──────────────────────────────────────────────────────────────

class Candidate(Base):
    __tablename__ = "candidates"

    id          = Column(Integer, primary_key=True, index=True)
    full_name   = Column(String(255), nullable=False)
    state       = Column(String(100), nullable=False)
    bio         = Column(Text, nullable=True)
    photo_url   = Column(String(500), nullable=True)
    season_year = Column(Integer, nullable=False, index=True)
    tenant_slug = Column(String(50),  nullable=False, default="mimx", index=True)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    votes = relationship("Vote", back_populates="candidate")


# ── VotePackage ────────────────────────────────────────────────────────────
# tenant_id NULL  → plantilla nacional (admin)
# tenant_id UUID  → override del director (solo plan Pro)

class VotePackage(Base):
    __tablename__ = "vote_packages"

    id              = Column(Integer, primary_key=True, index=True)
    # NULL = plantilla nacional; FK = paquete propio del director
    tenant_id       = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    name            = Column(String(100), nullable=False)
    # Precio en centavos (sin floats en DB) — MXN
    price_cents     = Column(Integer, nullable=False)
    vote_count      = Column(Integer, nullable=False)
    # ID del Price en Stripe (se crea/recrea al cambiar el precio)
    stripe_price_id = Column(String(255), nullable=True)
    is_active       = Column(Boolean, default=True)
    sort_order      = Column(Integer, default=0)

    tenant       = relationship("Tenant",      back_populates="vote_packages")
    transactions = relationship("Transaction", back_populates="package")


# ── Vote ───────────────────────────────────────────────────────────────────

class Vote(Base):
    __tablename__ = "votes"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"),      nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False, index=True)
    season_year  = Column(Integer, nullable=False, index=True)
    tenant_slug  = Column(String(50), nullable=False, default="mimx", index=True)
    is_free      = Column(Boolean, default=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    user      = relationship("User",      back_populates="votes")
    candidate = relationship("Candidate", back_populates="votes")

    __table_args__ = (
        Index(
            "ix_votes_user_candidate_season_tenant",
            "user_id", "candidate_id", "season_year", "tenant_slug"
        ),
    )


# ── Transaction ────────────────────────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    id                       = Column(Integer, primary_key=True, index=True)
    user_id                  = Column(Integer, ForeignKey("users.id"),         nullable=False)
    package_id               = Column(Integer, ForeignKey("vote_packages.id"), nullable=False)
    candidate_id             = Column(Integer, ForeignKey("candidates.id"),    nullable=False)
    stripe_payment_intent_id = Column(String(255), unique=True, nullable=False)
    # Guardamos centavos para consistencia con VotePackage
    amount_cents             = Column(Integer, nullable=False)
    votes_credited           = Column(Integer, nullable=False)
    season_year              = Column(Integer, nullable=False, index=True)
    tenant_slug              = Column(String(50), nullable=False, default="mimx", index=True)
    status                   = Column(String(50), default="completed")
    created_at               = Column(DateTime(timezone=True), server_default=func.now())

    user    = relationship("User",        back_populates="transactions")
    package = relationship("VotePackage", back_populates="transactions")
    comment = relationship("VoteComment", back_populates="transaction", uselist=False)


# ══════════════════════════════════════════════════════════════════════════════
# TICKETS — Sistema de venta de boletos · lanzamiento 15 julio 2026
# ══════════════════════════════════════════════════════════════════════════════

# ── Event ──────────────────────────────────────────────────────────────────
# MIMX: un solo evento "MIM 2026" cubre Preliminar + Gran Final.
# El boleto da acceso a ambas noches — se aclara en el frontend con copy.
# is_active es el "switch" manual para cerrar ventas sin tocar otra cosa.

class Event(Base):
    __tablename__ = "events"

    id          = Column(Integer, primary_key=True, index=True)
    tenant_slug = Column(String(50),  nullable=False, index=True)
    name        = Column(String(255), nullable=False)
    # Nullable: fecha puede no estar definida al crear el evento
    event_date  = Column(DateTime(timezone=True), nullable=True)
    season_year = Column(Integer, nullable=False, index=True)
    # Switch manual: apagar = nadie más puede comprar boletos
    is_active   = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    zones = relationship("TicketZone", back_populates="event")


# ── TicketZone ─────────────────────────────────────────────────────────────

class TicketZone(Base):
    __tablename__ = "ticket_zones"

    id          = Column(Integer, primary_key=True, index=True)
    event_id    = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    name        = Column(String(100), nullable=False)    # "Zona Plata" · "Zona Oro"
    price_cents = Column(Integer, nullable=False)        # precio base en centavos MXN
    # NULL = sin límite de inventario · MIMX: Plata=175, Oro=75
    capacity    = Column(Integer, nullable=True)
    sort_order  = Column(Integer, nullable=False, default=0)
    is_active   = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    event          = relationship("Event",        back_populates="zones")
    discount_codes = relationship("DiscountCode", back_populates="zone")
    orders         = relationship("TicketOrder",  back_populates="zone")


# ── DiscountCode ───────────────────────────────────────────────────────────
# Diseño generalizado: sirve para cualquier certamen futuro sin tocar código.
#
# Casos MIMX configurados como datos:
#   hotel 2+ noches → PLATA-{uid}: free,         applies_to_zone=Plata, max_uses=1
#   hotel 2+ noches → ORO-{uid}:   fixed $250,   applies_to_zone=Oro,   max_uses=1
#   director estatal→ DIR-{uid}:    free,         applies_to_zone=Oro,   max_uses=1
#
# Exclusividad mutua tarjeta hotel: el webhook desactiva el código hermano
# (mismo {uid}) al confirmar el pago del primero que se use.

class DiscountCode(Base):
    __tablename__ = "discount_codes"

    id                 = Column(Integer, primary_key=True, index=True)
    tenant_slug        = Column(String(50), nullable=False, index=True)
    # Código que escribe el usuario: "PLATA-A3K9", "DIR-SONORA-7F2B", etc.
    code               = Column(String(50), nullable=False)
    # percent | fixed_amount | free
    discount_type      = Column(SAEnum(DiscountType), nullable=False)
    # centavos para fixed_amount · 0-100 para percent · NULL para free
    discount_value     = Column(Integer, nullable=True)
    # NULL = aplica a cualquier zona del tenant
    applies_to_zone_id = Column(Integer, ForeignKey("ticket_zones.id"), nullable=True)
    # NULL = ilimitado · 1 = código individual (tarjeta de bienvenida, director estatal)
    max_uses           = Column(Integer, nullable=True)
    current_uses       = Column(Integer, nullable=False, default=0)
    valid_until        = Column(DateTime(timezone=True), nullable=True)
    is_active          = Column(Boolean, nullable=False, default=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())

    zone   = relationship("TicketZone", back_populates="discount_codes")
    orders = relationship("TicketOrder", back_populates="discount_code")

    __table_args__ = (
        # Unique compuesto: dos tenants distintos pueden tener el mismo código sin conflicto
        Index("ix_discount_codes_tenant_code", "tenant_slug", "code", unique=True),
    )


# ── TicketOrder ────────────────────────────────────────────────────────────

class TicketOrder(Base):
    __tablename__ = "ticket_orders"

    id                       = Column(Integer, primary_key=True, index=True)
    # user_id nullable: invitados y comps del hotel no tienen cuenta
    user_id                  = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    zone_id                  = Column(Integer, ForeignKey("ticket_zones.id"), nullable=False, index=True)
    tenant_slug              = Column(String(50), nullable=False, index=True)
    quantity                 = Column(Integer, nullable=False, default=1)
    amount_cents             = Column(Integer, nullable=False)
    discount_code_id         = Column(Integer, ForeignKey("discount_codes.id"), nullable=True)
    stripe_payment_intent_id = Column(String(255), unique=True, nullable=False)
    season_year              = Column(Integer, nullable=False, index=True)
    status                   = Column(String(50), nullable=False, default="pending")
    folio                    = Column(String(20), nullable=True, index=True)
    # Asistente sin cuenta (invitado o huésped)
    guest_name               = Column(String(255), nullable=True)
    guest_email              = Column(String(255), nullable=True)
    guest_phone              = Column(String(50),  nullable=True)
    # Canal: public | hotel | director
    source                   = Column(String(20), nullable=False, default="public")
    # Referencia de grupo (número de habitación) para sentar juntos en el lote
    group_ref                = Column(String(100), nullable=True)
    created_at               = Column(DateTime(timezone=True), server_default=func.now())

    user          = relationship("User",         back_populates="ticket_orders")
    zone          = relationship("TicketZone",   back_populates="orders")
    discount_code = relationship("DiscountCode", back_populates="orders")


# ── VoteComment ──────────────────────────────────────────────────────────────
class VoteComment(Base):
    __tablename__ = "vote_comments"

    id             = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    candidate_id   = Column(Integer, ForeignKey("candidates.id"),   nullable=False, index=True)
    user_id        = Column(Integer, ForeignKey("users.id"),        nullable=False, index=True)
    comment_text   = Column(Text, nullable=False)
    tenant_slug    = Column(String(50), nullable=False, index=True)
    season_year    = Column(Integer,    nullable=False, index=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    transaction = relationship("Transaction", back_populates="comment")
    candidate   = relationship("Candidate")
    user        = relationship("User")