"""
Institutional Sentiment Engine — ISS for XAUUSD.

NSS (News Sentiment Score 0-100): Claude classifies news impact on Gold.
MCS (Market Confirmation Score 0-100): real-time price confirmation across
    1m / 5m / 15m / 30m windows for XAUUSD, DXY, US10Y, VIX.
ISS = 60% × NSS + 40% × MCS

Classification:
  85-100 → EXTREME BULLISH
  70-84  → BULLISH
  55-69  → MODERATELY BULLISH
  45-54  → NEUTRAL
  30-44  → BEARISH
  0-29   → EXTREME BEARISH

Divergence alerts:
  NSS > 70 and MCS < 40 → "Posible trampa institucional"
  NSS < 40 and MCS > 70 → "Posible acumulación institucional"
"""

from __future__ import annotations

import json

import anthropic

from app.core.config import settings
from app.core.logger import get_logger
from app.services.prices.history import get_price_change_pct, history_depth_seconds

logger = get_logger(__name__)

# ── Classification table ───────────────────────────────────────────────────────

_ISS_CLASSES = [
    (85, "EXTREME BULLISH",    "#00ff88"),
    (70, "BULLISH",            "#00d4aa"),
    (55, "MODERATELY BULLISH", "#66ffaa"),
    (45, "NEUTRAL",            "#4090ff"),
    (30, "BEARISH",            "#ff4455"),
    (0,  "EXTREME BEARISH",    "#cc0011"),
]

# ── NSS (News Sentiment Score) ─────────────────────────────────────────────────

_NSS_SYSTEM = """Eres un clasificador de sentimiento institucional especializado en oro (XAUUSD).
Analiza el evento económico y determina su impacto sobre el oro.

Responde ÚNICAMENTE con un objeto JSON válido (sin markdown, sin texto fuera del JSON):
{
  "sentiment": "bullish_gold" | "bearish_gold" | "neutral",
  "strength": <entero 0-100>,
  "confidence": <entero 0-100>,
  "bull_probability": <entero 0-100>,
  "bear_probability": <entero 0-100>,
  "explanation": "<máximo 2 oraciones en Español>"
}"""


