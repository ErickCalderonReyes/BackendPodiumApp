from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(String(50), default="voter")  # voter | state_director | national_admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    votes = relationship("Vote", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    state = Column(String(100), nullable=False)
    bio = Column(Text, nullable=True)
    photo_url = Column(String(500), nullable=True)
    season_year = Column(Integer, nullable=False, index=True)
    tenant_slug = Column(String(50), nullable=False, default="mimx", index=True)  # 👈 nuevo
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    votes = relationship("Vote", back_populates="candidate")


class VotePackage(Base):
    __tablename__ = "vote_packages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    price_mxn = Column(Numeric(10, 2), nullable=False)
    vote_count = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)

    transactions = relationship("Transaction", back_populates="package")


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False, index=True)  # 👈 index agregado
    season_year = Column(Integer, nullable=False, index=True)
    tenant_slug = Column(String(50), nullable=False, default="mimx", index=True)  # 👈 nuevo
    is_free = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="votes")
    candidate = relationship("Candidate", back_populates="votes")

    __table_args__ = (
        Index("ix_votes_user_candidate_season_tenant",
              "user_id", "candidate_id", "season_year", "tenant_slug"),  # 👈 nuevo
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    package_id = Column(Integer, ForeignKey("vote_packages.id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    stripe_payment_intent_id = Column(String(255), unique=True, nullable=False)
    amount_mxn = Column(Numeric(10, 2), nullable=False)
    votes_credited = Column(Integer, nullable=False)
    season_year = Column(Integer, nullable=False, index=True)
    tenant_slug = Column(String(50), nullable=False, default="mimx", index=True)  # 👈 nuevo
    status = Column(String(50), default="completed")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="transactions")
    package = relationship("VotePackage", back_populates="transactions")