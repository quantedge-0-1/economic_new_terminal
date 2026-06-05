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
    """Parse the SEÑAL: line from analysis output."""
    for line in text.split("\n"):
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("SEÑAL:") or upper.startswith("SENAL:"):
            signal = stripped[stripped.index(":") + 1:].strip()
            return signal or None
    return None


_SYSTEM = """Eres un trader macro en un banco Tier-1. Respondes ÚNICAMENTE en Español.
Exactamente 4 líneas. Sin markdown. Sin líneas en blanco. Texto plano.
Copia los SCORES exactos del input en la línea 2. Usa el precio actual como ancla para los niveles.

FORMATO (4 líneas exactas):
SEÑAL: [ALCISTA/BAJISTA/NEUTRAL] [ORO/USD] — [evento dominante] [LARGE BEAT/BEAT/IN LINE/MISS] [+/-X%] + [N] eventos
SCORES: USD [+/-N] | XAUUSD [+/-N] | BONDS [+/-N] | RISK [+/-N]
PRECIO: [dirección] hacia [nivel]. Retroceso a [nivel] es la entrada.
ACCIÓN: [LONG/SHORT/ESPERAR] en [nivel] | Stop [nivel] | TP [nivel] | R:R [ratio]"""


async def analyze_consolidated(events: list[dict], impacts: dict | None = None) -> dict:
    """
    Generate one consolidated institutional analysis for N simultaneous events.

    events:  list of dicts with keys: event_name, actual, forecast, previous,
             unit, currency, weight, surprise_pct, surprise_label.
    impacts: pre-computed weighted impact scores from calculate_weighted_impacts().
             If None, scores are recomputed here.
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

    from app.services.prices.history import get_latest_price

    if impacts is None:
        impacts = calculate_weighted_impacts(events)

    scores_line = (
        f"USD {impacts.get('USD', 0):+.0f} | "
        f"XAUUSD {impacts.get('Gold', 0):+.0f} | "
        f"BONDS {impacts.get('Bond', 0):+.0f} | "
        f"RISK {impacts.get('Risk', 0):+.0f}"
    )

    xauusd_price = get_latest_price("XAUUSD")
    price_ctx = (
        f"Precio actual XAUUSD: {xauusd_price:,.2f}"
        if xauusd_price
        else "Precio XAUUSD: no disponible — escribe SIN DATOS en PRECIO y ACCIÓN"
    )

    sorted_ev = sorted(events, key=lambda e: e.get("weight", 3), reverse=True)
    event_lines = []
    for ev in sorted_ev:
        sp   = ev.get("surprise_pct")
        unit = ev.get("unit") or ""
        actual_str = f"{ev.get('actual')}{unit}" if ev.get("actual") is not None else "N/D"
        sp_str     = f"{sp:+.2f}%" if sp is not None else "N/A"
        label      = (ev.get("surprise_label") or "N/A").upper().replace("_", " ")
        event_lines.append(
            f"  [{ev.get('weight', 3)}/10] {ev['event_name']}: "
            f"Actual={actual_str} | Sorpresa={sp_str} ({label})"
        )

    n = len(events)
    prompt = (
        f"{n} RELEASES SIMULTÁNEOS:\n"
        f"{chr(10).join(event_lines)}\n"
        f"SCORES (copia exacto en línea 2): {scores_line}\n"
        f"{price_ctx}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=settings.ai_model,
            max_tokens=settings.ai_max_tokens,
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