async def compute_nss(event_data: dict) -> dict:
    """Call Claude Haiku to get News Sentiment Score for Gold."""
    if not settings.anthropic_api_key:
        return _neutral_nss("ANTHROPIC_API_KEY no configurada")

    surprise_pct = event_data.get("surprise_pct") or 0
    user_msg = (
        f"Evento: {event_data.get('event_name')}\n"
        f"Actual: {event_data.get('actual')} | "
        f"Consenso: {event_data.get('forecast')} | "
        f"Previo: {event_data.get('previous')}\n"
        f"Sorpresa: {surprise_pct:+.2f}%\n"
        f"Moneda: {event_data.get('currency', 'USD')}"
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_NSS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()

        # Strip markdown fences if present
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                if "{" in part:
                    text = part.lstrip("json").strip()
                    break

        data = json.loads(text)
        return {
            "sentiment":        data.get("sentiment", "neutral"),
            "strength":         int(data.get("strength", 50)),
            "confidence":       int(data.get("confidence", 50)),
            "bull_probability": int(data.get("bull_probability", 50)),
            "bear_probability": int(data.get("bear_probability", 50)),
            "explanation":      data.get("explanation", ""),
        }

    except json.JSONDecodeError as exc:
        logger.warning("NSS JSON parse failed: %s", exc)
        return _neutral_nss("Error al parsear respuesta Claude")
    except Exception as exc:
        logger.error("NSS computation failed: %s", exc)
        return _neutral_nss(str(exc))


# ── MCS (Market Confirmation Score) ───────────────────────────────────────────

# Expected direction per asset given bullish_gold / bearish_gold sentiment
# +1 = should go UP, -1 = should go DOWN
_EXPECTED_DIRECTIONS: dict[str, dict[str, int]] = {
    "bullish_gold":  {"XAUUSD": +1, "DXY": -1, "US10Y": -1, "VIX": +1},
    "bearish_gold":  {"XAUUSD": -1, "DXY": +1, "US10Y": +1, "VIX": -1},
    "neutral":       {"XAUUSD":  0, "DXY":  0, "US10Y":  0, "VIX":  0},
}

_WINDOWS = [("1m", 60), ("5m", 300), ("15m", 900), ("30m", 1800)]


def compute_mcs(nss_sentiment: str) -> dict:
    """
    Compare price movements across 4 time windows against NSS direction.
    Returns MCS score 0-100 and per-window breakdown.
    """
    expected = _EXPECTED_DIRECTIONS.get(nss_sentiment, _EXPECTED_DIRECTIONS["neutral"])
    windows: dict[str, dict] = {}
    total_points = 0
    max_points = 0

    for win_label, secs in _WINDOWS:
        win_assets: dict[str, dict] = {}
        for symbol, exp_dir in expected.items():
            chg = get_price_change_pct(symbol, secs)
            if chg is None:
                win_assets[symbol] = {"change_pct": None, "confirms": None}
                continue

            actual_dir = +1 if chg > 0.05 else (-1 if chg < -0.05 else 0)
            if exp_dir != 0:
                max_points += 1
                confirms = actual_dir == exp_dir
                if confirms:
                    total_points += 1
            else:
                confirms = True  # neutral — counts as confirm

            win_assets[symbol] = {
                "change_pct":  round(chg, 4),
                "expected":    "up" if exp_dir > 0 else ("down" if exp_dir < 0 else "flat"),
                "actual":      "up" if actual_dir > 0 else ("down" if actual_dir < 0 else "flat"),
                "confirms":    confirms,
            }
        windows[win_label] = win_assets

    score = round((total_points / max_points) * 100) if max_points > 0 else 50
    return {
        "score":          score,
        "windows":        windows,
        "total_points":   total_points,
        "max_points":     max_points,
        "data_available": max_points > 0,
        "history_depth":  history_depth_seconds(),
    }


# ── ISS (Institutional Sentiment Score) ───────────────────────────────────────

async def compute_iss(event_data: dict) -> dict:
    """Full ISS: NSS + MCS → composite score, classification, divergence alert."""
    nss_data = await compute_nss(event_data)
    mcs_data = compute_mcs(nss_data["sentiment"])

    nss_score = _sentiment_to_score(nss_data)
    mcs_score = mcs_data["score"] if mcs_data["data_available"] else 50

    iss = round(nss_score * 0.6 + mcs_score * 0.4)
    iss = max(0, min(100, iss))
    classification = _classify_iss(iss)

    # Divergence alerts
    divergence_alert = None
    if nss_score > 70 and mcs_score < 40:
        divergence_alert = {
            "type":    "institutional_trap",
            "message": "⚠️ POSIBLE TRAMPA INSTITUCIONAL — Noticia bullish pero precio no confirma. Smart Money puede estar distribuyendo contra el retail.",
        }
    elif nss_score < 40 and mcs_score > 70:
        divergence_alert = {
            "type":    "institutional_accumulation",
            "message": "🔄 POSIBLE ACUMULACIÓN INSTITUCIONAL — Mercado alcista sin respaldo noticioso. Monitorear Order Blocks para entrada.",
        }

    return {
        "iss":               iss,
        "classification":    classification,
        "sesgo":             _sesgo(nss_data["sentiment"]),
        "intensidad":        _intensidad(iss),
        "nss": {
            **nss_data,
            "score": nss_score,
        },
        "mcs":               mcs_data,
        "divergence_alert":  divergence_alert,
        "event_name":        event_data.get("event_name"),
        "formula":           f"ISS = {nss_score}×0.6 + {mcs_score}×0.4 = {iss}",
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sentiment_to_score(nss: dict) -> int:
    """Map sentiment + strength → 0-100 score (50 = neutral)."""
    s = nss["sentiment"]
    strength = nss["strength"]
    if s == "bullish_gold":
        return min(100, 50 + round(strength / 2))
    if s == "bearish_gold":
        return max(0, 50 - round(strength / 2))
    return 50


def _classify_iss(score: int) -> dict:
    for threshold, label, color in _ISS_CLASSES:
        if score >= threshold:
            return {"label": label, "color": color, "threshold": threshold}
    return {"label": "EXTREME BEARISH", "color": "#cc0011", "threshold": 0}


def _sesgo(sentiment: str) -> str:
    return {
        "bullish_gold": "ALCISTA ORO",
        "bearish_gold": "BAJISTA ORO",
        "neutral":      "NEUTRAL",
    }.get(sentiment, "NEUTRAL")


def _intensidad(iss: int) -> str:
    if iss >= 85 or iss <= 15:
        return "EXTREMA"
    if iss >= 70 or iss <= 30:
        return "ALTA"
    if iss >= 55 or iss <= 45:
        return "MODERADA"
    return "BAJA"


def _neutral_nss(reason: str) -> dict:
    return {
        "sentiment":        "neutral",
        "strength":         0,
        "confidence":       0,
        "bull_probability": 50,
        "bear_probability": 50,
        "explanation":      reason,
    }
