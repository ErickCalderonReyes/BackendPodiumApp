"""restructure tickets: 2 eventos (preliminar + final), 4 zonas, folios

Revision ID: 0004_tickets_two_events
Revises: 0003_tickets_discounts
Create Date: 2026-06-17

Cambios:
  - Renombra el evento existente (id=1) → "... — Gran Final"
  - Ajusta aforo de las zonas Final: Plata 146, Oro 82 (precios sin cambio)
  - Crea evento "... — Preliminar" con sus 2 zonas ($100 c/u, 146 / 82)
  - Borra discount_codes (se regeneran con el modelo de 4 códigos/tarjeta)
  - Agrega columna folio a ticket_orders (+ índice único filtrado)

Contexto:
  Tras la limpieza de duplicados, la DB tenía 1 evento (id=1) y 2 zonas
  (Plata id=1 $350, Oro id=2 $450). Esta migración convierte esas dos zonas
  en las de la Gran Final y agrega el evento Preliminar con dos zonas nuevas.

  ticket_orders estaba vacía → folio nullable + índice único filtrado
  (WHERE folio IS NOT NULL) no requiere backfill.

IMPORTANTE: el DELETE de discount_codes NO es reversible en downgrade
(los 234 códigos viejos se pierden — es intencional, se regeneran).
"""
from alembic import op
import sqlalchemy as sa


revision      = "0004_tickets_two_events"
down_revision = "0003_tickets_discounts"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── 1. El evento existente pasa a ser la Gran Final ────────────────────
    # id=1 confirmado tras la limpieza de duplicados.
    op.execute("""
        UPDATE events
        SET name = 'Mister International México 2026 — Gran Final'
        WHERE id = 1
    """)

    # ── 2. Aforo de las zonas Final (precios sin cambio) ───────────────────
    # Plata id=1, Oro id=2 (confirmado contra la DB).
    op.execute("UPDATE ticket_zones SET capacity = 146 WHERE id = 1")  # Final Plata
    op.execute("UPDATE ticket_zones SET capacity = 82  WHERE id = 2")  # Final Oro

    # ── 3. Evento Preliminar ───────────────────────────────────────────────
    op.execute("""
        INSERT INTO events (tenant_slug, name, season_year, is_active)
        VALUES ('mimx', 'Mister International México 2026 — Preliminar', 2026, 1)
    """)

    # ── 4. Zonas de la Preliminar ($100 ambas) ─────────────────────────────
    op.execute("""
        INSERT INTO ticket_zones (event_id, name, price_cents, capacity, sort_order, is_active)
        SELECT id, 'Zona Plata', 10000, 146, 1, 1
        FROM   events
        WHERE  tenant_slug = 'mimx' AND name LIKE '%Preliminar%'
    """)
    op.execute("""
        INSERT INTO ticket_zones (event_id, name, price_cents, capacity, sort_order, is_active)
        SELECT id, 'Zona Oro', 10000, 82, 2, 1
        FROM   events
        WHERE  tenant_slug = 'mimx' AND name LIKE '%Preliminar%'
    """)

    # ── 5. Borrar códigos viejos (se regeneran con el modelo de 4/tarjeta) ─
    op.execute("DELETE FROM discount_codes")

    # ── 6. Folio en ticket_orders ──────────────────────────────────────────
    op.add_column("ticket_orders", sa.Column("folio", sa.String(20), nullable=True))
    op.create_index("ix_ticket_orders_folio", "ticket_orders", ["folio"])

    # Índice único FILTRADO: en SQL Server un índice único normal solo admite
    # un NULL. Con WHERE folio IS NOT NULL permitimos múltiples NULL (pending)
    # pero garantizamos folios únicos una vez asignados.
    op.execute("""
        CREATE UNIQUE INDEX ix_ticket_orders_tenant_folio
        ON ticket_orders (tenant_slug, folio)
        WHERE folio IS NOT NULL
    """)


def downgrade() -> None:
    # Folio
    op.execute("DROP INDEX IF EXISTS ix_ticket_orders_tenant_folio ON ticket_orders")
    op.drop_index("ix_ticket_orders_folio", table_name="ticket_orders")
    op.drop_column("ticket_orders", "folio")

    # Zonas + evento Preliminar
    op.execute("""
        DELETE FROM ticket_zones
        WHERE event_id IN (
            SELECT id FROM events
            WHERE tenant_slug = 'mimx' AND name LIKE '%Preliminar%'
        )
    """)
    op.execute("DELETE FROM events WHERE tenant_slug = 'mimx' AND name LIKE '%Preliminar%'")

    # Revertir aforo y nombre de la Final
    op.execute("UPDATE ticket_zones SET capacity = 175 WHERE id = 1")
    op.execute("UPDATE ticket_zones SET capacity = 75  WHERE id = 2")
    op.execute("""
        UPDATE events
        SET name = 'Mister International México 2026'
        WHERE id = 1
    """)
    # NOTA: los discount_codes borrados en upgrade NO se restauran.