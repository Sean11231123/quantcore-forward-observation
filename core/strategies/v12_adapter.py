from typing import Optional
import pandas as pd

from core.strategies.base import BaseStrategy, Signal, StrategyConfig

from v12_strategy import (
    SL_ATR_MULT,
    RISK_PCT,
    compute_v12_15m,
    align_1h_adx_to_15m,
    check_entry_long,
)


class V12Strategy(BaseStrategy):
    """
    V12 Trend Strategy Adapter
    - Wrap legacy V12 logic into BaseStrategy interface
    - Long-only (as design)
    """

    name = "v12_trend"

    def __init__(
        self,
        config: StrategyConfig,
        mode: str = "C3",
        adx_entry_override: float = 30.0,
        re_threshold_override: float = 0.22,
    ):
        super().__init__(config)

        self.mode = mode
        self.adx_entry_override = adx_entry_override
        self.re_threshold_override = re_threshold_override

    # =====================================================
    # Core Entry Logic
    # =====================================================
    def generate_signal(
        self,
        ohlcv_15m: pd.DataFrame,
        ohlcv_1h: pd.DataFrame = None,
        btc_regime: dict = None,
    ) -> Optional[Signal]:

        if ohlcv_15m is None or len(ohlcv_15m) < 200:
            return None

        df = ohlcv_15m.copy()

        # 1. compute indicators
        df = compute_v12_15m(df)

        # 2. align 1h ADX if available
        if ohlcv_1h is not None:
            df = align_1h_adx_to_15m(df, ohlcv_1h)

        # 3. latest row
        row = df.iloc[-1]

        price = float(row["close"])
        atr = float(row["atr"]) if pd.notna(row["atr"]) else None

        if atr is None or atr <= 0:
            return None

        # 4. BTC regime fallback
        if btc_regime is None:
            btc_regime = {
                "btc_adx": 0,
                "btc_adx_1h": 0,
                "btc_re": 0,
                "btc_close": 0,
            }

        # 5. entry filter
        ok = check_entry_long(
            row,
            float(row.get("prior_high_20", 0)),
            atr,
            float(row.get("adx_1h", 0)),
            btc_regime=btc_regime,
            mode=self.mode,
            adx_entry_override=self.adx_entry_override,
            re_threshold_override=self.re_threshold_override,
        )

        if not ok:
            return None

        # 6. risk sizing (V12 rule)
        stop_loss = price - SL_ATR_MULT * atr
        take_profit = price + 4.0 * atr

        qty = self._position_size(price, stop_loss)

        # 7. confidence (proxy from ATR + ADX strength if available)
        confidence = 0.7
        if "adx" in row:
            confidence = min(0.9, 0.5 + float(row["adx"]) / 100)

        return Signal(
            strategy_name=self.name,
            symbol=self.config.symbol,
            side="buy",
            order_type="limit",
            price=price,
            quantity=qty,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            metadata={
                "atr": atr,
                "mode": self.mode,
                "btc_re": btc_regime.get("btc_re", 0),
            },
        )
