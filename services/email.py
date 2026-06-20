"""
services/email.py
─────────────────
Servicio de correo agnóstico de proveedor. Hoy usa Resend; si más adelante
migras a Azure Communication Services u otro, solo cambias _send_raw() y el
resto del código (plantillas, llamadas) queda igual.

Requiere en .env:
  RESEND_API_KEY=re_xxxxxxxx
  EMAIL_FROM=Mister International México <boletos@misterinternational.mx>

Mientras el dominio no esté verificado en Resend, puedes enviar de prueba
poniendo EMAIL_FROM=onboarding@resend.dev (solo llega a tu propio correo).

Instala el SDK:
  pip install resend --break-system-packages
"""
from __future__ import annotations
from typing import Optional
import resend

from config import settings

resend.api_key = settings.RESEND_API_KEY


# ── Envío crudo (lo único acoplado al proveedor) ───────────────────────────

def _send_raw(to: str, subject: str, html: str) -> Optional[str]:
    """
    Envía un correo. Devuelve el id del mensaje, o None si falla.
    No lanza excepción hacia arriba: el batch no debe detenerse porque
    un correo individual rebote.
    """
    try:
        r = resend.Emails.send({
            "from":    settings.EMAIL_FROM,
            "to":      [to],
            "subject": subject,
            "html":    html,
        })
        return r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
    except Exception as e:
        print(f"[email] ERROR enviando a {to}: {e}")
        return None


# ── Plantilla de confirmación de boletos ───────────────────────────────────

def _ticket_email_html(
    titular:      str,
    habitacion:   Optional[str],
    preliminar:   list[str],   # folios Preliminar
    final:        list[str],   # folios Final
    final_zona:   str,         # "Plata" | "Oro"
) -> str:
    def _folio_list(folios: list[str]) -> str:
        items = "".join(
            f'<li style="font-size:18px;font-weight:bold;letter-spacing:1px;'
            f'padding:4px 0;">{f}</li>'
            for f in folios
        )
        return f'<ul style="list-style:none;padding:0;margin:8px 0;">{items}</ul>'

    hab_line = (
        f'<p style="margin:4px 0;color:#555;">Habitación: <strong>{habitacion}</strong></p>'
        if habitacion else ""
    )

    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;
            color:#1a1a1a;border:1px solid #e5e5e5;border-radius:12px;overflow:hidden;">
  <div style="background:#0A0A0A;color:#C9A84C;padding:24px;text-align:center;">
    <h1 style="margin:0;font-size:22px;letter-spacing:1px;">Mister International México 2026</h1>
    <p style="margin:6px 0 0;color:#e8d9a8;font-size:14px;">Confirmación de acceso</p>
  </div>

  <div style="padding:24px;">
    <p style="margin:0 0 4px;">Hola <strong>{titular}</strong>,</p>
    {hab_line}
    <p style="margin:12px 0;color:#333;">
      Tu acceso está confirmado. Presenta estos folios en la entrada
      (los mostramos también en la lista de acceso, no necesitas imprimir nada).
    </p>

    <div style="background:#faf7ef;border:1px solid #ecdfbd;border-radius:8px;padding:16px;margin:16px 0;">
      <p style="margin:0 0 4px;color:#7a6a3a;font-size:13px;text-transform:uppercase;
                letter-spacing:1px;">Preliminar — Entrada general</p>
      {_folio_list(preliminar)}
    </div>

    <div style="background:#faf7ef;border:1px solid #ecdfbd;border-radius:8px;padding:16px;margin:16px 0;">
      <p style="margin:0 0 4px;color:#7a6a3a;font-size:13px;text-transform:uppercase;
                letter-spacing:1px;">Gran Final — Zona {final_zona}</p>
      {_folio_list(final)}
      <p style="margin:8px 0 0;color:#888;font-size:12px;">
        Tu asiento asignado se confirmará en un correo posterior, antes del evento.
      </p>
    </div>

    <p style="margin:16px 0 0;color:#555;font-size:13px;">
      Si tienes dudas, responde a este correo. ¡Nos vemos en el evento!
    </p>
  </div>

  <div style="background:#0A0A0A;color:#888;padding:14px;text-align:center;font-size:11px;">
    Mister International México · misterinternational.mx
  </div>
</div>
"""


def send_ticket_confirmation(
    to:           str,
    titular:      str,
    preliminar:   list[str],
    final:        list[str],
    final_zona:   str,
    habitacion:   Optional[str] = None,
) -> Optional[str]:
    """
    Envía la confirmación de boletos a un huésped/asistente.
    Devuelve el id del mensaje o None si falló.
    """
    n = len(preliminar) + len(final)
    subject = f"Tus {n} accesos · Mister International México 2026"
    html = _ticket_email_html(titular, habitacion, preliminar, final, final_zona)
    return _send_raw(to, subject, html)


def send_public_ticket_confirmation(
    to: str, name: str, event_name: str, zone_name: str,
    quantity: int, folio: Optional[str], amount_cents: int,
) -> Optional[str]:
    pesos = f"${amount_cents/100:,.0f} MXN"
    lugares = f"{quantity} lugar" + ("es" if quantity > 1 else "")
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;
            color:#1a1a1a;border:1px solid #e5e5e5;border-radius:12px;overflow:hidden;">
  <div style="background:#0A0A0A;color:#C9A84C;padding:24px;text-align:center;">
    <h1 style="margin:0;font-size:22px;letter-spacing:1px;">Mister International México 2026</h1>
    <p style="margin:6px 0 0;color:#e8d9a8;font-size:14px;">Confirmación de compra</p>
  </div>
  <div style="padding:24px;">
    <p style="margin:0 0 12px;">Hola <strong>{name}</strong>, tu compra está confirmada.</p>
    <div style="background:#faf7ef;border:1px solid #ecdfbd;border-radius:8px;padding:16px;">
      <p style="margin:0 0 4px;color:#7a6a3a;font-size:13px;text-transform:uppercase;
                letter-spacing:1px;">{event_name} — {zone_name}</p>
      <p style="margin:8px 0;font-size:22px;font-weight:bold;letter-spacing:2px;">{folio or '—'}</p>
      <p style="margin:0;color:#555;">{lugares} · {pesos}</p>
    </div>
    <p style="margin:16px 0 0;color:#888;font-size:12px;">
      Presenta este folio en la entrada (aparece también en la lista de acceso).
      Tu asiento, si aplica, se confirmará antes del evento.
    </p>
  </div>
  <div style="background:#0A0A0A;color:#888;padding:14px;text-align:center;font-size:11px;">
    Mister International México · misterinternational.mx
  </div>
</div>
"""
    subject = f"Tu compra · {event_name}"
    return _send_raw(to, subject, html)