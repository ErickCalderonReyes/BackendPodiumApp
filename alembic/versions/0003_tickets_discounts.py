"""add events, ticket_zones, discount_codes, ticket_orders

Revision ID: 0003_tickets_discounts
Revises: 0002_tenants_freemium
Create Date: 2026-06-14

Cambios:
  - Crea tabla `events`        — un evento = acceso a Preliminar + Gran Final MIMX
  - Crea tabla `ticket_zones`  — precio variable + capacity opcional por zona
  - Crea tabla `discount_codes`— generalizado: percent / fixed_amount / free
  - Crea tabla `ticket_orders` — idempotencia por stripe_payment_intent_id UNIQUE

Seed MIMX 2026:
  - 1 evento:   "Mister International México 2026"
  - Zona Plata: $350 MXN · capacity 175
  - Zona Oro:   $450 MXN · capacity  75

Notas de diseño:
  - events.is_active          → switch manual para parar ventas (apagar = sin más compras)
  - ticket_zones.capacity     → NULL = sin límite; MIMX lo define por zona
  - discount_codes.max_uses   → NULL = ilimitado; 1 = código individual (tarjetas bienvenida)
  - discount_codes.applies_to_zone_id → NULL = aplica a cualquier zona del tenant
  - ticket_orders.stripe_payment_intent_id UNIQUE → idempotencia, igual que transactions
  - Boletos gratis (discount_type=free): el servicio usa "FREE-{uuid4().hex}" como valor
    sintético para mantener el UNIQUE sin pasar por Stripe Checkout
"""

from alembic import op
import sqlalchemy as sa


