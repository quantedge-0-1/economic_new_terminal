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
    "Eres un trader macro en un banco Tier-1. Respondes ÚNICAMENTE en Español. "
    "Exactamente 3 líneas. Sin introducciones. Sin markdown. Sin texto fuera de esas 3 líneas. "
    "FORMATO EXACTO: "
    "ESTADO: [descontado/no descontado/trampa]. "
    "POSICIONAMIENTO: [qué parecen estar haciendo las instituciones en 1 oración]. "
    "PLAN: [acción operativa concreta en 1 línea]."
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
        f"Evento: {event_name} | T-{minutes_to_release}min | {signals.symbol} @ {signals.current_price}\n"
        f"Zona: {signals.price_zone} | Bias: {signals.directional_bias:+.2f} | "
        f"Discount: {signals.discount_score:+.0f}/100\n"
        f"BSL: {signals.bsl} | EQ: {signals.equilibrium} | SSL: {signals.ssl}\n"
        f"Sweep: {swept_str} | Consolidando: {'SÍ' if signals.is_consolidating else 'NO'} | "
        f"Estado: {signals.state_label}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=220,
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
