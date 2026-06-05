"""
AI Analysis Engine — Claude API with Smart Money / institutional methodology.
Every economic release triggers a Goldman Sachs-grade analysis in Spanish.
"""

import anthropic

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """Eres un trader macro en un banco Tier-1. Respondes ÚNICAMENTE en Español.
Exactamente 4 líneas. Sin markdown. Sin líneas en blanco. Texto plano.
Copia los SCORES exactos del input en la línea 2. Usa el precio actual como ancla para los niveles.

FORMATO (4 líneas exactas):
SEÑAL: [ALCISTA/BAJISTA/NEUTRAL] [ORO/USD] — [nombre evento] [LARGE BEAT/BEAT/IN LINE/MISS/LARGE MISS] [+/-X%]
SCORES: USD [+/-N] | XAUUSD [+/-N] | BONDS [+/-N] | RISK [+/-N]
PRECIO: [dirección] hacia [nivel]. Retroceso a [nivel] es la entrada.
ACCIÓN: [LONG/SHORT/ESPERAR] en [nivel] | Stop [nivel] | TP [nivel] | R:R [ratio]"""


def _compute_scores(surprise_pct: float, currency: str) -> dict[str, int]:
    """Impact scores from a single event surprise — same formula as calculate_weighted_impacts."""
    norm = max(-100.0, min(100.0, surprise_pct * 2))
    if currency.upper() != "USD":
        return {"USD": 0, "XAUUSD": 0, "BONDS": 0, "RISK": 0}
    return {
        "USD":    round(norm),
        "XAUUSD": round(-norm * 0.8),
        "BONDS":  round(-norm * 0.7),
        "RISK":   round(norm * 0.6),
    }


def _beat_label(surprise_pct: float) -> str:
    if surprise_pct > 10:
        return "LARGE BEAT"
    if surprise_pct > 3:
        return "BEAT"
    if surprise_pct >= -3:
        return "IN LINE"
    if surprise_pct >= -10:
        return "MISS"
    return "LARGE MISS"


async def analyze_event(event_data: dict) -> dict:
    """
    Generate institutional 4-line analysis for an economic event.

    event_data keys: event_name, actual, forecast, previous, surprise_pct,
                     surprise_label, currency, importance, unit
    """
    if not settings.anthropic_api_key:
        return {
            "analysis": "⚠️ ANTHROPIC_API_KEY no configurada.",
            "model": "none",
            "tokens_used": 0,
        }

    from app.services.prices.history import get_latest_price

    actual      = event_data.get("actual")
    forecast    = event_data.get("forecast")
    previous    = event_data.get("previous")
    surprise_pct = event_data.get("surprise_pct", 0) or 0
    currency    = event_data.get("currency", "USD")
    unit        = event_data.get("unit", "")

    def fmt(v):
        return f"{v}{unit}" if v is not None else "N/D"

    beat        = _beat_label(surprise_pct)
    scores      = _compute_scores(surprise_pct, currency)
    scores_line = (
        f"USD {scores['USD']:+d} | "
        f"XAUUSD {scores['XAUUSD']:+d} | "
        f"BONDS {scores['BONDS']:+d} | "
        f"RISK {scores['RISK']:+d}"
    )

    xauusd_price = get_latest_price("XAUUSD")
    price_ctx = (
        f"Precio actual XAUUSD: {xauusd_price:,.2f}"
        if xauusd_price
        else "Precio XAUUSD: no disponible — escribe SIN DATOS en PRECIO y ACCIÓN"
    )

    user_prompt = (
        f"Evento: {event_data.get('event_name', 'N/A')} | {currency}\n"
        f"Actual: {fmt(actual)} | Forecast: {fmt(forecast)} | Previo: {fmt(previous)}\n"
        f"Sorpresa: {surprise_pct:+.2f}% — {beat}\n"
        f"SCORES (copia exacto en línea 2): {scores_line}\n"
        f"{price_ctx}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model=settings.ai_model,
            max_tokens=settings.ai_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        analysis_text = message.content[0].text
        tokens = message.usage.input_tokens + message.usage.output_tokens

        logger.info(
            "AI analysis completed | event=%s | tokens=%d",
            event_data.get("event_name"),
            tokens,
        )

        return {
            "analysis":    analysis_text,
            "model":       settings.ai_model,
            "tokens_used": tokens,
            "surprise_pct": surprise_pct,
            "beat_label":  beat,
        }

    except Exception as exc:
        logger.error("AI analysis failed: %s", exc)
        return {
            "analysis":    f"❌ Error al generar análisis: {exc}",
            "model":       settings.ai_model,
            "tokens_used": 0,
        }


async def analyze_news_flash(article: dict) -> str:
    """Quick 3-line institutional take on a breaking news article."""
    if not settings.anthropic_api_key:
        return "ANTHROPIC_API_KEY no configurada."

    prompt = (
        f"NOTICIA BREAKING:\n"
        f"Título: {article.get('title', '')}\n"
        f"Fuente: {article.get('source', '')}\n"
        f"Resumen: {article.get('summary', '')[:500]}\n\n"
        f"En máximo 3 líneas: impacto en USD, XAUUSD y sentimiento de riesgo. Tono Bloomberg. Español."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as exc:
        logger.error("News flash analysis failed: %s", exc)
        return f"Error: {exc}"
