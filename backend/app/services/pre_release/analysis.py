"""
Pre-Release AI Analysis — one Claude Haiku call per event activation window.

The result is cached for 5 minutes per event so repeated polls (every 30s)
do not trigger additional Claude calls. A single T-10 window costs 1 call.
"""

from __future__ import annotations

import anthropic

from app.core import cache
from app.core.config import settings
from app.core.logger import get_logger
from app.services.pre_release.engine import PreReleaseResult

logger = get_logger(__name__)

_SYSTEM = (
    "Eres un trader macro senior en un banco de inversión de primer nivel. "
    "Analizas condiciones pre-release usando Smart Money Concepts. "
    "Respondes ÚNICAMENTE en español. "
    "Tu respuesta es EXACTAMENTE 5 líneas numeradas (1. 2. 3. 4. 5.), "
    "sin markdown, sin texto adicional fuera de esas 5 líneas. "
    "Habla como un professional institucional: directo, preciso, sin adornos."
)


async def get_ai_analysis(
    event_name: str,
    event_at_str: str,
    signals: PreReleaseResult,
    minutes_to_release: int,
) -> str:
    """
    Returns a 5-line institutional analysis.
    Cached per (event_name, event_at) for 5 minutes.
    """
    cache_key = f"pre_release:ai:{event_name}:{event_at_str}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    if not settings.anthropic_api_key:
        return "API de Anthropic no configurada — análisis AI no disponible."

    disp_str = (
        f"{signals.displacement_10m_pct:+.3f}%"
        if signals.displacement_10m_pct is not None
        else "sin datos"
    )
    swept_str = (
        "BSL barrido — institucionales vendieron en el máximo"
        if signals.bsl_swept
        else "SSL barrido — institucionales compraron en el mínimo"
        if signals.ssl_swept
        else "sin sweep de liquidez detectado"
    )

    user_msg = (
        f"EVENTO INMINENTE: {event_name}  (T-{minutes_to_release} minutos)\n"
        f"Instrumento: {signals.symbol}   Precio actual: {signals.current_price}\n"
        f"Desplazamiento 10m: {disp_str}  Zona precio: {signals.price_zone}\n"
        f"BSL (max 30m): {signals.bsl}   SSL (min 30m): {signals.ssl}   "
        f"Equilibrio: {signals.equilibrium}\n"
        f"Sweep liquidez: {swept_str}\n"
        f"Consolidando: {'SÍ (<0.15% rango 20m)' if signals.is_consolidating else 'NO'}\n"
        f"Bias direccional: {signals.directional_bias:+.2f}   "
        f"Discount Score: {signals.discount_score:+.0f}/100\n"
        f"Estado institucional: {signals.state_label}\n\n"
        f"Responde exactamente:\n"
        f"1. Estado actual: ¿el mercado ha descontado el evento o no?\n"
        f"2. Posicionamiento institucional aparente\n"
        f"3. Reacción esperada POST-release dado el posicionamiento\n"
        f"4. Niveles clave a vigilar (BSL {signals.bsl} / EQ {signals.equilibrium} / SSL {signals.ssl})\n"
        f"5. Acción concreta recomendada al trader"
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=450,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        cache.set(cache_key, text, 300)   # 5-min TTL per event window
        logger.info("[PreRelease AI] analysis generated for '%s'", event_name)
        return text
    except Exception as exc:
        logger.error("[PreRelease AI] failed: %s", exc)
        error_msg = (
            f"1. Error al conectar con Claude API: {exc}\n"
            f"2. Revisar ANTHROPIC_API_KEY en .env\n"
            f"3. Usar señales de precio del panel como referencia\n"
            f"4. BSL: {signals.bsl} | EQ: {signals.equilibrium} | SSL: {signals.ssl}\n"
            f"5. Estado: {signals.state_label} — {signals.trader_action}"
        )
        return error_msg
