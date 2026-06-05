"""
AI Analysis Engine — Claude API with Smart Money / institutional methodology.
Every economic release triggers a Goldman Sachs-grade analysis in Spanish.
"""

import anthropic

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """Eres un trader macro en un banco Tier-1. Respondes ÚNICAMENTE en Español.
Exactamente 3 líneas. Sin introducciones. Sin markdown. Sin texto fuera de esas 3 líneas.

FORMATO EXACTO:
SEÑAL: Dato [alcista/bajista/neutral] para USD. [1 oración explicando por qué.]
XAUUSD: [sube/baja/neutral] — [1 oración con la implicación en precio.]
SESGO: [alcista/bajista/neutral] — [lectura operativa en 1 línea. O: SIN SETUP CLARO.]"""


async def analyze_event(event_data: dict) -> dict:
    """
    Generate institutional Smart Money analysis for an economic event.

    event_data keys: event_name, actual, forecast, previous, surprise_pct,
                     surprise_label, currency, importance, unit
    """
    if not settings.anthropic_api_key:
        return {
            "analysis": "⚠️ ANTHROPIC_API_KEY no configurada. Agrega tu clave en el archivo .env para activar el análisis IA.",
            "model": "none",
            "tokens_used": 0,
        }

    actual = event_data.get("actual")
    forecast = event_data.get("forecast")
    previous = event_data.get("previous")
    surprise_pct = event_data.get("surprise_pct", 0) or 0
    surprise_label = event_data.get("surprise_label", "N/A")
    unit = event_data.get("unit", "")

    def fmt(v):
        if v is None:
            return "N/D"
        return f"{v}{unit}" if unit else str(v)

    # Determine beat/miss label
    if surprise_pct > 5:
        beat_label = "BEAT FUERTE ▲"
    elif surprise_pct > 0:
        beat_label = "BEAT MODERADO ▲"
    elif surprise_pct == 0:
        beat_label = "IN LINE →"
    elif surprise_pct > -5:
        beat_label = "MISS MODERADO ▼"
    else:
        beat_label = "MISS FUERTE ▼"

    user_prompt = (
        f"Evento: {event_data.get('event_name', 'N/A')} | "
        f"Divisa: {event_data.get('currency', 'USD')}\n"
        f"Actual: {fmt(actual)} | Forecast: {fmt(forecast)} | Previo: {fmt(previous)}\n"
        f"Sorpresa: {surprise_pct:+.2f}% — {beat_label}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model=settings.ai_model,
            max_tokens=220,
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
            "analysis": analysis_text,
            "model": settings.ai_model,
            "tokens_used": tokens,
            "surprise_pct": surprise_pct,
            "beat_label": beat_label,
        }

    except Exception as exc:
        logger.error("AI analysis failed: %s", exc)
        return {
            "analysis": f"❌ Error al generar análisis: {exc}",
            "model": settings.ai_model,
            "tokens_used": 0,
        }


async def analyze_news_flash(article: dict) -> str:
    """Quick 3-line institutional take on a breaking news article."""
    if not settings.anthropic_api_key:
        return "ANTHROPIC_API_KEY no configurada."

    prompt = f"""NOTICIA BREAKING:
Título: {article.get('title', '')}
Fuente: {article.get('source', '')}
Resumen: {article.get('summary', '')[:500]}

En máximo 3 líneas: impacto en USD, XAUUSD y sentimiento de riesgo. Tono Bloomberg. Español."""

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as exc:
        logger.error("News flash analysis failed: %s", exc)
        return f"Error: {exc}"
