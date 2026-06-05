"""
ConsolidatedAnalysisService — groups simultaneous economic releases and generates
a single weighted institutional analysis from one Claude API call.

Used when NFP day drops 3-4 indicators at the same minute.
"""

from __future__ import annotations

import anthropic

from app.core import cache
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

# Institutional importance hierarchy (1–10)
EVENT_WEIGHTS: dict[str, int] = {
    "nonfarm payrolls": 10, "nfp": 10,
    "fomc": 10, "federal funds rate": 10,
    "cpi": 9, "consumer price index": 9,
    "core cpi": 9, "core consumer price index": 9,
    "gdp": 8, "gross domestic product": 8,
    "core pce": 8,
    "pce": 7,
    "unemployment rate": 7, "unemployment": 7,
    "retail sales": 6,
    "ism": 5, "adp": 5, "adp nonfarm": 5,
    "ppi": 4, "producer price index": 4,
}


def get_event_weight(event_name: str) -> int:
    """Return institutional importance weight (1–10) for an event name."""
    name_lower = event_name.lower()
    for key, weight in EVENT_WEIGHTS.items():
        if key in name_lower:
            return weight
    return 3  # default


def group_simultaneous_events(
    events: list[dict], window_minutes: int = 5
) -> list[list[dict]]:
    """Group events whose timestamps fall within the same N-minute window."""
    if not events:
        return []

    from datetime import datetime

    def parse_dt(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    sorted_ev = sorted(events, key=lambda e: parse_dt(e["event_at"]))
    groups: list[list[dict]] = []
    current = [sorted_ev[0]]

    for ev in sorted_ev[1:]:
        anchor    = parse_dt(current[0]["event_at"])
        candidate = parse_dt(ev["event_at"])
        if abs((candidate - anchor).total_seconds()) <= window_minutes * 60:
            current.append(ev)
        else:
            groups.append(current)
            current = [ev]

    groups.append(current)
    return groups


def calculate_weighted_impacts(events: list[dict]) -> dict[str, float]:
    """
    Weighted net impact scores for USD/Gold/Bond/Risk.
    Range: -100 (max bearish for USD) to +100 (max bullish for USD).
    Gold is inverse: strong USD data → bearish Gold.
    """
    accum = {"USD": 0.0, "Gold": 0.0, "Bond": 0.0, "Risk": 0.0}
    total_weight = 0

    for ev in events:
        weight       = ev.get("weight", 3)
        surprise_pct = ev.get("surprise_pct") or 0.0
        currency     = (ev.get("currency") or "USD").upper()

        # Clamp surprise to ±100 and scale
        norm = max(-100.0, min(100.0, surprise_pct * 2))

        if currency == "USD":
            accum["USD"]  += norm * weight
            accum["Gold"] += -norm * weight          # inverse to USD
            accum["Bond"] += -norm * 0.7 * weight    # strong data → yields rise
            accum["Risk"] += norm * 0.5 * weight     # strong data → risk-on

        total_weight += weight

    if total_weight > 0:
        return {k: round(v / total_weight, 1) for k, v in accum.items()}
    return {k: 0.0 for k in accum}


def _extract_net_signal(text: str) -> str | None:
    """Parse the NET SIGNAL: line from analysis output."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("NET SIGNAL:"):
            signal = stripped[len("NET SIGNAL:"):].strip()
            return signal or None
    return None


_SYSTEM = """Eres un trader macro en un banco Tier-1. Respondes ÚNICAMENTE en Español.
Exactamente 4 líneas. Sin introducciones. Sin markdown. Sin texto fuera de esas 4 líneas.
CRÍTICO: los eventos van TODOS en la línea 2, separados por " | ".

FORMATO EXACTO (4 líneas, ni una más):
LÍNEA 1 — NET SIGNAL: [activo principal] [alcista/bajista/neutral] dominado por [evento de mayor peso].
LÍNEA 2 — DATOS: [EVENTO1]: [impacto 4 palabras] | [EVENTO2]: [impacto 4 palabras] | ...
LÍNEA 3 — PRECIO: [movimiento esperado con dirección y nivel estimado].
LÍNEA 4 — SESGO: [lectura operativa concreta en 1 línea]."""


async def analyze_consolidated(events: list[dict]) -> dict:
    """
    Generate one consolidated institutional analysis for N simultaneous events.

    events: list of dicts with keys: event_name, actual, forecast, previous,
            unit, currency, weight, surprise_pct, surprise_label.
    """
    ids = sorted(str(ev.get("id", ev["event_name"])) for ev in events)
    cache_key = f"analysis:consolidated:{':'.join(ids)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    if not settings.anthropic_api_key:
        return {
            "analysis": "⚠️ ANTHROPIC_API_KEY no configurada.",
            "model": "none",
            "tokens_used": 0,
            "net_signal": None,
        }

    sorted_ev = sorted(events, key=lambda e: e.get("weight", 3), reverse=True)

    lines = []
    for ev in sorted_ev:
        w          = ev.get("weight", 3)
        sp         = ev.get("surprise_pct")
        unit       = ev.get("unit") or ""
        actual_str   = f"{ev.get('actual')}{unit}" if ev.get("actual") is not None else "N/D"
        forecast_str = f"{ev.get('forecast')}{unit}" if ev.get("forecast") is not None else "N/D"
        sp_str       = f"{sp:+.2f}%" if sp is not None else "N/A"
        label        = (ev.get("surprise_label") or "N/A").upper()
        lines.append(
            f"  [{w}/10] {ev['event_name']}: "
            f"Actual={actual_str} | Forecast={forecast_str} | "
            f"Surprise={sp_str} ({label})"
        )

    n = len(events)
    prompt = (
        f"BATCH DE DATOS ECONÓMICOS — {n} RELEASES SIMULTÁNEOS\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{chr(10).join(lines)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Estos {n} indicadores se publicaron en la misma ventana de 5 minutos.\n"
        f"Genera el análisis institucional CONSOLIDADO del impacto neto."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=settings.ai_model,
            max_tokens=250,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text   = msg.content[0].text
        tokens = msg.usage.input_tokens + msg.usage.output_tokens

        logger.info("[Consolidated] %d simultaneous events | tokens=%d", n, tokens)

        result = {
            "analysis":    text,
            "model":       settings.ai_model,
            "tokens_used": tokens,
            "net_signal":  _extract_net_signal(text),
        }
        cache.set(cache_key, result, 300)
        return result

    except Exception as exc:
        logger.error("[Consolidated] Claude call failed: %s", exc)
        return {
            "analysis":    f"❌ Error al generar análisis consolidado: {exc}",
            "model":       settings.ai_model,
            "tokens_used": 0,
            "net_signal":  None,
        }
