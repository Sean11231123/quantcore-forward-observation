# backtest_v9_v2.py
"""
V9 v2 Backtest Engine
Includes execution cost simulation
"""
import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
from v9_v2_strategy import compute_indicators, generate_signal, Signal
from config import INITIAL_BALANCE
from config_v9_v2 import (
    V9_V2_FEE_PCT, V9_V2_SLIPPAGE_PCT,
    V9_V2_BE_TRIGGER_ATR
)

def run_backtest(file_path: str) -> dict:
    """Run backtest on single symbol"""
    symbol = os.path.basename(file_path).replace("_1h.csv", "")
    
    df = pd.read_csv(file_path)
    df.columns = df.columns.str.lower()
    
    # Time column handling
    ts_col = None
    for col in ["timestamp", "time", "open_time"]:
        if col in df.columns:
            ts_col = col
            break
    if ts_col:
        df["timestamp"] = pd.to_datetime(df[ts_col])
    
    # Compute indicators
    df = compute_indicators(df)
    df = df.reset_index(drop=True)
    
    # Backtest loop
    balance = INITIAL_BALANCE
    pos = 0
    entry_price = 0
    entry_atr = 0
    current_sl = 0
    current_tp = 0
    peak_price = 0
    trough_price = 0
    trade_log = []
    
    for i in range(200, len(df)):
        row = df.iloc[i]
        ts = row["timestamp"]
        hi, lo, cl = row["high"], row["low"], row["close"]
        
        # Position management
        if pos != 0:
            if pos == 1:  # LONG
                peak_price = max(peak_price, hi)
                trough_price = min(trough_price, lo)

                # Check BE trigger
                if (cl - entry_price) / entry_atr >= V9_V2_BE_TRIGGER_ATR:
                    current_sl = max(current_sl, entry_price)
                
                # Check SL
                if lo <= current_sl:
                    pnl = (current_sl - entry_price) / entry_price
                    fee = V9_V2_FEE_PCT
                    slippage = V9_V2_SLIPPAGE_PCT
                    exit_net_pnl = pnl - fee - slippage
                    net_pnl = pnl - (2 * (V9_V2_FEE_PCT + V9_V2_SLIPPAGE_PCT))
                    balance *= (1 + exit_net_pnl)
                    mfe_atr = (peak_price - entry_price) / entry_atr if entry_atr > 0 else 0
                    mae_atr = (entry_price - trough_price) / entry_atr if entry_atr > 0 else 0
                    trade_log.append({
                        "timestamp": ts, "symbol": symbol, "type": "LONG",
                        "exit": "SL", "pnl_pct": pnl, "net_pnl_pct": net_pnl,
                        "exit_net_pnl_pct": exit_net_pnl,
                        "entry_price": entry_price, "exit_price": current_sl,
                        "atr": entry_atr, "mfe_atr": mfe_atr, "mae_atr": mae_atr,
                        "bars_held": i - entry_idx
                    })
                    pos = 0
                
                # Check TP
                elif hi >= current_tp:
                    pnl = (current_tp - entry_price) / entry_price
                    fee = V9_V2_FEE_PCT
                    slippage = V9_V2_SLIPPAGE_PCT
                    exit_net_pnl = pnl - fee - slippage
                    net_pnl = pnl - (2 * (V9_V2_FEE_PCT + V9_V2_SLIPPAGE_PCT))
                    balance *= (1 + exit_net_pnl)
                    mfe_atr = (peak_price - entry_price) / entry_atr if entry_atr > 0 else 0
                    mae_atr = (entry_price - trough_price) / entry_atr if entry_atr > 0 else 0
                    trade_log.append({
                        "timestamp": ts, "symbol": symbol, "type": "LONG",
                        "exit": "TP", "pnl_pct": pnl, "net_pnl_pct": net_pnl,
                        "exit_net_pnl_pct": exit_net_pnl,
                        "entry_price": entry_price, "exit_price": current_tp,
                        "atr": entry_atr, "mfe_atr": mfe_atr, "mae_atr": mae_atr,
                        "bars_held": i - entry_idx
                    })
                    pos = 0
        
        # Entry signal
        else:
            sig = generate_signal(df, i)
            if sig.signal == Signal.LONG:
                pos = 1
                entry_price = cl
                entry_atr = sig.atr
                entry_idx = i
                current_sl = sig.stop_loss
                current_tp = sig.take_profit
                peak_price = entry_price
                trough_price = entry_price
                balance *= (1 - V9_V2_FEE_PCT - V9_V2_SLIPPAGE_PCT)  # Entry fee + slippage
    
    # Calculate stats
    if not trade_log:
        return None
    
    tdf = pd.DataFrame(trade_log)
    wr = (tdf["pnl_pct"] > 0).sum() / len(tdf) * 100
    expectancy = tdf["net_pnl_pct"].mean()
    avg_rr = (tdf["pnl_pct"][tdf["pnl_pct"] > 0].mean() / 
              abs(tdf["pnl_pct"][tdf["pnl_pct"] <= 0].mean())) if len(tdf[tdf["pnl_pct"] <= 0]) > 0 else 0
    balance_curve = [INITIAL_BALANCE]
    running_balance = INITIAL_BALANCE
    for pnl in tdf["net_pnl_pct"]:
        running_balance *= (1 + pnl)
        balance_curve.append(running_balance)
    balance_curve = pd.Series(balance_curve)
    rolling_max = balance_curve.cummax()
    dd = (rolling_max - balance_curve) / rolling_max
    max_dd = dd.max() * 100
    
    return {
        "symbol": symbol,
        "trades": len(tdf),
        "win_rate": wr,
        "expectancy": expectancy,
        "avg_rr": avg_rr,
        "total_return": (balance / INITIAL_BALANCE - 1) * 100,
        "max_dd": max_dd,
        "trade_log": trade_log
    }

if __name__ == "__main__":
    data_files = glob.glob("data/*_1h.csv")
    results = []
    
    for f in data_files:
        res = run_backtest(f)
        if res:
            results.append(res)
            print(f"✅ {res['symbol']}: {res['trades']} trades, Expectancy={res['expectancy']:.6f}, WR={res['win_rate']:.1f}%")
    
    if results:
        # Save combined results
        os.makedirs("logs", exist_ok=True)
        all_trades = []
        for r in results:
            all_trades.extend(r["trade_log"])
        pd.DataFrame(all_trades).to_csv("logs/v9_v2_trades.csv", index=False)
        
        # Summary
        print("\n" + "=" * 70)
        print("V9 v2 BACKTEST SUMMARY")
        print("=" * 70)
        print(f"Total Trades: {sum(r['trades'] for r in results)}")
        print(f"Avg Expectancy: {np.mean([r['expectancy'] for r in results]):.6f}")
        print(f"Avg Win Rate: {np.mean([r['win_rate'] for r in results]):.1f}%")
        print(f"Avg R:R: {np.mean([r['avg_rr'] for r in results]):.2f}")
