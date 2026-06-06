"""
Daily Macro Briefing — 8-line narrative context for all events of the day.

Unlike the 4-line tactical analysis (SEÑAL/SCORES/PRECIO/ACCIÓN) that fires
after each individual release, this briefing is a session-wide context generator
that explains WHY each event matters, WHEN to act, and HOW the day's releases
interact as a unified macro narrative.

Triggered manually or auto-loaded in the Analysis panel idle state.
Cached 10 minutes; ?force=true regenerates immediately.
"""

from __future__ import annotations

import anthropic
from datetime import datetime, UTC

from app.core import cache
from app.core.claude_retry import claude_with_retry
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_SYSTEM = """Eres un estratega macro senior de Goldman Sachs. Respondes ÚNICAMENTE en Español.
Exactamente 8 líneas. Sin markdown. Sin líneas en blanco. Texto plano.
Cita horas y nombres exactos del input. Sé directo, preciso y accionable como Bloomberg Terminal.

FORMATO OBLIGATORIO (8 líneas exactas, cada una empieza con su etiqueta):
CONTEXTO: [situación macro actual — ciclo Fed, inflación, tendencia USD y ORO últimas 2 semanas]
NARRATIVA: [tema unificador del día — qué historia cuentan estos datos juntos para el mercado]
CLAVE: [evento más importante hoy — nombre exacto, hora UTC, por qué domina ORO y USD]
HORARIO: [línea de tiempo completa — HH:MM Evento1 · HH:MM Evento2 · HH:MM Evento3]
CADENA: [correlación — cómo afecta evento1 a la interpretación de evento2, riesgo acumulado]
TRADING: [ventanas de no-operar — N min antes de [evento], M min después · horas libres hoy]
SESGO: [ALCISTA/BAJISTA/NEUTRAL ORO hoy — razón macro + nivel BSL y SSL clave del día]
ACCIÓN: [PREPARAR_LONG/PREPARAR_SHORT/ESPERAR — condición específica de entrada o trigger]"""


async def generate_daily_briefing(
    upcoming_events: list[dict],
    recent_releases: list[dict],
    current_prices: dict,
) -> dict:
    """
    Generate 8-line daily macro briefing for all today's high-impact events.

    upcoming_events: list of pending events sorted by time
    recent_releases: list of already-released events today with surprise data
    current_prices:  {XAUUSD, DXY, US10Y, SP500} current levels
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    # Stable cache key: date + sorted event names
    event_ids = ":".join(sorted(
        ev.get("event_name", "") for ev in upcoming_events + recent_releases
    ))
    cache_key = f"analysis:briefing:{today}:{hash(event_ids)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    if not settings.anthropic_api_key:
        return {
            "briefing": "⚠️ ANTHROPIC_API_KEY no configurada.",
            "model": "none",
            "tokens_used": 0,
            "upcoming_count": len(upcoming_events),
            "released_count": len(recent_releases),
            "generated_at": datetime.now(UTC).isoformat(),
        }

    # ── Build user prompt ────────────────────────────────────────────────────
    lines: list[str] = [f"SESIÓN: {today} UTC\n"]

    if upcoming_events:
        lines.append("PRÓXIMOS EVENTOS:")
        for ev in sorted(upcoming_events, key=lambda e: e.get("event_at", "")):
            t    = ev.get("event_at", "")[:16].replace("T", " ")
            imp  = "★★★" if ev.get("importance") == "high" else "★★"
            fc   = ev.get("forecast")
            prev = ev.get("previous")
            unit = ev.get("unit", "")
            fc_str   = f"Pronóstico: {fc}{unit}" if fc is not None else "Sin pronóstico"
            prev_str = f"| Previo: {prev}{unit}" if prev is not None else ""
            lines.append(
                f"  {t} UTC {imp} {ev.get('event_name', 'N/A')} — {fc_str} {prev_str}".rstrip()
            )
    else:
        lines.append("PRÓXIMOS EVENTOS: Ninguno de alto impacto programado hoy")

    if recent_releases:
        lines.append("\nPUBLICADOS HOY:")
        for ev in recent_releases:
            t      = ev.get("event_at", "")[:16].replace("T", " ")
            actual = ev.get("actual")
            fc     = ev.get("forecast")
            unit   = ev.get("unit", "")
            sp     = ev.get("surprise_pct")
            sp_str = f"Sorpresa: {sp:+.1f}%" if sp is not None else ""
            lines.append(
                f"  {t} UTC {ev.get('event_name', 'N/A')} — "
                f"Actual: {actual}{unit} vs Forecast: {fc}{unit} {sp_str}".rstrip()
            )

    if current_prices:
        lines.append("\nPRECIOS ACTUALES:")
        for sym, price in current_prices.items():
            if price is not None:
                fmt = f"{price:,.2f}" if isinstance(price, (int, float)) else str(price)
                lines.append(f"  {sym}: {fmt}")

    user_prompt = "\n".join(lines)

    # ── Claude call ──────────────────────────────────────────────────────────
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await claude_with_retry(
            client,
            model=settings.ai_model,
            max_tokens=400,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text   = msg.content[0].text.strip()
        tokens = msg.usage.input_tokens + msg.usage.output_tokens

        logger.info(
            "[DailyBriefing] generated | upcoming=%d released=%d | tokens=%d",
            len(upcoming_events), len(recent_releases), tokens,
        )

        result = {
            "briefing":       text,
            "model":          settings.ai_model,
            "tokens_used":    tokens,
            "upcoming_count": len(upcoming_events),
            "released_count": len(recent_releases),
            "generated_at":   datetime.now(UTC).isoformat(),
        }
        cache.set(cache_key, result, 600)  # 10 min cache
        return result

    except Exception as exc:
        logger.error("[DailyBriefing] Claude call failed after retries: %s", exc)
        return {
            "briefing": (
                "CONTEXTO: Servicio de análisis temporalmente no disponible — reintentar en 1-2 minutos.\n"
                "NARRATIVA: Los mercados siguen activos — revisar calendario y precios manualmente.\n"
                "CLAVE: Consultar panel de calendario para eventos de alto impacto del día.\n"
                "HORARIO: Ver sección Calendar para horarios exactos de cada release.\n"
                "CADENA: Sin análisis de correlación disponible en este momento.\n"
                "TRADING: Regla estándar: no operar 5 min antes ni 5 min después de cada dato.\n"
                "SESGO: NEUTRAL — sin suficientes datos para sesgo direccional ahora.\n"
                "ACCIÓN: ESPERAR — confirmar dirección con primer cierre de 5 min post-release."
            ),
            "model":          settings.ai_model,
            "tokens_used":    0,
            "upcoming_count": len(upcoming_events),
            "released_count": len(recent_releases),
            "generated_at":   datetime.now(UTC).isoformat(),
        }
