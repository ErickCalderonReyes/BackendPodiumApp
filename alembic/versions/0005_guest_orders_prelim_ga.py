"""ticket_orders para invitados/comps + Preliminar entrada general

Revision ID: 0005_guest_orders_prelim_ga
Revises: 0004_tickets_two_events
Create Date: 2026-06-17

Cambios:
  ticket_orders:
    - user_id  -> nullable (compras como invitado y comps del hotel no tienen cuenta)
    - + guest_name, guest_email, guest_phone  (datos del asistente)
    - + source   ('public' | 'hotel' | 'director')  default 'public'
    - + group_ref (p.ej. numero de habitacion, para sentar juntos en el lote)

  Preliminar -> entrada general unica:
    - zona id=7 (Preliminar Plata) renombrada a 'General'  (precio $100 sin cambio)
    - zona id=8 (Preliminar Oro) desactivada (is_active=0) — la Preliminar no tiene zonas

Nota: ticket_orders esta vacia, asi que source NOT NULL con default no requiere backfill.
"""
from alembic import op
import sqlalchemy as sa


revision      = "0005_guest_orders_prelim_ga"
down_revision = "0004_tickets_two_events"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # -- ticket_orders: asistente sin cuenta -------------------------------
    op.alter_column("ticket_orders", "user_id",
                    existing_type=sa.Integer(), nullable=True)

    op.add_column("ticket_orders", sa.Column("guest_name",  sa.String(255), nullable=True))
    op.add_column("ticket_orders", sa.Column("guest_email", sa.String(255), nullable=True))
    op.add_column("ticket_orders", sa.Column("guest_phone", sa.String(50),  nullable=True))
    op.add_column("ticket_orders", sa.Column("source", sa.String(20),
                                             nullable=False, server_default="public"))
    op.add_column("ticket_orders", sa.Column("group_ref", sa.String(100), nullable=True))

    op.create_index("ix_ticket_orders_source",    "ticket_orders", ["source"])
    op.create_index("ix_ticket_orders_group_ref", "ticket_orders", ["group_ref"])

    # -- Preliminar = entrada general unica --------------------------------
    op.execute("UPDATE ticket_zones SET name = 'General' WHERE id = 7")  # Preliminar
    op.execute("UPDATE ticket_zones SET is_active = 0     WHERE id = 8")  # Preliminar Oro off


def downgrade() -> None:
    op.execute("UPDATE ticket_zones SET is_active = 1   WHERE id = 8")
    op.execute("UPDATE ticket_zones SET name = 'Zona Plata' WHERE id = 7")

    op.drop_index("ix_ticket_orders_group_ref", table_name="ticket_orders")
    op.drop_index("ix_ticket_orders_source",    table_name="ticket_orders")
    op.drop_column("ticket_orders", "group_ref")
    op.drop_column("ticket_orders", "source")
    op.drop_column("ticket_orders", "guest_phone")
    op.drop_column("ticket_orders", "guest_email")
    op.drop_column("ticket_orders", "guest_name")
    op.alter_column("ticket_orders", "user_id",
                    existing_type=sa.Integer(), nullable=False)