# test_v9_v2_edge.py
"""
V9 v2 Edge Validation
E_A (entry-only) vs E_B (full system with costs)
"""
import pandas as pd
import numpy as np
from config_v9_v2 import V9_V2_MIN_EXPECTANCY, V9_V2_MIN_RR

def validate_edge():
    print("=" * 70)
    print("V9 v2 EDGE VALIDATION")
    print("=" * 70)
    
    trades = pd.read_csv("logs/v9_v2_trades.csv")
    
    # E_A: Entry-only (no fees/slippage)
    E_A = trades["pnl_pct"].mean()
    
    # E_B: Full system (with fees/slippage)
    E_B = trades["net_pnl_pct"].mean()
    
    # Execution cost impact
    cost_impact = E_A - E_B
    
    # Win rate
    wr = (trades["pnl_pct"] > 0).mean() * 100
    
    # R:R
    winners = trades[trades["pnl_pct"] > 0]["pnl_pct"].mean()
    losers = abs(trades[trades["pnl_pct"] <= 0]["pnl_pct"].mean())
    rr = winners / losers if losers > 0 else 0
    
    # MFE/MAE
    avg_mfe = trades["mfe_atr"].mean()
    avg_mae = trades["mae_atr"].mean()
    
    print(f"""
┌─────────────────────────────────────────────────────────┐
│  EDGE VALIDATION RESULTS                                │
├─────────────────────────────────────────────────────────┤
│  E_A (Entry-only):      {E_A:.6f}                       │
│  E_B (Full w/Costs):    {E_B:.6f}                       │
│  Cost Impact:           {cost_impact:.6f} ({cost_impact/E_A*100:.1f}%)         │
│                                                         │
│  Win Rate:              {wr:.1f}%                        │
│  Avg R:R:               {rr:.2f}                          │
│  Avg MFE:               {avg_mfe:.2f} ATR                    │
│  Avg MAE:               {avg_mae:.2f} ATR                    │
├─────────────────────────────────────────────────────────┤
│  VALIDATION CRITERIA:                                   │
│  - E_A > 0:             {'✅ PASS' if E_A > 0 else '❌ FAIL'}                          │
│  - E_B > 0:             {'✅ PASS' if E_B > 0 else '❌ FAIL'}                          │
│  - E_A ≥ 0.003:         {'✅ PASS' if E_A >= V9_V2_MIN_EXPECTANCY else '❌ FAIL'}      │
│  - R:R ≥ 2.0:           {'✅ PASS' if rr >= V9_V2_MIN_RR else '❌ FAIL'}              │
└─────────────────────────────────────────────────────────┘
""")
    
    # Final classification
    if E_A > 0 and E_B > 0 and E_A >= V9_V2_MIN_EXPECTANCY and rr >= V9_V2_MIN_RR:
        print("✅ V9 v2: VALID - Signal-based edge confirmed")
        return True
    else:
        print("❌ V9 v2: INVALID - Does not meet criteria")
        return False

if __name__ == "__main__":
    validate_edge()
