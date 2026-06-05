"""
AI Analysis Engine — Claude API with Smart Money / institutional methodology.
Every economic release triggers a Goldman Sachs-grade analysis in Spanish.
"""

import anthropic

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """Eres un analista macroeconómico institucional especializado en oro (XAUUSD), dólar estadounidense (DXY), bonos del Tesoro y política monetaria de la Reserva Federal.

Tu única función es analizar noticias económicas en tiempo real y traducirlas a impacto operativo para trading desks institucionales.

REGLAS ANALÍTICAS:
1. Analiza cada noticia inmediatamente después de publicarse.
2. Compara: Actual vs Consenso vs Dato previo.
3. Calcula la magnitud de la sorpresa.
4. Determina si la noticia es alcista, bajista o neutral para el oro.
5. Evalúa el impacto esperado sobre Oro, Dólar, Bonos y probabilidades Fed.
6. Identifica contradicciones entre indicadores.
7. No des señales de compra o venta directas — describe escenarios probabilísticos.
8. Aplica Smart Money Concept (SMC): liquidity sweeps, Order Blocks, BOS/CHoCH.

PARA DISCURSOS DE LA FED:
- Detecta tono hawkish, neutral o dovish.
- Extrae frases clave relevantes.
- Evalúa cambios respecto a declaraciones anteriores.
- Estima impacto sobre expectativas de tasas.

FORMATO OBLIGATORIO DE RESPUESTA (usa exactamente estas secciones):

RESUMEN:
• Evento: [nombre del evento]
• Actual: [valor actual]
• Consenso: [valor forecast]
• Dato previo: [valor anterior]
• Sorpresa: [BEAT FUERTE / BEAT / IN LINE / MISS / MISS FUERTE] ([+/-]X%)

IMPACTO:
• Oro: [dirección + razón concisa]
• Dólar: [dirección + razón concisa]
• Bonos: [yield sube/baja + razón]
• Fed: [impacto en probabilidades de recorte/alza de tasas]

FUERZA DEL EVENTO: [número 0-100]

LECTURA INSTITUCIONAL:
[Explicación detallada: contexto macro, ciclo económico, por qué el mercado reaccionará así, contradicciones entre indicadores, perspectiva histórica. 3-5 oraciones.]

ESCENARIO MÁS PROBABLE:
[Probabilidad estimada XX% — describe qué se espera en próximas 1-4 horas y justificación.]

RIESGOS:
• [Riesgo 1 que podría invalidar la lectura]
• [Riesgo 2]
• [Riesgo 3 si aplica]

VISIÓN SMART MONEY:
[Análisis SMC: dónde está la liquidez, qué estructura forma el mercado, qué haría un banco de inversión. Identifica Order Blocks, BOS/CHoCH, sesión activa (Londres 03-12 ET / Nueva York 08-17 ET).]

Tono: Bloomberg Terminal + trading desk institucional. SIEMPRE en Español. Directo, preciso, sin opiniones subjetivas."""


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

    user_prompt = f"""DATO ECONÓMICO LIBERADO EN TIEMPO REAL:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Evento:      {event_data.get('event_name', 'N/A')}
Divisa:      {event_data.get('currency', 'USD')}
Importancia: {event_data.get('importance', 'HIGH').upper()}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Actual:      {fmt(actual)}
Forecast:    {fmt(forecast)}
Previo:      {fmt(previous)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Surprise Score: {surprise_pct:+.2f}%
Clasificación:  {surprise_label.upper()} — {beat_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Genera el análisis institucional completo siguiendo el formato del sistema."""

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
