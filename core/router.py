"""
Layer 3: Strategy Router

Routes market regimes to strategy names. Strategy implementations live in
core.strategies.*.
"""

from __future__ import annotations

from core.strategies.base import BaseStrategy
from core.strategies.v12_adapter import V12Strategy


class StrategyRouter:
    """
    Routes the primary V12 forward stream, plus the mean-reversion
    stream in bear regimes.
    """

    REGIME_PRIORITY = {
        "trending_bull": ["v12_trend"],
        "trending_bear": ["mean_reversion"],
        "breakout": ["v12_trend"],
        "ranging": [],
        "low_volatility": [],
        "high_volatility": [],
        "choppy": [],
    }

    def __init__(self, strategies: dict[str, BaseStrategy]):
        self.strategies = strategies

    def route(self, regime_signal) -> list[str]:
        """Return ordered list of strategy names to activate."""
        regime_key = regime_signal.regime.value
        priority = self.REGIME_PRIORITY.get(regime_key, [])
        return [s for s in priority if s in self.strategies]


__all__ = [
    "StrategyRouter",
    "V12Strategy",
]
