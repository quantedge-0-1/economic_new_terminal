"""
Pre-Release Market Discount Detection Engine.

Activates T-10 minutes before any high-impact economic event.
Uses ONLY the existing in-memory rolling price history — zero new API calls.

Signal weights (Discount Score -100 to +100):
  35%  Price displacement   — how far XAU moved in the last 10 min
  30%  Liquidity sweep      — was BSL/SSL tagged and reversed?
  20%  Directional bias     — sequential tick direction last 10 min
  15%  Consolidation        — tight range (<0.15%) = institutional silence

Institutional States:
  ALREADY_DISCOUNTED_BULLISH   — big up move + SSL swept → sell-the-news risk
  ALREADY_DISCOUNTED_BEARISH   — big down move + BSL swept → buy-the-news risk
  CONSOLIDATION_ACCUMULATION   — flat range → explosive move after release
  TRAP_SETUP_DETECTED          — strong move that stalled → distribution signal
  NOT_DISCOUNTED_NEUTRAL       — equilibrium → trade with the data
  INSUFFICIENT_DATA            — < 4 price snapshots in buffer
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from app.core.logger import get_logger
from app.services.prices.history import _price_history, get_price_change_pct

logger = get_logger(__name__)

InstitutionalState = Literal[
    "ALREADY_DISCOUNTED_BULLISH",
    "ALREADY_DISCOUNTED_BEARISH",
    "CONSOLIDATION_ACCUMULATION",
    "NOT_DISCOUNTED_NEUTRAL",
    "TRAP_SETUP_DETECTED",
    "INSUFFICIENT_DATA",
]

_STATE_CONFIG: dict[str, dict] = {
    "ALREADY_DISCOUNTED_BULLISH": {
        "label":  "DESCONTADO ALCISTA",
        "color":  "#ff4444",
        "note":   "Institucionales ya compraron. Retail comprará al dato → distribución probable.",
        "action": "ESPERAR_REVERSIÓN — No perseguir el alza inicial. Buscar CHoCH bajista post-release.",
    },
    "ALREADY_DISCOUNTED_BEARISH": {
        "label":  "DESCONTADO BAJISTA",
        "color":  "#ff4444",
        "note":   "Institucionales ya vendieron. Retail venderá al dato → rebote técnico probable.",
        "action": "ESPERAR_REVERSIÓN — No vender el break. Buscar CHoCH alcista post-release.",
    },
    "CONSOLIDATION_ACCUMULATION": {
        "label":  "ACUMULACIÓN SILENCIOSA",
        "color":  "#f0c040",
        "note":   "Rango comprimido (<0.15%). Smart Money acumulando. El dato generará movimiento explosivo.",
        "action": "ESPERAR_BREAKOUT — Entrar en dirección del primer cierre de 2 velas post-release.",
    },
    "TRAP_SETUP_DETECTED": {
        "label":  "TRAMPA INSTITUCIONAL",
        "color":  "#ff8800",
        "note":   "Movimiento fuerte previo ahora estancado. Posible distribución contra la dirección.",
        "action": "MÁXIMA_PRECAUCIÓN — Esperar 3 velas de confirmación antes de cualquier entrada.",
    },
    "NOT_DISCOUNTED_NEUTRAL": {
        "label":  "NO DESCONTADO",
        "color":  "#4090ff",
        "note":   "Mercado en equilibrio. El dato real moverá el precio desde aquí.",
        "action": "OPERAR_CON_EL_DATO — Confirmar dirección en cierre 2m post-release.",
    },
    "INSUFFICIENT_DATA": {
        "label":  "DATOS INSUFICIENTES",
        "color":  "#666666",
        "note":   "Historial de precios insuficiente. Se necesitan al menos 3 min de datos.",
        "action": "ESPERAR — Mantener el terminal activo 15 min antes del próximo evento.",
    },
}


@dataclass
class PreReleaseResult:
    symbol: str
    current_price: float | None
    bsl: float | None          # Buy-side liquidity: 30-min high
    ssl: float | None          # Sell-side liquidity: 30-min low
    equilibrium: float | None  # Midpoint of 30-min range

    displacement_10m_pct: float | None
    displacement_30m_pct: float | None
    range_30m_pct: float | None
    price_zone: str | None                # PREMIUM / EQUILIBRIUM / DISCOUNT
    is_consolidating: bool
    directional_bias: float               # -1.0 → +1.0
    bsl_swept: bool
    ssl_swept: bool
    history_depth_s: int

    displacement_score: float
    sweep_score: float
    structure_score: float
    consolidation_score: float
    discount_score: float                 # composite -100 → +100

    institutional_state: InstitutionalState
    state_label: str
    state_color: str
    smc_note: str
    trader_action: str


def analyze_pre_release(symbol: str = "XAUUSD") -> PreReleaseResult:
    """
    Derive all pre-release signals from the rolling price history buffer.
    No external API calls — uses data already collected by the prices poller.
    """
    snapshots = list(_price_history.get(symbol) or [])

    if len(snapshots) < 4:
        cfg = _STATE_CONFIG["INSUFFICIENT_DATA"]
        return PreReleaseResult(
            symbol=symbol, current_price=None, bsl=None, ssl=None, equilibrium=None,
            displacement_10m_pct=None, displacement_30m_pct=None, range_30m_pct=None,
            price_zone=None, is_consolidating=False, directional_bias=0.0,
            bsl_swept=False, ssl_swept=False, history_depth_s=0,
            displacement_score=0.0, sweep_score=0.0,
            structure_score=0.0, consolidation_score=0.0, discount_score=0.0,
            institutional_state="INSUFFICIENT_DATA",
            state_label=cfg["label"], state_color=cfg["color"],
            smc_note=cfg["note"], trader_action=cfg["action"],
        )

    now = time.monotonic()
    current_price = snapshots[-1][1]
    history_depth_s = int(now - snapshots[0][0])

    # ── 30-min range: BSL (max) / SSL (min) / equilibrium ────────────────────
    prices_30m = [p for ts, p in snapshots if ts >= now - 1800] or [p for _, p in snapshots]
    bsl = max(prices_30m)
    ssl = min(prices_30m)
    equilibrium = (bsl + ssl) / 2.0
    total_range = bsl - ssl
    range_30m_pct = round(total_range / equilibrium * 100, 4) if equilibrium > 0 else None

    # ── Price zone (position within 30-min range) ─────────────────────────────
    if total_range > 0:
        pos = (current_price - ssl) / total_range
        if pos >= 0.67:
            price_zone = "PREMIUM"
        elif pos <= 0.33:
            price_zone = "DISCOUNT"
        else:
            price_zone = "EQUILIBRIUM"
    else:
        price_zone = "EQUILIBRIUM"

    # ── Consolidation: range of last 20 min < 0.15% ───────────────────────────
    prices_20m = [p for ts, p in snapshots if ts >= now - 1200]
    if len(prices_20m) >= 3:
        h20 = max(prices_20m)
        l20 = min(prices_20m)
        m20 = (h20 + l20) / 2.0
        is_consolidating = (h20 - l20) / m20 * 100 < 0.15 if m20 > 0 else False
    else:
        is_consolidating = False

    # ── Displacement ──────────────────────────────────────────────────────────
    disp_10m = get_price_change_pct(symbol, 600)
    disp_30m = get_price_change_pct(symbol, 1800)

    # ── Directional bias: sequential up/down ticks in last 10 min ────────────
    recent_10m = [p for ts, p in snapshots if ts >= now - 600]
    if len(recent_10m) >= 3:
        pairs = list(zip(recent_10m, recent_10m[1:]))
        ups   = sum(1 for a, b in pairs if b > a)
        downs = sum(1 for a, b in pairs if b < a)
        total = ups + downs
        bias  = (ups - downs) / total if total > 0 else 0.0
    else:
        bias = 0.0

    # ── Liquidity sweep detection ─────────────────────────────────────────────
    # Historical baseline: snapshots from 10-30 min ago (before the recent window)
    hist_prices  = [p for ts, p in snapshots if ts < now - 600]
    recent_ts    = [(ts, p) for ts, p in snapshots if ts >= now - 600]

    bsl_swept = False
    ssl_swept = False

    if hist_prices and len(recent_ts) >= 2:
        hist_high = max(hist_prices)
        hist_low  = min(hist_prices)
        tol_hi = hist_high * 0.0005   # 0.05% tolerance
        tol_lo = hist_low  * 0.0005

        recent_p = [p for _, p in recent_ts]
        # BSL sweep: price tagged hist_high in the recent window and came back down
        bsl_swept = (
            any(p >= hist_high - tol_hi for p in recent_p[:-1])
            and recent_p[-1] < hist_high
        )
        # SSL sweep: price tagged hist_low in the recent window and bounced back up
        ssl_swept = (
            any(p <= hist_low + tol_lo for p in recent_p[:-1])
            and recent_p[-1] > hist_low
        )

    # ── Score computation ─────────────────────────────────────────────────────
    d = disp_10m or 0.0

    # 1. Displacement (35%): ±0.5% → ±100
    displacement_score = max(-100.0, min(100.0, d / 0.5 * 100.0))

    # 2. Sweep (30%): BSL swept = bearish (-75), SSL swept = bullish (+75)
    if ssl_swept and not bsl_swept:
        sweep_score = +75.0
    elif bsl_swept and not ssl_swept:
        sweep_score = -75.0
    else:
        sweep_score = 0.0

    # 3. Directional structure (20%)
    structure_score = bias * 100.0

    # 4. Consolidation (15%): flat = 0 (no directional info)
    consolidation_score = 0.0 if is_consolidating else displacement_score * 0.5

    discount_score = round(
        displacement_score  * 0.35 +
        sweep_score         * 0.30 +
        structure_score     * 0.20 +
        consolidation_score * 0.15,
        1,
    )
    discount_score = max(-100.0, min(100.0, discount_score))

    # ── Classify institutional state ──────────────────────────────────────────
    state = _classify(discount_score, d, is_consolidating, bsl_swept, ssl_swept)
    cfg = _STATE_CONFIG[state]

    return PreReleaseResult(
        symbol=symbol,
        current_price=round(current_price, 2),
        bsl=round(bsl, 2),
        ssl=round(ssl, 2),
        equilibrium=round(equilibrium, 2),
        displacement_10m_pct=round(disp_10m, 4) if disp_10m is not None else None,
        displacement_30m_pct=round(disp_30m, 4) if disp_30m is not None else None,
        range_30m_pct=range_30m_pct,
        price_zone=price_zone,
        is_consolidating=is_consolidating,
        directional_bias=round(bias, 3),
        bsl_swept=bsl_swept,
        ssl_swept=ssl_swept,
        history_depth_s=history_depth_s,
        displacement_score=round(displacement_score, 1),
        sweep_score=round(sweep_score, 1),
        structure_score=round(structure_score, 1),
        consolidation_score=round(consolidation_score, 1),
        discount_score=discount_score,
        institutional_state=state,
        state_label=cfg["label"],
        state_color=cfg["color"],
        smc_note=cfg["note"],
        trader_action=cfg["action"],
    )


def _classify(
    discount_score: float,
    disp_10m: float,
    is_consolidating: bool,
    bsl_swept: bool,
    ssl_swept: bool,
) -> InstitutionalState:
    d = disp_10m

    # Trap: strong pre-release move that has now stalled (distribution signal)
    if abs(d) > 0.25 and is_consolidating:
        return "TRAP_SETUP_DETECTED"

    # Consolidation: tight range, no directional commitment
    if is_consolidating and abs(d) < 0.10:
        return "CONSOLIDATION_ACCUMULATION"

    if discount_score >= 45:
        return "ALREADY_DISCOUNTED_BULLISH"
    if discount_score <= -45:
        return "ALREADY_DISCOUNTED_BEARISH"

    return "NOT_DISCOUNTED_NEUTRAL"
