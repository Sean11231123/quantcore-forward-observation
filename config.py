# ============================================================
#  config.py — 所有可調參數集中於此
#  V9.4 變更紀錄（基於 edge_report.csv 數據分析）：
#    - ADX_TREND_VAL  : 25 → 30  (ADX>35 平均PnL=-0.06%, 25-30=-0.36%，提高門檻)
#    - ATR_SL_MULT    : 1.5 → 2.0 (53% SL單曾有1ATR+浮盈，SL確實偏緊)
#    - ATR_TP_MULT_RSI: 2.0 → 3.0 (SL放寬後同步提高TP維持R:R≥1.5)
#    - BODY_ATR_MIN_MULT: 新增 0.5 (針對A類失敗：進場K棒實體須≥0.5ATR)
# ============================================================
import os
from dotenv import load_dotenv
load_dotenv()

BINANCE_API_KEY    = os.getenv("BINANCE_TESTNET_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_TESTNET_SECRET", "")
OKX_API_KEY        = os.getenv("OKX_DEMO_KEY", "")
OKX_API_SECRET     = os.getenv("OKX_DEMO_SECRET", "")
OKX_PASSPHRASE     = os.getenv("OKX_DEMO_PASSPHRASE", "")
# --- 交易所設定 ---
TESTNET         = True

# --- Telegram ---
TG_BOT_TOKEN    = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID      = os.getenv("TG_CHAT_ID", "")

# --- 監控標的 (市值前 20 大熱門山寨幣) ---
SYMBOLS = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
        'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT',
        'TRX/USDT', 'BCH/USDT', 'NEAR/USDT', 'LTC/USDT', 'SUI/USDT', 'APT/USDT', 
        'OP/USDT', 'ARB/USDT', 'POL/USDT', 'FTM/USDT'
    ]

TIMEFRAMES      = ["15m", "1h"]      # 掃描的時間週期
POLL_INTERVAL   = 60                 # 每 60 秒掃描一輪

# --- 策略參數 ---
EMA_FAST        = 9
EMA_SLOW        = 21
VOLUME_MULT     = 1.2                # 成交量過濾基準倍數（進場條件另有設定）

# --- V9 ATR 風控參數 ---
ATR_PERIOD      = 14
ATR_SL_MULT     = 2.0            # V9.4 調整：1.5 → 2.0（數據支持：53% SL單曾有1ATR+浮盈）
ATR_TP_MULT_RSI = 3.0            # V9.4 調整：2.0 → 3.0（配合SL放寬，維持R:R≥1.5）
# Trend 策略的 TP 維持 4.0 ATR，由 strategy.py 內部定義

# --- V9.4 新增：進場 K 棒實體過濾 ---
# 用途：過濾 A 類失敗（進場後立即反向）
# 進場 K 棒的「收盤-開盤」實體必須 >= 當根 ATR × BODY_ATR_MIN_MULT
# 這確保進場 K 棒有真實動能，排除震盪假突破
# 數據依據：22% 的 SL 單屬於「進場即錯方向（MFE<0.3 ATR, bars<=2）」
# 建議值：0.4~0.6（太高會過度減少訊號頻率）
BODY_ATR_MIN_MULT = 0.3   # 原本是 0.5

# --- RSI 相關參數 ---
RSI_PERIOD      = 14
RSI_OVERSOLD    = 30
RSI_OVERBOUGHT  = 70

# --- 訊號品質過濾 ---
MIN_CONFIDENCE  = 60

# --- V9 Regime & Trend 參數 ---
ADX_PERIOD      = 14
ADX_TREND_SMOOTH = 3             # 防抖：需連續 N 根符合
ADX_TREND_VAL   = 25             # 原本是 30
ADX_RANGE_VAL   = 20             # Range 門檻不變

# --- 資金流向確認 (OBV + CMF) ---
OBV_EMA_PERIOD   = 14
CMF_PERIOD       = 20
CONFIRM_LOOKBACK = 5

# --- 回測與模擬設定 ---
INITIAL_BALANCE  = 100
COMMISSION       = 0.0005        # 幣安合約 Taker 手續費 (萬分之五)