revision      = "0003_tickets_discounts"
down_revision = "0002_tenants_freemium"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── 1. Tabla events ────────────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column("id",          sa.Integer(),               primary_key=True, autoincrement=True),
        sa.Column("tenant_slug", sa.String(50),              nullable=False),
        sa.Column("name",        sa.String(255),             nullable=False),
        # Nullable: la fecha exacta puede no conocerse al crear el evento
        sa.Column("event_date",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("season_year", sa.Integer(),               nullable=False),
        # Switch manual: apagar para cerrar ventas sin tocar la DB directamente
        sa.Column("is_active",   sa.Boolean(),               nullable=False, server_default=sa.text("1")),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_events_id",          "events", ["id"])
    op.create_index("ix_events_tenant_slug", "events", ["tenant_slug"])
    op.create_index("ix_events_season_year", "events", ["season_year"])

    # Seed MIMX: un boleto cubre Preliminar + Gran Final (mismo venue, misma entrada)
    op.execute("""
        INSERT INTO events (tenant_slug, name, season_year, is_active)
        VALUES ('mimx', 'Mister International México 2026', 2026, 1)
    """)

    # ── 2. Tabla ticket_zones ──────────────────────────────────────────────
    op.create_table(
        "ticket_zones",
        sa.Column("id",          sa.Integer(),               primary_key=True, autoincrement=True),
        sa.Column("event_id",    sa.Integer(),               sa.ForeignKey("events.id"), nullable=False),
        sa.Column("name",        sa.String(100),             nullable=False),   # "Zona Plata" / "Zona Oro"
        sa.Column("price_cents", sa.Integer(),               nullable=False),   # precio base en centavos MXN
        # NULL = sin límite · MIMX: Plata=175, Oro=75
        sa.Column("capacity",    sa.Integer(),               nullable=True),
        sa.Column("sort_order",  sa.Integer(),               nullable=False, server_default="0"),
        sa.Column("is_active",   sa.Boolean(),               nullable=False, server_default=sa.text("1")),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_zones_id",       "ticket_zones", ["id"])
    op.create_index("ix_ticket_zones_event_id", "ticket_zones", ["event_id"])

    # Seed MIMX: Zona Plata $350 (175 lugares) — sort_order=1
    op.execute("""
        INSERT INTO ticket_zones (event_id, name, price_cents, capacity, sort_order, is_active)
        SELECT id, 'Zona Plata', 35000, 175, 1, 1
        FROM   events
        WHERE  tenant_slug = 'mimx' AND season_year = 2026
    """)

    # Seed MIMX: Zona Oro $450 (75 lugares) — sort_order=2
    op.execute("""
        INSERT INTO ticket_zones (event_id, name, price_cents, capacity, sort_order, is_active)
        SELECT id, 'Zona Oro', 45000, 75, 2, 1
        FROM   events
        WHERE  tenant_slug = 'mimx' AND season_year = 2026
    """)

    # ── 3. Tabla discount_codes ────────────────────────────────────────────
    op.create_table(
        "discount_codes",
        sa.Column("id",                 sa.Integer(),               primary_key=True, autoincrement=True),
        sa.Column("tenant_slug",        sa.String(50),              nullable=False),
        # Código que escribe el usuario: "PLATA-A3K9", "DIRECTOR-SONORA", etc.
        sa.Column("code",               sa.String(50),              nullable=False),
        # "percent" | "fixed_amount" | "free"
        sa.Column("discount_type",      sa.String(20),              nullable=False),
        # centavos para fixed_amount · 0-100 para percent · NULL para free
        sa.Column("discount_value",     sa.Integer(),               nullable=True),
        # NULL = aplica a cualquier zona del tenant
        sa.Column("applies_to_zone_id", sa.Integer(),               sa.ForeignKey("ticket_zones.id"), nullable=True),
        # NULL = ilimitado · 1 = código individual (tarjetas de bienvenida hotel)
        sa.Column("max_uses",           sa.Integer(),               nullable=True),
        sa.Column("current_uses",       sa.Integer(),               nullable=False, server_default="0"),
        sa.Column("valid_until",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active",          sa.Boolean(),               nullable=False, server_default=sa.text("1")),
        sa.Column("created_at",         sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_discount_codes_id",          "discount_codes", ["id"])
    op.create_index("ix_discount_codes_tenant_slug", "discount_codes", ["tenant_slug"])
    # Unique compuesto: dos tenants distintos pueden tener el mismo código
    op.create_index("ix_discount_codes_tenant_code", "discount_codes", ["tenant_slug", "code"], unique=True)

    # ── 4. Tabla ticket_orders ─────────────────────────────────────────────
    op.create_table(
        "ticket_orders",
        sa.Column("id",                       sa.Integer(),               primary_key=True, autoincrement=True),
        sa.Column("user_id",                  sa.Integer(),               sa.ForeignKey("users.id"),         nullable=False),
        sa.Column("zone_id",                  sa.Integer(),               sa.ForeignKey("ticket_zones.id"),  nullable=False),
        sa.Column("tenant_slug",              sa.String(50),              nullable=False),
        sa.Column("quantity",                 sa.Integer(),               nullable=False, server_default="1"),
        # Total cobrado con descuento aplicado (0 para boletos free)
        sa.Column("amount_cents",             sa.Integer(),               nullable=False),
        sa.Column("discount_code_id",         sa.Integer(),               sa.ForeignKey("discount_codes.id"), nullable=True),
        # Idempotencia — mismo patrón que transactions.stripe_payment_intent_id
        # Boletos gratis (sin Stripe): el servicio genera "FREE-{uuid4().hex}"
        sa.Column("stripe_payment_intent_id", sa.String(255),             nullable=False, unique=True),
        sa.Column("season_year",              sa.Integer(),               nullable=False),
        # "pending" → "completed" | "failed"
        sa.Column("status",                   sa.String(50),              nullable=False, server_default="pending"),
        sa.Column("created_at",               sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_orders_id",             "ticket_orders", ["id"])
    op.create_index("ix_ticket_orders_user_id",        "ticket_orders", ["user_id"])
    op.create_index("ix_ticket_orders_zone_id",        "ticket_orders", ["zone_id"])
    op.create_index("ix_ticket_orders_tenant_slug",    "ticket_orders", ["tenant_slug"])
    op.create_index("ix_ticket_orders_season_year",    "ticket_orders", ["season_year"])
    op.create_index("ix_ticket_orders_payment_intent", "ticket_orders", ["stripe_payment_intent_id"], unique=True)


def downgrade() -> None:
    # Orden inverso: primero tablas con FKs hacia otras tablas nuevas
    op.drop_index("ix_ticket_orders_payment_intent", table_name="ticket_orders")
    op.drop_index("ix_ticket_orders_season_year",    table_name="ticket_orders")
    op.drop_index("ix_ticket_orders_tenant_slug",    table_name="ticket_orders")
    op.drop_index("ix_ticket_orders_zone_id",        table_name="ticket_orders")
    op.drop_index("ix_ticket_orders_user_id",        table_name="ticket_orders")
    op.drop_index("ix_ticket_orders_id",             table_name="ticket_orders")
    op.drop_table("ticket_orders")

    op.drop_index("ix_discount_codes_tenant_code", table_name="discount_codes")
    op.drop_index("ix_discount_codes_tenant_slug", table_name="discount_codes")
    op.drop_index("ix_discount_codes_id",          table_name="discount_codes")
    op.drop_table("discount_codes")

    op.drop_index("ix_ticket_zones_event_id", table_name="ticket_zones")
    op.drop_index("ix_ticket_zones_id",       table_name="ticket_zones")
    op.drop_table("ticket_zones")

    op.drop_index("ix_events_season_year",   table_name="events")
    op.drop_index("ix_events_tenant_slug",   table_name="events")
    op.drop_index("ix_events_id",            table_name="events")
    op.drop_table("events")
