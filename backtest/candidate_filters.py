"""Pre-registered V12 candidate filter metadata.

This file intentionally defines specifications only. It must not import or run
any backtest code.
"""

CANDIDATE_FILTERS = {
    "F0_baseline": {
        "description": "原版 clean V12，無額外 filter",
        "conditions": {},
    },
    "F1_volume": {
        "description": "要求成交量確認",
        "conditions": {"volume_ratio": (">=", 1.5)},
        "rationale": "volume_ratio mid bucket 期望值最高，1.5 為 low/mid 切割的保守估計",
    },
    "F2_atr_quality": {
        "description": "ATR 擴張品質過濾",
        "conditions": {
            "atr_expansion_ratio": (">=", 1.03),
            "atr_expansion_ratio_upper": ("<=", 1.10),
        },
        "rationale": "mid ATR expansion 有最高 win rate，上下都較差",
        "risk_note": "上限 1.10 是從 OOS 三分位推算，overfit 風險高",
    },
    "F3_no_exhaustion": {
        "description": "排除追高型 K 棒",
        "conditions": {"candle_close_position": ("<=", 0.82)},
        "rationale": "close_position > 0.82 的 trades win% 只有 41%",
        "risk_note": "切割點 0.82 來自 OOS 66th percentile，overfit 風險高",
    },
    "F4_combined": {
        "description": "F1 + F3 組合（保守版，不含 ATR 上限）",
        "conditions": {
            "volume_ratio": (">=", 1.5),
            "candle_close_position": ("<=", 0.82),
        },
        "risk_note": "組合 filter 在小樣本上 overfit 風險更高",
    },
}
