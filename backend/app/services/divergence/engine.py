"""
Divergence Detection Engine — identifies when price moves opposite to data expectations.

Smart Money concept: divergence between macro data and price action often signals
institutional accumulation/distribution before the real move.
"""

from app.core.logger import get_logger

logger = get_logger(__name__)

# Expected directional impact of a positive surprise on each asset
# +1 = positive surprise → bullish for asset
# -1 = positive surprise → bearish for asset
EXPECTED_IMPACT: dict[str, dict[str, int]] = {
    "NFP": {"USD": +1, "XAUUSD": -1, "US10Y": +1, "SPX": +1},
    "CPI": {"USD": +1, "XAUUSD": +1, "US10Y": -1, "SPX": -1},
    "GDP": {"USD": +1, "XAUUSD": -1, "US10Y": +1, "SPX": +1},
    "FOMC": {"USD": +1, "XAUUSD": -1, "US10Y": -1, "SPX": -1},
    "UNEMPLOYMENT": {"USD": -1, "XAUUSD": +1, "US10Y": -1, "SPX": -1},
    "RETAIL_SALES": {"USD": +1, "XAUUSD": -1, "US10Y": +1, "SPX": +1},
    "PCE": {"USD": +1, "XAUUSD": +1, "US10Y": -1, "SPX": -1},
    "ISM": {"USD": +1, "XAUUSD": -1, "US10Y": +1, "SPX": +1},
    "DEFAULT": {"USD": +1, "XAUUSD": -1, "US10Y": +1, "SPX": 0},
}

DIVERGENCE_LEVELS = {
    "strong": "⚠️ DIVERGENCIA FUERTE — posible trampa institucional",
    "moderate": "⚡ Divergencia moderada — monitorear",
    "none": "✅ Sin divergencia — acción de precio confirma dato",
}


def _get_event_key(event_name: str) -> str:
    name = event_name.upper()
    for key in EXPECTED_IMPACT:
        if key in name:
            return key
    return "DEFAULT"


def detect_divergence(
    event_name: str,
    surprise_pct: float,
    price_changes: dict[str, float],  # {"XAUUSD": +0.3, "USD": -0.1, ...}
) -> dict:
    """
    Compares actual price movement direction vs expected direction given the surprise.

    Returns divergence analysis per asset with Smart Money interpretation.
    """
    if abs(surprise_pct) < 0.5:
        return {
            "has_divergence": False,
            "level": "none",
            "message": "Sorpresa insuficiente para detectar divergencia (<0.5%)",
            "assets": {},
        }

    event_key = _get_event_key(event_name)
    expected = EXPECTED_IMPACT[event_key]
    surprise_direction = +1 if surprise_pct > 0 else -1

    asset_results = {}
    divergences_found = 0

    for asset, price_chg in price_changes.items():
        if asset not in expected:
            continue

        expected_dir = expected[asset] * surprise_direction
        actual_dir = +1 if price_chg > 0.05 else (-1 if price_chg < -0.05 else 0)

        if actual_dir == 0:
            divergence = False
            strength = "none"
        elif actual_dir != expected_dir:
            divergence = True
            divergences_found += 1
            strength = "strong" if abs(price_chg) > 0.3 else "moderate"
        else:
            divergence = False
            strength = "none"

        asset_results[asset] = {
            "expected_direction": "alcista" if expected_dir > 0 else "bajista",
            "actual_direction": "alcista" if actual_dir > 0 else ("bajista" if actual_dir < 0 else "lateral"),
            "price_change_pct": round(price_chg, 3),
            "is_divergence": divergence,
            "divergence_strength": strength,
            "smc_note": _smc_note(asset, divergence, strength, expected_dir),
        }

    overall_level = (
        "strong" if divergences_found >= 2 else
        "moderate" if divergences_found == 1 else
        "none"
    )

    return {
        "has_divergence": divergences_found > 0,
        "level": overall_level,
        "message": DIVERGENCE_LEVELS[overall_level],
        "event_key": event_key,
        "surprise_direction": "beat" if surprise_pct > 0 else "miss",
        "assets": asset_results,
        "smc_interpretation": _global_smc_note(divergences_found, surprise_pct, event_name),
    }


def _smc_note(asset: str, divergence: bool, strength: str, expected_dir: int) -> str:
    if not divergence:
        return f"{asset} confirma el dato — flujo institucional alineado"
    direction = "alcista" if expected_dir < 0 else "bajista"
    if strength == "strong":
        return (
            f"⚠️ {asset} se mueve {direction} contra el dato — posible Order Block institucional "
            f"siendo formado. Smart Money puede estar acumulando en dirección contraria al retail."
        )
    return (
        f"⚡ {asset} diverge levemente — monitorear BOS/CHoCH en temporalidad 15m-1h "
        f"para confirmar si hay absorción institucional."
    )


def _global_smc_note(count: int, surprise_pct: float, event_name: str) -> str:
    if count == 0:
        return (
            "Acción de precio confirma el dato macro. Momentum institucional alineado. "
            "Buscar continuación en dirección del dato en próximas 1-4h."
        )
    if count == 1:
        return (
            f"Una divergencia detectada en {event_name}. "
            "Smart Money puede estar usando el dato para distribuir posiciones contrarias al retail. "
            "Esperar retest de estructura antes de entrar."
        )
    return (
        f"DIVERGENCIA MÚLTIPLE — {count} activos se mueven contra el dato. "
        "Alta probabilidad de trampa institucional (liquidity sweep). "
        "NO perseguir el movimiento inicial. Esperar CHoCH en 15m y retest de Order Block."
    )
