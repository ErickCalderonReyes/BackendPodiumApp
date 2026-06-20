"""
generate_codes.py
─────────────────
Generador de códigos de descuento para Mister International México 2026.

Produce 4 archivos:
  codigos_hotel_INSERT.sql       → 100 tarjetas (PLATA gratis + ORO -$250) · pegar en Azure Query Editor
  codigos_directores_INSERT.sql  → 34 códigos de director (Oro gratis)     · pegar en Azure Query Editor
  tarjetas_hotel.csv             → para la imprenta de las tarjetas de bienvenida
  codigos_directores.csv         → para distribuir a cada director estatal

Modelo de descuentos:
  Tarjeta hotel  → PLATA-{uid}: free,         zona Plata (id=1), max_uses=1
                 → ORO-{uid}:   fixed -$250,  zona Oro   (id=2), max_uses=1
                 (ambos comparten uid → exclusividad mutua vía webhook)
  Director       → {ABREV}-{uid}: free,       zona Oro   (id=2), max_uses=1

Uso:
  python generate_codes.py

Para un director de último minuto no contemplado, ver generar_codigo_director() al final.
"""
import csv
import secrets
import string

# ── Configuración MIMX (confirmada contra la DB) ───────────────────────────
TENANT_SLUG       = "mimx"
ZONA_PLATA_ID     = 1
ZONA_ORO_ID       = 2
PRECIO_ORO_CENTS  = 45000          # $450 — referencia para el CSV
DESCUENTO_ORO     = 25000          # $250 off en centavos (fixed_amount)
N_TARJETAS_HOTEL  = 100

