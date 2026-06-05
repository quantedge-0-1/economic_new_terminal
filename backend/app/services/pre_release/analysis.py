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
    "Exactamente 4 líneas. Sin markdown. Sin líneas en blanco. Texto plano. "
    "Usa los niveles BSL/EQ/SSL del input como ancla para PRECIO y ACCIÓN. "
    "FORMATO (4 líneas exactas): "
    "SEÑAL: [DESCONTADO/NO DESCONTADO/TRAMPA] [ORO/USD] — [evento] en T-[N]min. "
    "SCORES: Bias [+/-N] | Discount [+/-N/100] | Estado [label]. "
    "PRECIO: [dirección] hacia [BSL o SSL]. Entrada en zona [nivel]. "
    "ACCIÓN: [LONG/SHORT/ESPERAR] en [nivel] | Stop [nivel] | TP [nivel] | R:R [ratio]"
)


async def get_ai_analysis(
    event_name: str,
    event_at_str: str,
    signals: PreReleaseResult,
    minutes_to_release: int,
) -> str:
    """
    Returns a 4-line pre-release institutional analysis.
    Cached per (event_name, event_at) for 5 minutes.
    """
    cache_key = f"pre_release:ai:{event_name}:{event_at_str}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    if not settings.anthropic_api_key:
        return "API de Anthropic no configurada — análisis AI no disponible."

    swept_str = (
        "BSL barrido"
        if signals.bsl_swept
        else "SSL barrido"
        if signals.ssl_swept
        else "sin sweep"
    )

    user_msg = (
        f"Evento: {event_name} | T-{minutes_to_release}min\n"
        f"{signals.symbol} @ {signals.current_price} | Zona: {signals.price_zone}\n"
        f"BSL: {signals.bsl} | EQ: {signals.equilibrium} | SSL: {signals.ssl}\n"
        f"Bias: {signals.directional_bias:+.2f} | Discount: {signals.discount_score:+.0f}/100 | "
        f"Sweep: {swept_str} | Estado: {signals.state_label}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=settings.ai_max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        cache.set(cache_key, text, 300)
        logger.info("[PreRelease AI] analysis generated for '%s'", event_name)
        return text
    except Exception as exc:
        logger.error("[PreRelease AI] failed: %s", exc)
        return (
            f"SEÑAL: ERROR — no se pudo conectar con Claude API.\n"
            f"SCORES: Bias {signals.directional_bias:+.2f} | Discount {signals.discount_score:+.0f}/100 | {signals.state_label}\n"
            f"PRECIO: BSL {signals.bsl} | EQ {signals.equilibrium} | SSL {signals.ssl}\n"
            f"ACCIÓN: {signals.trader_action}"
        )
