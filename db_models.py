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
    owner        = relationship("User", back_populates="tenants")
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

    votes        = relationship("Vote",        back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    tenants      = relationship("Tenant",      back_populates="owner")


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

    id           = Column(Integer, primary_key=True, index=True)
    # NULL = plantilla nacional; FK = paquete propio del director
    tenant_id    = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    name         = Column(String(100), nullable=False)
    # Precio en centavos (sin floats en DB) — MXN
    price_cents  = Column(Integer, nullable=False)
    vote_count   = Column(Integer, nullable=False)
    # ID del Price en Stripe (se crea/recrea al cambiar el precio)
    stripe_price_id = Column(String(255), nullable=True)
    is_active    = Column(Boolean, default=True)
    sort_order   = Column(Integer, default=0)

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
