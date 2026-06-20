"""
issue_hotel_tickets.py
──────────────────────
Emisión en lote de boletos comp para huéspedes del hotel (y directores).

Lee un CSV (una fila por habitación) y por cada habitación crea:
  - num_personas órdenes de Preliminar (entrada general, gratis)
  - num_personas órdenes de Final Plata (gratis), agrupadas por habitación (group_ref)
Luego manda UN correo al titular con todos los folios.

Las órdenes se crean con:
  source='hotel', status='completed', amount_cents=0
  stripe_payment_intent_id = 'HOTEL-{uuid}'  (sintético, respeta el UNIQUE)
  folio secuencial por evento+zona (PRE-001, FP-001, ...)
  group_ref = número de habitación (para sentar juntos en el lote de asientos)

CSV esperado (UTF-8):
  habitacion,titular,correo,num_personas,telefono
  201,Madonna,madonna@correo.com,2,
  305,Michael Jackson,mj@correo.com,4,

Uso:
  # prueba sin enviar correos ni escribir DB (recomendado primero):
  python issue_hotel_tickets.py --csv hotel_prueba.csv --dry-run

  # ejecución real:
  python issue_hotel_tickets.py --csv hotel_prueba.csv

  # sin mandar correos (solo crea órdenes):
  python issue_hotel_tickets.py --csv hotel_prueba.csv --no-email
"""
import argparse
import asyncio
import csv
import sys
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from database import AsyncSessionLocal
from db_models import TicketOrder, TicketZone, Event

# ── Configuración MIMX (IDs confirmados) ───────────────────────────────────
TENANT_SLUG       = "mimx"
SEASON            = 2026
ZONA_PRE_GENERAL  = 7   # Preliminar "General"
ZONA_FIN_PLATA    = 1   # Final Plata
CAP_FIN_PLATA     = 146

# Prefijos de folio por zona
FOLIO_PREFIX = {
    ZONA_PRE_GENERAL: "PRE",
    ZONA_FIN_PLATA:   "FP",
}


async def _next_folio(db, zone_id: int) -> str:
    """Folio secuencial por zona: PRE-001, FP-001, ... (reintenta ante carrera)."""
    prefix = FOLIO_PREFIX.get(zone_id, "GEN")
    count = await db.scalar(
        select(func.count(TicketOrder.id)).where(
            TicketOrder.zone_id == zone_id,
            TicketOrder.status  == "completed",
            TicketOrder.folio.is_not(None),
        )
    ) or 0
    return f"{prefix}-{count + 1:03d}"


async def _create_order(db, zone_id, titular, correo, telefono, habitacion) -> str:
    """Crea una orden comp y devuelve su folio."""
    folio = await _next_folio(db, zone_id)
    order = TicketOrder(
        user_id                  = None,
        zone_id                  = zone_id,
        tenant_slug              = TENANT_SLUG,
        quantity                 = 1,
        amount_cents             = 0,
        stripe_payment_intent_id = f"HOTEL-{uuid4().hex}",
        season_year              = SEASON,
        status                   = "completed",
        folio                    = folio,
        guest_name               = titular,
        guest_email              = correo,
        guest_phone              = telefono or None,
        source                   = "hotel",
        group_ref                = habitacion,
    )
    db.add(order)
    await db.flush()   # asigna id; valida UNIQUE de folio/payment_intent
    return folio


async def run(csv_path: str, dry_run: bool, send_emails: bool):
    # Importar el envío solo si se va a usar (evita exigir resend en dry-run)
    send_ticket_confirmation = None
    if send_emails and not dry_run:
        from services.email import send_ticket_confirmation

    # Leer CSV
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("CSV vacío.")
        return

    total_personas = sum(int(r["num_personas"]) for r in rows)
    print(f"Habitaciones: {len(rows)} · personas totales: {total_personas}")
    print(f"Boletos a crear: {total_personas} Preliminar + {total_personas} Final Plata\n")

    # DRY RUN primero — verdaderamente offline, no toca la DB
    if dry_run:
        print("— DRY RUN — no se escribe DB ni se envían correos.\n")
        for r in rows:
            n = int(r["num_personas"])
            print(f"  Hab {r['habitacion']:>4} · {r['titular']:<22} · {r['correo']:<28} "
                  f"· {n} pers → {n} PRE + {n} FP, correo con {2*n} folios")
        return

    # Guard de aforo Final Plata (solo en ejecución real)
    async with AsyncSessionLocal() as db:
        ya_plata = await db.scalar(
            select(func.count(TicketOrder.id)).where(
                TicketOrder.zone_id == ZONA_FIN_PLATA,
                TicketOrder.status  == "completed",
            )
        ) or 0
    if ya_plata + total_personas > CAP_FIN_PLATA:
        print(f"⛔ Excede aforo Final Plata: {ya_plata} ya emitidos + {total_personas} "
              f"= {ya_plata + total_personas} > {CAP_FIN_PLATA}. Abortando.")
        sys.exit(1)

    # Ejecución real — una transacción por habitación (atómica por correo)
    enviados, fallidos = 0, 0
    for r in rows:
        habitacion = r["habitacion"].strip()
        titular    = r["titular"].strip()
        correo     = r["correo"].strip()
        telefono   = (r.get("telefono") or "").strip()
        n          = int(r["num_personas"])

        async with AsyncSessionLocal() as db:
            try:
                pre_folios, fin_folios = [], []
                for _ in range(n):
                    pre_folios.append(
                        await _create_order(db, ZONA_PRE_GENERAL, titular, correo, telefono, habitacion)
                    )
                for _ in range(n):
                    fin_folios.append(
                        await _create_order(db, ZONA_FIN_PLATA, titular, correo, telefono, habitacion)
                    )
                await db.commit()
            except IntegrityError as e:
                await db.rollback()
                print(f"  ⚠ Hab {habitacion} ({titular}): error DB, se omite — {e}")
                fallidos += 1
                continue

        print(f"  ✅ Hab {habitacion} · {titular}: {n} PRE {pre_folios} + {n} FP {fin_folios}")

        if send_emails:
            msg_id = send_ticket_confirmation(
                to=correo, titular=titular,
                preliminar=pre_folios, final=fin_folios,
                final_zona="Plata", habitacion=habitacion,
            )
            if msg_id:
                enviados += 1
                print(f"     ✉ correo enviado ({msg_id})")
            else:
                fallidos += 1
                print(f"     ⚠ correo NO enviado a {correo}")

    print(f"\nListo. Habitaciones OK · correos enviados: {enviados} · fallidos: {fallidos}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Ruta al CSV del hotel")
    ap.add_argument("--dry-run", action="store_true", help="Simula sin escribir DB ni enviar")
    ap.add_argument("--no-email", action="store_true", help="Crea órdenes pero no envía correos")
    args = ap.parse_args()

    asyncio.run(run(args.csv, dry_run=args.dry_run, send_emails=not args.no_email))