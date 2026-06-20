"""add tenants + freemium plan + vote_packages multi-tenant

Revision ID: 0002_tenants_freemium
Revises: 0148a4e8a170
Create Date: 2026-06-08

Cambios:
  - Crea tabla `tenants` con plan freemium, branding y Stripe Connect
  - Agrega `tenant_id` (FK nullable) a `vote_packages`
  - Agrega `stripe_price_id` y `sort_order` a `vote_packages`
  - Migra `price_mxn` → `price_cents` (int) en `vote_packages`
  - Migra `amount_mxn` → `amount_cents` (int) en `transactions`

IMPORTANTE: `tenant_slug` ya existe en candidates, votes, transactions
desde la migración inicial — no se toca aquí.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "0002_tenants_freemium"
down_revision = "0148a4e8a170"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── 1. Tabla tenants ───────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id",                     sa.Integer(),      primary_key=True, autoincrement=True),
        sa.Column("slug",                   sa.String(63),     nullable=False),
        sa.Column("name",                   sa.String(255),    nullable=False),

        # Plan freemium
        sa.Column("plan",                   sa.String(10),     nullable=False, server_default="free"),
        sa.Column("plan_expires_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255),    nullable=True),

        # Stripe Connect
        sa.Column("stripe_account_id",      sa.String(255),    nullable=True),

        # Branding
        sa.Column("primary_color",          sa.String(7),      nullable=True, server_default="#C9A84C"),
        sa.Column("secondary_color",        sa.String(7),      nullable=True, server_default="#0A0A0A"),
        sa.Column("logo_url",               sa.String(500),    nullable=True),
        sa.Column("banner_url",             sa.String(500),    nullable=True),

        # Ownership
        sa.Column("owner_id",               sa.Integer(),      sa.ForeignKey("users.id"), nullable=False),
        sa.Column("season_year",            sa.Integer(),      nullable=False),

        sa.Column("is_active",              sa.Boolean(),      nullable=False, server_default=sa.text("1")),
        sa.Column("created_at",             sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",             sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("ix_tenants_id",   "tenants", ["id"])

    # Inserta el tenant piloto de Mister International México
    # owner_id=1 asume que el primer usuario registrado es el admin nacional.
    # Ajusta el ID si tu admin tiene otro id en producción.
    op.execute("""
               INSERT INTO tenants (slug, name, [plan], owner_id, season_year, is_active)
               VALUES ('mimx', 'Mister International México', 'pro', 1, 2026, 1)
               """)

    # ── 2. vote_packages: nuevas columnas ─────────────────────────────────
    # tenant_id nullable — NULL = plantilla nacional
    op.add_column("vote_packages",
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id"), nullable=True))
    op.create_index("ix_vote_packages_tenant_id", "vote_packages", ["tenant_id"])

    # stripe_price_id y sort_order
    op.add_column("vote_packages",
        sa.Column("stripe_price_id", sa.String(255), nullable=True))
    op.add_column("vote_packages",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))

    # ── 3. vote_packages: price_mxn (Numeric) → price_cents (Integer) ─────
    # Paso 1: agregar columna nueva
    op.add_column("vote_packages",
        sa.Column("price_cents", sa.Integer(), nullable=True))

    # Paso 2: poblar desde el valor existente (MXN * 100, redondeado)
    op.execute("""
        UPDATE vote_packages
        SET price_cents = CAST(ROUND(price_mxn * 100, 0) AS INT)
    """)

    # Paso 3: hacer NOT NULL ahora que está poblada
    op.alter_column("vote_packages", "price_cents",
                    existing_type=sa.Integer(), nullable=False)

    # Paso 4: eliminar columna vieja
    op.drop_column("vote_packages", "price_mxn")

    # ── 4. transactions: amount_mxn (Numeric) → amount_cents (Integer) ────
    op.add_column("transactions",
        sa.Column("amount_cents", sa.Integer(), nullable=True))

    op.execute("""
        UPDATE transactions
        SET amount_cents = CAST(ROUND(amount_mxn * 100, 0) AS INT)
    """)

    op.alter_column("transactions", "amount_cents",
                    existing_type=sa.Integer(), nullable=False)
    op.drop_column("transactions", "amount_mxn")


def downgrade() -> None:
    # ── Revertir transactions ──────────────────────────────────────────────
    op.add_column("transactions",
        sa.Column("amount_mxn", sa.Numeric(10, 2), nullable=True))
    op.execute("UPDATE transactions SET amount_mxn = CAST(amount_cents AS NUMERIC) / 100")
    op.alter_column("transactions", "amount_mxn",
                    existing_type=sa.Numeric(10, 2), nullable=False)

    # ── Revertir vote_packages ─────────────────────────────────────────────
    op.add_column("vote_packages",
        sa.Column("price_mxn", sa.Numeric(10, 2), nullable=True))
    op.execute("UPDATE vote_packages SET price_mxn = CAST(price_cents AS NUMERIC) / 100")
    op.alter_column("vote_packages", "price_mxn",
                    existing_type=sa.Numeric(10, 2), nullable=False)
    op.drop_column("vote_packages", "price_cents")
    op.drop_column("vote_packages", "sort_order")
    op.drop_column("vote_packages", "stripe_price_id")

    op.drop_index("ix_vote_packages_tenant_id", table_name="vote_packages")
    op.drop_column("vote_packages", "tenant_id")

    # ── Revertir tenants ───────────────────────────────────────────────────
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_index("ix_tenants_id",   table_name="tenants")
    op.drop_table("tenants")