# uid sin caracteres ambiguos (sin 0/O, 1/I/L) — fácil de leer en papel
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _uid(n: int = 6) -> str:
    """Genera un identificador único legible de n caracteres."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def _esc(s: str) -> str:
    """Escapa comillas simples para SQL."""
    return s.replace("'", "''")


# ── 32 estados + abreviaturas · duplicados de BC y ZAC ─────────────────────
# (abreviatura, nombre completo)
DIRECTORES = [
    ("AGS",  "Aguascalientes"),
    ("BC",   "Baja California"),
    ("BC2",  "Baja California (2º director)"),
    ("BCS",  "Baja California Sur"),
    ("CAMP", "Campeche"),
    ("CHIS", "Chiapas"),
    ("CHIH", "Chihuahua"),
    ("CDMX", "Ciudad de México"),
    ("COAH", "Coahuila"),
    ("COL",  "Colima"),
    ("DGO",  "Durango"),
    ("GTO",  "Guanajuato"),
    ("GRO",  "Guerrero"),
    ("HGO",  "Hidalgo"),
    ("JAL",  "Jalisco"),
    ("MEX",  "Estado de México"),
    ("MICH", "Michoacán"),
    ("MOR",  "Morelos"),
    ("NAY",  "Nayarit"),
    ("NL",   "Nuevo León"),
    ("OAX",  "Oaxaca"),
    ("PUE",  "Puebla"),
    ("QRO",  "Querétaro"),
    ("QROO", "Quintana Roo"),
    ("SLP",  "San Luis Potosí"),
    ("SIN",  "Sinaloa"),
    ("SON",  "Sonora"),
    ("TAB",  "Tabasco"),
    ("TAMS", "Tamaulipas"),
    ("TLAX", "Tlaxcala"),
    ("VER",  "Veracruz"),
    ("YUC",  "Yucatán"),
    ("ZAC",  "Zacatecas"),
    ("ZAC2", "Zacatecas (2º director)"),
]


# ── 1. Tarjetas de hotel ───────────────────────────────────────────────────

def generar_hotel():
    rows_sql = []
    rows_csv = []

    for i in range(1, N_TARJETAS_HOTEL + 1):
        uid          = _uid()
        codigo_plata = f"PLATA-{uid}"
        codigo_oro   = f"ORO-{uid}"

        # PLATA gratis
        rows_sql.append(
            f"('{TENANT_SLUG}', '{_esc(codigo_plata)}', 'free', NULL, "
            f"{ZONA_PLATA_ID}, 1, 0, 1)"
        )
        # ORO -$250
        rows_sql.append(
            f"('{TENANT_SLUG}', '{_esc(codigo_oro)}', 'fixed_amount', {DESCUENTO_ORO}, "
            f"{ZONA_ORO_ID}, 1, 0, 1)"
        )

        rows_csv.append({
            "tarjeta_num":     i,
            "codigo_plata":    codigo_plata,
            "descuento_plata": "GRATIS",
            "codigo_oro":      codigo_oro,
            "descuento_oro":   "$250 MXN de descuento",
        })

    # SQL
    with open("codigos_hotel_INSERT.sql", "w", encoding="utf-8") as f:
        f.write("-- 100 tarjetas de hotel (200 códigos: PLATA gratis + ORO -$250)\n")
        f.write("-- Cada par PLATA/ORO comparte uid → exclusividad mutua vía webhook\n")
        f.write("INSERT INTO discount_codes\n")
        f.write("  (tenant_slug, code, discount_type, discount_value, "
                "applies_to_zone_id, max_uses, current_uses, is_active)\n")
        f.write("VALUES\n")
        f.write(",\n".join(rows_sql))
        f.write(";\n")

    # CSV
    with open("tarjetas_hotel.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "tarjeta_num", "codigo_plata", "descuento_plata", "codigo_oro", "descuento_oro"
        ])
        w.writeheader()
        w.writerows(rows_csv)

    print(f"✅ Hotel: {N_TARJETAS_HOTEL} tarjetas ({N_TARJETAS_HOTEL*2} códigos)")
    print("   → codigos_hotel_INSERT.sql")
    print("   → tarjetas_hotel.csv")


# ── 2. Códigos de directores ───────────────────────────────────────────────

def generar_directores():
    rows_sql = []
    rows_csv = []

    for abrev, nombre in DIRECTORES:
        uid    = _uid()
        codigo = f"{abrev}-{uid}"

        # Oro gratis, un solo uso
        rows_sql.append(
            f"('{TENANT_SLUG}', '{_esc(codigo)}', 'free', NULL, "
            f"{ZONA_ORO_ID}, 1, 0, 1)"
        )

        rows_csv.append({
            "estado":    nombre,
            "abrev":     abrev,
            "codigo":    codigo,
            "beneficio": "Zona Oro GRATIS (1 boleto)",
        })

    # SQL
    with open("codigos_directores_INSERT.sql", "w", encoding="utf-8") as f:
        f.write(f"-- {len(DIRECTORES)} códigos de director estatal (Oro gratis, max_uses=1)\n")
        f.write("INSERT INTO discount_codes\n")
        f.write("  (tenant_slug, code, discount_type, discount_value, "
                "applies_to_zone_id, max_uses, current_uses, is_active)\n")
        f.write("VALUES\n")
        f.write(",\n".join(rows_sql))
        f.write(";\n")

    # CSV
    with open("codigos_directores.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["estado", "abrev", "codigo", "beneficio"])
        w.writeheader()
        w.writerows(rows_csv)

    print(f"✅ Directores: {len(DIRECTORES)} códigos")
    print("   → codigos_directores_INSERT.sql")
    print("   → codigos_directores.csv")


# ── Director de último minuto ──────────────────────────────────────────────

def generar_codigo_director(abrev: str, nombre_estado: str):
    """
    Genera UN código de director sobre la marcha (director no contemplado).

    Uso en consola:
        python -c "from generate_codes import generar_codigo_director as g; g('SON', 'Sonora')"

    Imprime el INSERT listo para pegar en Azure Query Editor y el código a entregar.
    """
    uid    = _uid()
    codigo = f"{abrev.upper()}-{uid}"
    sql = (
        "INSERT INTO discount_codes "
        "(tenant_slug, code, discount_type, discount_value, "
        "applies_to_zone_id, max_uses, current_uses, is_active) VALUES "
        f"('{TENANT_SLUG}', '{_esc(codigo)}', 'free', NULL, "
        f"{ZONA_ORO_ID}, 1, 0, 1);"
    )
    print(f"\nEstado:  {nombre_estado}")
    print(f"Código:  {codigo}  (Zona Oro gratis)")
    print(f"\nSQL para Azure Query Editor:\n{sql}\n")
    return codigo


if __name__ == "__main__":
    generar_hotel()
    print()
    generar_directores()
    print("\n🎟️  Listo. Pega los dos .sql en Azure Portal → Query Editor.")
    print("    Verifica después con: SELECT COUNT(*) FROM discount_codes;  -- debe dar 234")
