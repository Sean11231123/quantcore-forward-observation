"""
Layer 4: Risk Management
Portfolio-level risk controls, drawdown limits, position limits.

"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, Literal
import numpy as np

from strategies import Signal


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4: Risk Management
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskLimits:
    max_drawdown_pct: float = 0.10        # 10% max drawdown → halt
    max_daily_loss_pct: float = 0.03      # 3% daily loss → pause
    max_open_positions: int = 5
    max_correlated_positions: int = 2     # Avoid concentration
    max_total_exposure_pct: float = 0.50  # 50% max portfolio exposure
    position_size_limit_pct: float = 0.15 # Single position max 15%
    min_signal_confidence: float = 0.55   # Reject weak signals


@dataclass
class PortfolioState:
    capital_usdt: float
    peak_capital: float
    daily_start_capital: float
    open_positions: dict = field(default_factory=dict)  # symbol -> position
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    trade_count_today: int = 0
    last_reset_date: str = ""
    is_halted: bool = False
    halt_reason: str = ""


class RiskManager:
    """
    Validates signals against portfolio-level risk rules.
    Controls position sizing, drawdown, and correlation limits.
    """

    def __init__(self, limits: RiskLimits, state: PortfolioState):
        self.limits = limits
        self.state = state

    def validate_signal(self, signal: Signal) -> tuple[bool, str]:
        """
        Returns (approved: bool, reason: str).
        Runs all risk checks in sequence.
        """
        if self.state.is_halted:
            return False, f"System halted: {self.state.halt_reason}"

        checks = [
            self._check_confidence(signal),
            self._check_drawdown(),
            self._check_daily_loss(),
            self._check_position_count(),
            self._check_exposure(signal),
        ]

        for passed, reason in checks:
            if not passed:
                return False, reason

        return True, "approved"

    def adjust_position_size(self, signal: Signal) -> Signal:
        """Scale down signal quantity if it would breach limits."""
        max_qty_by_capital = (
            self.state.capital_usdt
            * self.limits.position_size_limit_pct
            / (signal.price or 1.0)
        )
        signal.quantity = min(signal.quantity, max_qty_by_capital)
        return signal

    def update_state(self, pnl_delta: float):
        """Call after trade close to update portfolio state."""
        self.state.capital_usdt += pnl_delta
        self.state.total_pnl += pnl_delta
        self.state.daily_pnl += pnl_delta
        self.state.peak_capital = max(self.state.peak_capital, self.state.capital_usdt)
        self._check_halt_conditions()

    def _check_halt_conditions(self):
        drawdown = (self.state.peak_capital - self.state.capital_usdt) / self.state.peak_capital
        if drawdown >= self.limits.max_drawdown_pct:
            self.state.is_halted = True
            self.state.halt_reason = f"Max drawdown {drawdown:.1%} exceeded"

        daily_loss = -self.state.daily_pnl / self.state.daily_start_capital
        if daily_loss >= self.limits.max_daily_loss_pct:
            self.state.is_halted = True
            self.state.halt_reason = f"Daily loss {daily_loss:.1%} exceeded"

    def _check_confidence(self, signal: Signal):
        if signal.confidence < self.limits.min_signal_confidence:
            return False, f"Signal confidence {signal.confidence:.2f} below threshold"
        return True, ""

    def _check_drawdown(self):
        drawdown = (self.state.peak_capital - self.state.capital_usdt) / self.state.peak_capital
        if drawdown >= self.limits.max_drawdown_pct:
            return False, f"Drawdown {drawdown:.1%} at limit"
        return True, ""

    def _check_daily_loss(self):
        daily_loss_pct = -self.state.daily_pnl / self.state.daily_start_capital
        if daily_loss_pct >= self.limits.max_daily_loss_pct:
            return False, f"Daily loss {daily_loss_pct:.1%} at limit"
        return True, ""

    def _check_position_count(self):
        if len(self.state.open_positions) >= self.limits.max_open_positions:
            return False, f"Max positions ({self.limits.max_open_positions}) reached"
        return True, ""

    def _check_exposure(self, signal: Signal):
        price = signal.price or 0
        new_exposure = signal.quantity * price
        total_current = sum(
            p.get("value_usdt", 0) for p in self.state.open_positions.values()
        )
        total_new = total_current + new_exposure
        exposure_pct = total_new / self.state.capital_usdt
        if exposure_pct > self.limits.max_total_exposure_pct:
            return False, f"Total exposure {exposure_pct:.1%} would exceed limit"
        return True, ""


