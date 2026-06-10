"""
Pre-Release AI Analysis — one Claude Haiku call per event activation window.

The result is cached for 5 minutes per event so repeated polls (every 30s)
do not trigger additional Claude calls. A single T-10 window costs 1 call.
"""

from __future__ import annotations

import anthropic

from app.core import cache
from app.core.claude_retry import claude_with_retry
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

_POST_SYSTEM = (
    "Eres un trader macro en un banco Tier-1. Respondes ÚNICAMENTE en Español. "
    "Exactamente 3 líneas. Sin markdown. Sin líneas en blanco. Texto plano. "
    "FORMATO (3 líneas exactas): "
    "RESULTADO: [POSITIVO/NEGATIVO/NEUTRO] — [evento]: Real [actual] vs Pronóstico [forecast] ([sorpresa en %]). "
    "REACCIÓN: [alcista/bajista/neutral] para ORO. [Breve explicación macro 1 frase]. "
    "ACCIÓN: [LONG/SHORT/ESPERAR] | Esperar [N] velas de confirmación post-release."
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
    # Bucket by 2-min windows so analysis refreshes ~5 times during the 10-min window
    minutes_bucket = (minutes_to_release // 2) * 2
    cache_key = f"pre_release:ai:{event_name}:{event_at_str}:{minutes_bucket}"
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
        resp = await claude_with_retry(
            client,
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
        logger.error("[PreRelease AI] failed after retries: %s", exc)
        return (
            f"SEÑAL: NEUTRAL — Análisis no disponible temporalmente.\n"
            f"SCORES: Bias {signals.directional_bias:+.2f} | Discount {signals.discount_score:+.0f}/100 | {signals.state_label}\n"
            f"PRECIO: BSL {signals.bsl} | EQ {signals.equilibrium} | SSL {signals.ssl}\n"
            f"ACCIÓN: ESPERAR — usar niveles de precio como referencia."
        )


async def get_post_release_ai_analysis(
    event_name: str,
    event_at_str: str,
    actual: str | None,
    forecast: str | None,
    currency: str,
    minutes_since: int,
) -> str:
    """
    Returns a 3-line post-release reaction analysis. Cached per event (no re-generation).
    """
    cache_key = f"post_release:ai:{event_name}:{event_at_str}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    if not settings.anthropic_api_key:
        text = (
            f"RESULTADO: PENDIENTE — {event_name}: Real {actual or '?'} vs Pronóstico {forecast or '?'}.\n"
            f"REACCIÓN: Evaluar impacto en ORO vs USD manualmente.\n"
            f"ACCIÓN: ESPERAR — confirmar dirección con cierre de 2 velas post-release."
        )
        if actual is not None:
            cache.set(cache_key, text, 300)
        return text

    surprise_str = "sin pronóstico previo"
    if actual is not None and forecast is not None:
        try:
            surp = ((float(actual) - float(forecast)) / abs(float(forecast))) * 100
            surprise_str = f"{surp:+.1f}% vs pronóstico"
        except (ValueError, ZeroDivisionError):
            surprise_str = f"Real {actual} vs Pronóstico {forecast}"

    user_msg = (
        f"Evento: {event_name} ({currency}) | T+{minutes_since}min post-release\n"
        f"Dato real: {actual or 'N/D'} | Pronóstico: {forecast or 'N/D'} | Sorpresa: {surprise_str}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await claude_with_retry(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=180,
            system=_POST_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        # Only cache when we have real data — if actual is None, retry on next poll
        if actual is not None:
            cache.set(cache_key, text, 300)
        logger.info("[PostRelease AI] analysis generated for '%s'", event_name)
        return text
    except Exception as exc:
        logger.error("[PostRelease AI] failed: %s", exc)
        return (
            f"RESULTADO: {event_name}: Real {actual or '?'} vs Pronóstico {forecast or '?'}.\n"
            f"REACCIÓN: Evaluar impacto en ORO manualmente.\n"
            f"ACCIÓN: ESPERAR — confirmar dirección con cierre de 2 velas."
        )
