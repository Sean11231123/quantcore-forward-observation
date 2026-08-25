# SECOND-ROUND SEMANTIC EVIDENCE — 彙整版 V1.0

- 提交對象:ChatGPT implementation review(轉呈 Claude 獨立稽核前)
- 編製:Ox Alpha(Temporary Implementation Agent)
- 儲存庫:quantcore-forward-observation(branch: main,HEAD = 3e2b20a)
- 證據基準日:2026-08-25(+0800)
- 語言:中文說明;程式碼與指令輸出保留英文原文

---

## 0. 閱讀指引、證據分級與能力限制聲明

### 0.1 證據分級慣例

- **FACT**:可由本文件所引之原始碼逐字內容或 git 實際輸出直接驗證之事實。
- **UNKNOWN / NOT AVAILABLE**:本地環境無法取得之資訊,明確標記,不以假設填補。

### 0.2 能力限制聲明(誠實申報)

Ox Alpha 於本會話中無法執行任何 shell / git / pytest 指令。因此:

- 本文件所有 git 輸出均由 Sean 於本地執行後逐字貼回,非 Ox Alpha 直接產生;
- 所有原始碼引用均來自 Sean 明確聲明「Trust this message as the true contents」之檔案內容(engine.py、v12_strategy.py、core/strategies/v12_adapter.py、core/exchange.py、config.py、backtest/v12_backtest.py、tests/test_v12_integration_contract.py),非記憶重構;
- 測試結果(pytest / py_compile / flake8)均由 Sean 本地執行並貼回完整輸出。

### 0.3 本輪邊界確認

本證據彙整輪零修改:未 edit、未 commit、未 push、未 merge、未 deploy、未動 .gitignore、未動 __pycache__、未動 V12 implementation、未動 tests。

---

## A. Implementation Diff

### A-1. Commit chain 完整分類(FACT,來自 git log --oneline --name-status)

| Commit | 分類 | 涉及檔案 | 說明 |
|---|---|---|---|
| 38cef46 | baseline | 全庫 | "Initial QuantCore forward observation deployment"(根 commit / shallow 邊界) |
| 81f8d8d | **implementation** | M engine.py(+184)、A tests/test_v12_integration_contract.py(+426) | V12 C3 資料契約修復主體 |
| 8d2462b | **test** | M tests(+6/−1) | 15m 樣本 80→300 根 + 新增斷言 |
| 5bb63a0 | **pollution introduction**(訊息誤標為 test) | M engine.py(626 行→3 行) | engine.py 被 pytest 輸出整檔覆寫並提交 |
| baea3bd | **tooling/remediation** | M engine.py | 以 git checkout 81f8d8d -- engine.py 還原 |
| e602b02 | pollution(意外引入) | A 兩個報告文字檔 | aider 誤建("B. Diff Integrity"、"C. Tests(...)") |
| 83b45dc | **tooling** | M .gitignore | 新增 .aider* 忽略規則 |
| faf42a2 | **tooling** | M .gitignore(1 insertion / 112 deletions) | 精簡忽略規則 |
| 3e2b20a | **report cleanup** | D 兩個污染檔 | 移除誤建之報告文字檔 |

### A-2. git show --stat 實際輸出(FACT,Sean 本地執行)

Commit 81f8d8d:

    commit 81f8d8d7a4e6e31ecb42b56020a6d7180a362a3a
    Author: Sean11231123 <sean9611231123@gmail.com>
    Date:   Tue Aug 25 00:14:50 2026 +0800

        fix: 修復V12 C3資料管線,補齊15m/1H/BTC regime並強制封閉K棒

     engine.py                              | 184 +++++++++++++-
     tests/test_v12_integration_contract.py | 426 +++++++++++++++++++++++++++++++++
     2 files changed, 600 insertions(+), 10 deletions(-)

Commit 8d2462b:

    commit 8d2462b70ccc07de0cae589502246fc9fd9d9bba
    Date:   Tue Aug 25 00:30:33 2026 +0800

        test: 增補 15m 樣本至 300 根並斷言滿足 V12_MIN_ENTRY_BARS

     tests/test_v12_integration_contract.py | 7 ++++++-
     1 file changed, 6 insertions(+), 1 deletion(-)

### A-3. Intended diff 核心內容(git diff 38cef46..81f8d8d,關鍵行摘錄)

BEFORE 側(原始缺陷的確切性質):

    -    async def _fetch_ohlcv_df(self, symbol: str, limit: int | None = None) -> pd.DataFrame:
    -                df = await self._fetch_ohlcv_df(symbol, limit=120)
    -                        signal = strategy.generate_signal(df)

即:僅抓取一幀 config TF("1h")資料,以位置參數傳入 generate_signal → 該 1h 幀被綁定至 ohlcv_15m 形參;ohlcv_1h 與 btc_regime 從未被供應(adapter 內部落入零值 fallback);enrichment 同樣只消費該錯誤幀。

AFTER 側(核心呼叫契約):

    +                        signal = strategy.generate_signal(
    +                            ohlcv_15m=df15,
    +                            ohlcv_1h=df1h,
    +                            btc_regime=btc_regime,
    +                        )

新增元件清單:AFTER 包含四個契約常數(V12_ENTRY_TIMEFRAME="15m"、V12_CONFIRM_TIMEFRAME="1h"、V12_OHLCV_LIMIT=300、V12_MIN_ENTRY_BARS=200)、_CLOSED_BAR_DELTAS 對照表、_fetch_ohlcv_df 之選用 timeframe 參數、_filter_closed_bars、_build_btc_regime、BTC 1H 抓取與 "BTC REGIME INPUTS" 日誌、候選 15m+1h 雙抓與封閉過濾、空幀防護與不足 200 根防護、"DATA ... closed-bar filtered" 日誌、enrichment 轉發 (df15, df1h) 使 adx_confirm_tf 取自真實 1H 確認 ADX。

### A-4. 凍結項目核查(FACT)

git diff 38cef46..81f8d8d 全文不含以下任何變更:V12 進場/出場條件、ADX 門檻、BTC RE 界線(btc_re_lower/btc_re_upper)、re_threshold_override 數值、策略過濾器、參數最佳化、universe(["BTC/USDT:USDT"] 保持)、execute_orders(False 保持)、exchange 層、E2 整合、Telegram、order execution。✅ 無夾帶。

### A-5. 5bb63a0 污染事件完全解密(FACT,來自 git show 5bb63a0 -- engine.py)

該 commit 刪除 engine.py 全部 626 行,替換為 3 行 pytest 輸出:

    platform win32 -- Python 3.12.2, pytest-9.1.1
    collected 10 items
    10 passed in 1.66s

要點:

1. commit 訊息「test: 新增V12整合契約回歸測試…」與實際變更完全相反——審查時不得以其訊息判斷內容。
2. 污染內容之「1.66s」對應第一次測試執行(第二次為 1.64s),可將污染時點定位於首次測試完成之後。
3. 時間線精確化:污染已在 5bb63a0 被提交(非僅工作樹覆寫);baea3bd 以 git checkout 81f8d8d -- engine.py 還原並提交;checkout 後 git status 不再顯示 M engine.py,直接證明現行 HEAD 之 engine.py 與 81f8d8d 版本逐字一致,diff 零殘留。

### A-6. 治理意涵(供審查方知悉,非 Ox Alpha 行動)

1. 歷史存在兩個污染引入點(5bb63a0 引擎覆寫、e602b02 報告文字檔);工作樹均已潔淨,但 git 歷史本身仍保留污染內容(歷史不可變)。若治理層要求歷史潔淨(rebase/squash/filter),屬新授權決策。
2. 兩次污染皆源於同一失效模式:「LLM 回應文字 / 終端輸出被寫入儲存庫」。建議流程面增設防護(例如 aider auto-commit 前人工 diff 審視)。此為建議,非授權內行動。

---

## B. Closed-Bar Policy(封閉 K 棒政策)

### B-1. 相關 constants(逐字,engine.py)

    # ── V12 C3 data-contract constants (integration layer only) ─────────────────
    # Frozen elsewhere (DO NOT CHANGE HERE):
    #   universe ["BTC/USDT:USDT"], execute_orders=False,
    #   re_threshold_override=0.22 (governance finding under archaeology).
    V12_ENTRY_TIMEFRAME = "15m"   # candidate entry timeframe required by V12 adapter
    V12_CONFIRM_TIMEFRAME = "1h"  # candidate + BTC confirmation timeframe
    V12_OHLCV_LIMIT = 300         # warmup headroom for ADX/EMA/RE indicators
    V12_MIN_ENTRY_BARS = 200      # minimum closed 15m bars required by V12Strategy.generate_signal

    # Timeframe duration map used by the closed-bar filter. Timestamps returned by
    # the exchange are candle OPEN times; close_time = open_time + duration.
    _CLOSED_BAR_DELTAS = {
        "15m": pd.Timedelta(minutes=15),
        "30m": pd.Timedelta(minutes=30),
        "1h": pd.Timedelta(hours=1),
        "2h": pd.Timedelta(hours=2),
        "4h": pd.Timedelta(hours=4),
        "1d": pd.Timedelta(days=1),
    }

### B-2. _filter_closed_bars 完整原始碼(逐字,engine.py)

    @staticmethod
    def _filter_closed_bars(
        df: pd.DataFrame, timeframe: str, now: datetime | None = None
    ) -> pd.DataFrame:
        """
        Closed-bar policy (mandatory no-lookahead rule).

        Timestamp convention: exchange OHLCV timestamps are candle OPEN times.
        A bar is usable at evaluation time t iff:

            open_time + timeframe_duration <= t

        i.e. the bar is fully CLOSED at t. This simultaneously excludes:
          - the currently forming candle (its close occurs after t)
          - any future candle (open_time > t implies close_time > t)

        Boundary: a bar whose close_time == t IS usable (its close is known at
        instant t). This matches the inclusive convention already used by
        v12_strategy.align_1h_adx_to_15m (merge_asof direction="backward" on
        candle-CLOSE timestamps).
        """
        if df.empty:
            return df
        delta = _CLOSED_BAR_DELTAS.get(timeframe)
        if delta is None:
            raise ValueError(f"Unsupported timeframe for closed-bar filter: {timeframe}")
        t = pd.Timestamp(now or datetime.now(timezone.utc))
        ts = df["timestamp"]
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize("UTC")
        mask = (ts + delta) <= t
        return df.loc[mask].reset_index(drop=True)

### B-3. 要求說明項(FACT)

- timestamp unit:交易所回傳 ms epoch 整數;_fetch_ohlcv_df 以 pd.to_datetime(unit="ms") 轉為 datetime64。
- timezone:UTC(tz-aware;若來源無 tz 則 tz_localize("UTC"))。
- evaluation timestamp source:每輪掃描開頭一次性擷取 now = datetime.now(timezone.utc),明確傳入所有過濾呼叫(同一輪內一致)。
- 15m duration:Timedelta(minutes=15);1h duration:Timedelta(hours=1)。
- 保留規則:open_time + duration <= t(邊界包含:收盤時刻恰等於 t 視為可用)。

### B-4. 殘餘風險申報(如實)

若本地系統時鐘領先交易所實際時間,K 棒可能在交易所端尚未定案時被本地判定為已封閉(clock skew)。完全消除需改為「等待下一根開盤後才評估」,屬行為變更,超出已核准範圍,僅申報待裁決。

---

## C. 1H Alignment(1H 確認資料對齊)

### C-1. 完整原始碼(逐字,v12_strategy.py,未修改檔)

    def shift_candle_open_to_close(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """Convert candle-open timestamps to candle-close timestamps for safe lower-TF merges."""
        offsets = {
            "15m": pd.Timedelta(minutes=15),
            "30m": pd.Timedelta(minutes=30),
            "1h": pd.Timedelta(hours=1),
            "2h": pd.Timedelta(hours=2),
            "4h": pd.Timedelta(hours=4),
            "1d": pd.Timedelta(days=1),
        }
        if timeframe not in offsets:
            raise ValueError(f"Unsupported timeframe for timestamp shift: {timeframe}")
        out = df.copy()
        out["timestamp"] = pd.to_datetime(out["timestamp"])
        out["timestamp"] = out["timestamp"] + offsets[timeframe]
        return out


    def align_1h_adx_to_15m(df15: pd.DataFrame, df1h: pd.DataFrame) -> pd.DataFrame:
        one_hour = compute_v12_15m(df1h)
        one_hour = shift_candle_open_to_close(one_hour, "1h")
        one_hour = one_hour[["timestamp", "adx"]].rename(columns={"adx": "adx_1h"})
        return pd.merge_asof(
            df15.sort_values("timestamp"),
            one_hour.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
        )

### C-2. 五項說明(FACT)

1. 原始 1H timestamp 意義:交易所回傳者為 K 棒開盤時間(open timestamp)。
2. shift 前:時間戳 = 該 1H K 棒之開盤時刻。
3. shift 後:時間戳 = 該 1H K 棒之收盤時刻(open + 1h),代表「此 K 棒資訊何時可用」。
4. merge_asof(direction="backward"):left key = df15.timestamp(15m K 棒開盤戳);right key = shift 後之 1H 收盤戳。backward 語意 = 對每個 left key,選取 right key <= left key 之最後一列。
5. 具體例子:設 15m 評估時間戳 T = 2026-05-04 10:30 UTC。
   - Eligible 1H candles:收盤時刻 <= 10:30 者,即 …、08:00 開盤(收 09:00)、09:00 開盤(收 10:00)。
   - Selected 1H candle:09:00 開盤、10:00 收盤那根(其 ADX 反映至 10:00 收盤之資訊)。

### C-3. 「收盤 > T 之 1H K 棒不可能被選中」之結構性證明(FACT)

候選右鍵即收盤時刻;backward 合併之選取條件 right_key <= left_key 由 pandas merge_asof 演算法保證。凡收盤 > T 之 K 棒其右鍵 > T,必然落選——此保證與資料數值無關,屬結構性質。另有一層雙重防護:實際前向路徑中,形成中的 1H K 棒早在 _filter_closed_bars 階段即被剔除,根本不會進入右側框架。

### C-4. 慣例細節申報(供 F 節核對)

left key 使用 15m K 棒的開盤時間戳(而非收盤戳)。效果:收盤時刻落在 (T_open, T_open+15分] 區間的 1H K 棒不會被使用,即使它在 15m K 棒完成前已收盤。方向偏保守(確認資料可能舊最多 15 分鐘),不是前瞻;但此慣例是否與回測端一致,見 F 節比對。

---

## D. BTC Regime Forward Definition(前向定義)

### D-1. _build_btc_regime 完整原始碼(逐字,engine.py)

    @staticmethod
    def _build_btc_regime(btc_1h_closed: pd.DataFrame) -> dict:
        """
        Build the existing V12 C3 BTC regime inputs from CLOSED BTC 1H bars.

        Reuses v12_strategy.compute_v12_15m indicator math UNCHANGED:
          - btc_adx_1h = ADX(14) on BTC 1H              (BTC ADX confirm)
          - btc_re     = 20-bar range efficiency on BTC 1H (BTC RE)
        Values are read from the last fully closed BTC 1H bar.
        """
        if btc_1h_closed.empty:
            return {}
        from v12_strategy import compute_v12_15m

        feats = compute_v12_15m(btc_1h_closed)
        row = feats.iloc[-1]
        adx = row.get("adx")
        re = row.get("range_efficiency")
        return {
            "btc_adx_1h": float(adx) if pd.notna(adx) else 0.0,
            "btc_re": float(re) if pd.notna(re) else 0.0,
        }

### D-2. 兩個輸出值之計算方式(逐字引用 compute_v12_15m 相關行,v12_strategy.py)

ADX(供 btc_adx_1h):

    def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        up_move = df["high"].diff()
        down_move = -df["low"].diff()

        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        tr = _true_range(df)

        atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)) * 100
        return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

RE(供 btc_re):

    window = 20
    range_high = out["high"].rolling(window, min_periods=window).max()
    range_low = out["low"].rolling(window, min_periods=window).min()
    out["range_efficiency"] = (
        (out["close"] - out["close"].shift(window)).abs()
        / (range_high - range_low).replace(0, pd.NA)
    ).fillna(0.0)

即:btc_re = |C_t − C_{t−20}| / (max(High,20) − min(Low,20)),NaN 補 0;btc_adx_1h 為 EMA 平滑型 ADX(α=1/14,min_periods=14)。兩者皆取自最後一根已封閉 BTC 1H K 棒(輸入框已過 _filter_closed_bars)。

---

## E. BTC Regime Backtest Definition(回測定義)

### E-1. _load_btc_regime 完整原始碼(逐字,backtest/v12_backtest.py)

    def _load_btc_regime() -> Optional[pd.DataFrame]:
        p15 = "data/BTC_USDT_15m.csv"
        p1h = "data/BTC_USDT_1h.csv"

        if not os.path.exists(p15) or not os.path.exists(p1h):
            return None

        btc15 = pd.read_csv(p15)
        btc1h = pd.read_csv(p1h)

        btc15.columns = [c.lower() for c in btc15.columns]
        btc1h.columns = [c.lower() for c in btc1h.columns]

        btc15["timestamp"] = pd.to_datetime(btc15["timestamp"])
        btc1h["timestamp"] = pd.to_datetime(btc1h["timestamp"])

        btc15 = compute_v12_15m(btc15)
        btc1h = compute_v12_15m(btc1h)
        btc1h = shift_candle_open_to_close(btc1h, "1h")

        btc1h = btc1h[["timestamp", "adx"]].rename(columns={"adx": "btc_adx_1h"})

        btc15 = btc15.sort_values("timestamp")
        btc1h = btc1h.sort_values("timestamp")

        df = pd.merge_asof(btc15, btc1h, on="timestamp", direction="backward")

        df = df.rename(columns={
            "close": "btc_close",
            "adx": "btc_adx",
            "ema20": "btc_ema20",
            "ema50": "btc_ema50",
            "ema200": "btc_ema200",
            "range_efficiency": "btc_re",
        })
        return df[[
            "timestamp",
            "btc_close",
            "btc_adx",
            "btc_adx_1h",
            "btc_ema20",
            "btc_ema50",
            "btc_ema200",
            "btc_re",
        ]]

### E-2. 回測端逐項事實(FACT,全部可直接由上述原始碼驗證)

1. btc_re 來源幀 = BTC 15m:range_efficiency 由 compute_v12_15m(btc15) 產生後更名為 btc_re——即 20 根 × 15 分鐘 = 5 小時視窗之 RE。
2. btc_adx_1h 來源幀 = BTC 1H:由 compute_v12_15m(btc1h) 產生,shift 至收盤時間戳。
3. 附帶欄位:btc_adx(BTC 15m ADX)、btc_ema20/50/200 同樣存在,但 C3 分支只讀 btc_adx_1h 與 btc_re。
4. 對齊方式(_prepare 內):候選 15m 框以 merge_asof(direction="backward") 對 BTC regime 框合併,left key = 候選 15m 開盤戳,right key = BTC 15m 開盤戳 → 每根候選 K 棒取得「開盤戳 <= 該棒開盤戳」的最後一根 BTC 15m 列(同時刻棒包含在內;兩者同時收盤,決策時點一致,無前瞻)。相關原始碼:

        if btc is not None:
            df = pd.merge_asof(
                df.sort_values("timestamp"),
                btc.sort_values("timestamp"),
                on="timestamp",
                direction="backward"
            )

5. btc_adx_1h 的二次對齊:BTC 1H 收盤戳先 backward 併入 BTC 15m 列(left key = 15m 開盤戳),再隨 regime 列併入候選框——與前向 align_1h_adx_to_15m 之鍵慣例完全相同。
6. 歷史紀錄交叉驗證:交易日誌之 btc_re 取自 state.btc_regime_at_entry,即上述 15m 視窗值。歷史證據「BTC RE = 0.31 / 0.29」皆屬此定義;C3 界線 0.20–0.40 是對此定義校準的。

---

## F. Semantic Equivalence(語意等價性判定)

### F-1. 逐項比對表

| Component | Backtest(v12_backtest.py) | Forward(engine.py) | 等價? |
|---|---|---|---|
| btc_adx_1h 來源 TF | BTC 1H | BTC 1H(封閉過濾後) | ✅ |
| btc_adx_1h 計算 | compute_v12_15m → _adx(period=14) | 同一函式 | ✅ |
| btc_adx_1h 取值時點 | 每評估 ts 之 asof 列(1H 收盤 <= 15m 開盤戳) | 掃描當下最後一根已封閉 1H 棒 | ✅(語意相同,僅刷新節奏差異) |
| btc_re 來源 TF | BTC 15m | BTC 1H | ❌ |
| btc_re 有效視窗 | 20×15m = 5 小時 | 20×1h = 20 小時 | ❌ |
| btc_re 公式 | \|C_t−C_{t−20}\|/(HH20−LL20)(同一公式) | 同一公式 | ✅(但套在不同 TF 上) |
| btc_re NaN 處理 | fillna(0.0) | fillna(0.0)(經同一函式) | ✅ |
| 候選 adx_1h 對齊 | align_1h_adx_to_15m(同一函式) | adapter 內呼叫同一函式 | ✅ |
| 候選進場評估基準 | 評估 ts 之已收盤 15m 棒(close 為進場價) | 最後一根已封閉 15m 棒 | ✅ |

### F-2. 結論

NOT SEMANTICALLY EQUIVALENT

具體範圍:不一致僅限 btc_re 一項——回測以 BTC 15m(5 小時視窗)計算,前向實作以 BTC 1H(20 小時視窗)計算。btc_adx_1h 與候選 1H ADX 對齊兩項經逐行核對為等價。

### F-3. 誠實歸因申報

此偏離源自 Ox Alpha 的第一輪實作決策:任務指令第 2 節架構圖示「BTC 1H OHLCV ─→ BTC ADX + BTC RE」,故兩者皆建構自 1H 幀,並在當時如實標記「BTC regime 語意等價性」為待確認假設。現有回測原始碼證明該圖示相對真實回測語意有誤導性——回測的 RE 實際來自 15m。Ox Alpha 在無法驗證時未宣稱等價(符合規則),但已實作的程式碼本身攜帶此偏離,必須由治理層裁決,Ox Alpha 不擅自修改。

### F-4. 實務影響(事實陳述,非策略建議)

C3 的 btc_re_lower=0.20 / btc_re_upper=0.40 是對 15m 視窗 RE 校準的界線;前向目前把同一界線套在 1H 視窗 RE 上。兩種統計量的分布不同,故前向的 regime 過濾行為與回測語意不一致——可能系統性放寬或收紧通過率,方向未知(需資料才能判定,不作猜測)。

### F-5. 待裁決之修復方向(二選一,皆超出 Ox Alpha 現有授權)

(a) 前向補抓 BTC 15m 以計算 btc_re(保留 BTC 1H 供 btc_adx_1h),還原回測語意;連帶須修正 _build_btc_regime 與 test_build_btc_regime_matches_manual_range_efficiency(該測試目前固化的是 1H 版語意)。
(b) 治理層正式認可 1H 版為新定義;則須同步更新文件與測試語意,並重新校準界線之意義。

---

## G. C3 是否使用 0.22(Code Fact Verification)

### G-1. check_entry_long 完整原始碼(逐字,v12_strategy.py,未修改檔)

    def check_entry_long(
        row,
        prior_high: float,
        atr: float,
        adx_1h: float,
        btc_regime: Optional[dict] = None,
        mode: str = "C3",
        adx_entry_override: float = 30.0,
        re_threshold_override: float = 0.22,
        btc_re_lower: float = 0.20,
        btc_re_upper: Optional[float] = 0.40,
        audit: Optional[MutableMapping[str, int]] = None,
    ) -> bool:
        _audit(audit, "total_checked")

        required = [row.get("close"), row.get("ema20"), row.get("ema50"), prior_high, atr, adx_1h]
        if any(pd.isna(v) for v in required) or atr <= 0:
            _audit(audit, "fail_nan")
            return False

        btc_regime = btc_regime or {}
        btc_adx_1h = float(btc_regime.get("btc_adx_1h", 0) or 0)
        btc_re = float(btc_regime.get("btc_re", 0) or 0)

        if float(row.get("adx", 0) or 0) < adx_entry_override or float(adx_1h or 0) < 22:
            _audit(audit, "fail_adx")
            return False

        if mode == "C3":
            re_pass = btc_re >= btc_re_lower
            if btc_re_upper is not None:
                re_pass = re_pass and btc_re <= btc_re_upper
            allow_regime = btc_adx_1h >= 30.0 and re_pass
            if not allow_regime:
                _audit(audit, "fail_btc_regime_c3")
                return False
        else:
            if btc_adx_1h < 18:
                _audit(audit, "fail_btc_adx")
                return False

            if btc_re < re_threshold_override:
                _audit(audit, "fail_re")
                return False

        bullish_stack = row["close"] > row["ema20"] > row["ema50"]
        breakout = row["close"] > prior_high
        if not bullish_stack or not breakout:
            _audit(audit, "fail_breakout")
            return False

        _audit(audit, "passed")
        return True

### G-2. Code Facts(僅事實陳述,不含判斷)

1. mode == "C3" 分支只讀取 btc_re_lower、btc_re_upper、btc_adx_1h、btc_re。
2. re_threshold_override 僅在 else(非 C3)分支被讀取(if btc_re < re_threshold_override)。
3. 引擎以 mode="C3" 實例化 adapter(engine.py _setup_strategies)→ 在現行執行路徑上,0.22 不被讀取,為無作用參數;有效界線為 0.20–0.40。
4. Ox Alpha 未據此做任何修改;裁決權在治理層。

### G-3. 0.22 溯源考古摘要(FACT 與 UNKNOWN 分列)

FACT(本地儲存庫可驗證):

1. 引入 commit:38cef46 "Initial QuantCore forward observation deployment"。git log -S "re_threshold_override" 僅命中 38cef46(引入)與 81f8d8d(本次修復,因新增註解提及該字串)。
2. 引入位置:core/strategies/v12_adapter.py 第 29 行 re_threshold_override: float = 0.22(git blame 全檔歸屬同一 commit)。
3. 作者與日期:Sean11231123,2026-05-04 18:50:12 +0800(blame 顯示 ^38cef46 前綴,表示邊界 commit——本地歷史在此之前無更多紀錄)。
4. Commit 訊息不含任何關於 0.22 的理由說明。
5. 同一 commit 同時包含 C3 分支(btc_re_lower=0.20 / btc_re_upper=0.40)與非 C3 分支(使用 re_threshold_override)。
6. backtest/v12_backtest.py 之 simulate_v12_v2 簽名亦含 re_threshold_override=0.22 預設值,與 adapter 同源;C3 下同樣不被讀取。

UNKNOWN(NOT AVAILABLE FROM LOCAL REPOSITORY):

1. 0.22 是刻意覆寫或沿用他處數值 → 無法判定。
2. 早於 38cef46 的任何 commit、PR、issue、討論 → 本地不存在。
3. 後續是否有依賴 0.22 的決策紀錄 → 本地僅有限歷史,無其他證據。

依任務第 6 節要求,Ox Alpha 不對 0.22 之正確性下任何結論。

---

## H. Lookahead Tests(前瞻防護測試)

### H-1. test_filter_closed_bars_drops_forming_and_future_bars(逐字)

    def test_filter_closed_bars_drops_forming_and_future_bars():
        """Evaluation at t cannot consume a forming bar (close > t) or a future bar."""
        engine = make_engine()
        now = datetime.now(timezone.utc)
        opens = [
            now - timedelta(hours=4),    # closes now-3h  -> keep
            now - timedelta(hours=3),    # closes now-2h  -> keep
            now - timedelta(minutes=90), # closes now-30m -> keep
            now - timedelta(minutes=30), # closes now+30m -> DROP (forming)
            now + timedelta(hours=2),    # closes now+3h  -> DROP (future)
        ]
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(opens, utc=True),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
            }
        )
        out = engine._filter_closed_bars(df, "1h", now=now)
        assert len(out) == 3
        assert out["timestamp"].iloc[-1] == pd.Timestamp(now - timedelta(minutes=90))

防止的 failure mode:過濾器放行形成中 K 棒(close > t)或未來 K 棒(open > t)。明確建構兩類敵意 K 棒並斷言剔除,非僅檢查函式可執行。

### H-2. test_align_1h_adx_backward_merge_no_future_leak(逐字)

    def test_align_1h_adx_backward_merge_no_future_leak():
        """
        Core no-lookahead proof: for EVERY 15m row at time t, the merged adx_1h
        must equal the ADX of the last 1H bar whose CLOSE time <= t — verified
        against an independently truncated reference (not implementation internals).
        """
        start = pd.Timestamp("2026-05-01 00:00", tz="UTC")
        n1h = 60
        df1h = make_ohlcv(start.to_pydatetime(), n1h, 60, seed=3)

        # Force an ADX contrast between halves so picking a LATER bar than allowed
        # would produce a detectably different value.
        strong = np.linspace(0.0, 30.0, 30)
        anchor = float(df1h["close"].iloc[29])
        df1h.loc[df1h.index[30:], "close"] = anchor + strong
        df1h.loc[df1h.index[30:], "open"] = anchor + np.concatenate([[0.0], strong[:-1]])
        df1h.loc[df1h.index[30:], "high"] = (
            df1h[["open", "close"]].max(axis=1).iloc[30:] + 0.5
        )
        df1h.loc[df1h.index[30:], "low"] = (
            df1h[["open", "close"]].min(axis=1).iloc[30:] - 0.5
        )

        start15 = start + pd.Timedelta(hours=20)
        df15 = make_ohlcv(start15.to_pydatetime(), 80, 15, seed=4)

        merged = align_1h_adx_to_15m(df15, df1h)
        assert "adx_1h" in merged.columns

        # Independent reference: 1H ADX keyed by candle-CLOSE time.
        ref = shift_candle_open_to_close(compute_v12_15m(df1h), "1h")[
            ["timestamp", "adx"]
        ].sort_values("timestamp").reset_index(drop=True)

        for _, row in merged.iterrows():
            t = row["timestamp"]
            eligible = ref[ref["timestamp"] <= t]
            assert not eligible.empty, f"no closed 1H bar available at {t}"
            expected = eligible["adx"].iloc[-1]
            got = row["adx_1h"]
            if pd.isna(expected):
                assert pd.isna(got)
            else:
                assert got == pytest.approx(float(expected), abs=1e-9)

        # Explicit boundary: a 15m stamp exactly at a 1H close time must consume
        # THAT bar (inclusive), never the following one.
        boundary = start + pd.Timedelta(hours=31)
        assert (ref["timestamp"] == boundary).any(), "boundary 1H close missing"
        brows = merged[merged["timestamp"] == boundary]
        assert len(brows) == 1
        expected = ref.loc[ref["timestamp"] == boundary, "adx"].iloc[-1]
        assert brows["adx_1h"].iloc[0] == pytest.approx(float(expected), abs=1e-9)

防止的 failure mode:合併層的未來 1H 洩漏。方法:人工製造前後半段 ADX 對比(後半強趨勢),再以獨立截斷參照(每列只允許收盤 <= 該列時刻之 1H ADX)逐列比對——若實作選了較晚的 K 棒,數值必不同而失敗。另釘死「15m 戳恰等於 1H 收盤戳」之包含式邊界。此為全套件中最強的時間語意證明。

### H-3. test_signal_path_supplies_full_v12_contract(逐字)

    def test_signal_path_supplies_full_v12_contract():
        """
        Level 1: the forward signal path must fetch candidate 15m + candidate 1H
        + BTC 1H regime data and pass all three into the V12 adapter.
        """
        engine = make_engine()
        now = datetime.now(timezone.utc)

        # End each series >= 2 bars before real 'now' so every bar is closed.
        # The 15m series must exceed V12_MIN_ENTRY_BARS (200) AFTER closed-bar
        # filtering, otherwise the engine legitimately skips signal generation
        # via the insufficient-bars guard and the adapter is never called.
        df15 = make_ohlcv(now - timedelta(minutes=15 * 302), 300, 15, seed=1)
        df1h = make_ohlcv(now - timedelta(hours=62), 60, 60, seed=11)

        stub = StubConnector({(SYMBOL, "15m"): df15, (SYMBOL, "1h"): df1h})
        engine.connectors = {"binance": stub}

        cap = CaptureStrategy()
        engine.strategy_sets[SYMBOL]["strategies"]["v12_trend"] = cap
        engine.strategy_sets[SYMBOL]["router"].route = lambda regime: ["v12_trend"]
        engine._regime_cache[SYMBOL] = (fake_regime(), time.time())

        asyncio.run(engine._signal_generation_once())

        # Both timeframes were actually requested from the connector.
        requested = {(s, tf) for s, tf, _ in stub.calls}
        assert (SYMBOL, "15m") in requested
        assert (SYMBOL, "1h") in requested

        # Adapter received the complete contract.
        assert cap.kwargs is not None, "adapter was never called"
        ohlcv_15m = cap.kwargs["ohlcv_15m"]
        ohlcv_1h = cap.kwargs["ohlcv_1h"]
        btc_regime = cap.kwargs["btc_regime"]

        assert isinstance(ohlcv_15m, pd.DataFrame) and not ohlcv_15m.empty
        assert isinstance(ohlcv_1h, pd.DataFrame) and not ohlcv_1h.empty
        assert isinstance(btc_regime, dict)
        assert "btc_adx_1h" in btc_regime and "btc_re" in btc_regime
        assert math.isfinite(float(btc_regime["btc_adx_1h"]))
        assert math.isfinite(float(btc_regime["btc_re"]))
        # Guard consistency: supplied entry frame satisfies the adapter minimum.
        assert len(ohlcv_15m) >= 200

        # Closed-bar property on supplied frames (evaluation at real now).
        t_now = pd.Timestamp(datetime.now(timezone.utc))
        assert (ohlcv_15m["timestamp"].iloc[-1] + pd.Timedelta(minutes=15)) <= t_now
        assert (ohlcv_1h["timestamp"].iloc[-1] + pd.Timedelta(hours=1)) <= t_now

防止的 failure mode:原始整合缺陷類別的回歸——adapter 被呼叫時缺 ohlcv_1h / btc_regime、或收到錯誤 TF 幀;同時斷言兩個 TF 都真的向 connector 請求、供應幀尾端滿足封閉性、>= 200 根。

### H-4. 三項指定 failure mode 之涵蓋判定(誠實回答)

| Failure mode | 涵蓋狀態 | 證據 |
|---|---|---|
| future 1H bar | ✅ 可捕捉 | H-2 於合併層結構性排除(選取條件與數值無關);H-1 於過濾層排除 |
| forming 1H bar | ✅ 可捕捉 | H-1 明確建構 close > t 之 K 棒並斷言剔除;H-3 斷言供應幀尾端封閉 |
| future BTC regime bar | ⚠️ 組合式涵蓋,非專用敵意測試 | _build_btc_regime 僅消費 _filter_closed_bars 輸出(程式碼結構保證),而過濾器本身經 H-1 泛用驗證;但沒有專門測試「注入含未來 BTC 1H 棒的序列穿過 _signal_generation_once,斷言 btc_regime 忽略它」。此殘餘缺口如實申報,是否需補測由 ChatGPT 裁決 |

### H-5. 測試執行紀錄(全部由 Sean 本地執行,FACT)

環境:win32 / Python 3.12.2 / pytest 9.1.1 / pluggy 1.6.0 / plugin anyio-4.12.1。

1. 第一次執行:10 passed in 1.66s(此輸出隨後被誤寫入 engine.py,成為 5bb63a0 污染源)。
2. 第二次執行(engine.py 還原後):10 passed in 1.64s。
3. 第三次執行(污染檔案刪除後之最新 working tree):10 passed in 2.69s —— collected 10 items,10 passed / 0 failed / 0 error,無警告。

Syntax / Lint(修復輪驗證):

- python -m py_compile engine.py → PASS(無輸出)
- python -m flake8 --select=E9,F821,F823,F831,F406,F407,F701,F702,F704,F706 --show-source --isolated engine.py → PASS(無輸出)
- 附註:一次全庫預設 flake8 顯示大量既有風格債(E501/E402/F401/W293 等,分布於 backtest/、scripts/、notifications/ 等),其中零 E9 語法錯誤;依治理指令第 11 節不做清理。

---

## I. Repository Status

NO MODIFICATIONS MADE

本證據彙整輪零修改:未 edit、未 commit、未 push、未 merge、未 deploy、未動 .gitignore、未動 __pycache__、未動 V12 implementation、未動 tests。

工作樹狀態(最後已知,FACT):除四個未追蹤 __pycache__/ 目錄外乾淨。成因推定:faf42a2 精簡 .gitignore 時移除了 bytecode 忽略規則。非 corruption、不影響測試與審查;是否補回忽略規則留待裁決。

---

## J. Validation Levels(驗證等級,不得過度宣稱)

- Level 1(介面/資料管線回歸):✅ 已驗證 —— test_signal_path_supplies_full_v12_contract 等 10 項全數通過。
- Level 2(歷史訊號 schema sanity):✅ 已驗證 —— 欄位齊全、數值合理(entry / ADX entry / ADX confirm / BTC RE / BTC ADX confirm)。附註:歷史 btc_re=0.31 之出身為 15m 視窗(見 E-2.6),Level 2 比對基準應據此理解。
- Level 3(2026-05-04 確定性重播):NOT AVAILABLE —— 原始 OHLCV 不在儲存庫,未做重播,不宣稱。

宇宙範圍聲明:BTC/USDT:USDT → 範圍內、已驗證;SOL 及其他歷史標的 → 範圍外、未驗證;歷史 SOL 紀錄(entry=148.5 等)僅作 schema 參考,不得解讀為現行 SOL 驗證。

---

## K. 交予 ChatGPT 之審查清單

1. A:以 A-2/A-3 之 git 證據獨立複核 intended diff 與凍結項目零觸碰;知悉 5bb63a0 訊息誤導性與歷史殘留污染之治理選項(A-6)。
2. B/C/H:獨立驗證封閉 K 棒政策(<= 邊界 × backward 合併)之無前瞻保證;裁定 clock skew 殘餘風險(B-4)可接受性;裁定是否需補「future BTC regime bar」專用敵意測試(H-4)。
3. D/E/F:複核 btc_re 15m vs 1h 分歧之事實認定(F-1/F-2);裁決修復方向(F-5 二選一);連帶注意 test_build_btc_regime_matches_manual_range_efficiency 固化的是 1H 版語意,任何修復須同步。
4. G:將「C3 下 0.22 為無作用參數」提交治理層裁決(G-2/G-3);Ox Alpha 未修改。
5. 重現性:於乾淨環境重跑 python -m pytest tests/test_v12_integration_contract.py -v,確認 10 passed 可重現(最新本地結果 2.69s)。
6. Level 3 缺口:向 Sean/Claude 確認是否另行取得 2026-05-04 OHLCV 以補做確定性重播。
7. 選擇性:backtest/validation_suite.py 加入對話,可將 F 節結論從「推定適用全研究管線」升級為「逐行確認」。

---

## L. Assumptions 與 Unresolved Risks

Assumptions(Ox Alpha 於實作期間明示之假設):

1. 交易所回傳時間戳為 K 棒開盤時間(ccxt/Binance 標準慣例)。
2. 主機系統時鐘大致準確(封閉過濾以本地 UTC 時間為基準)。
3. ~~BTC regime 之 ADX/RE 以 compute_v12_15m 計算即等同回測語意~~ —— 此假設已被 backtest/v12_backtest.py 原始碼駁回(僅 btc_adx_1h 成立;btc_re 不成立,見 F 節)。

Unresolved / Risks:

1. btc_re 前向/回測語意分歧(F 節)—— 最高優先待裁決項。
2. Clock skew 殘餘風險(B-4)。
3. 0.22 意圖不明(G-3 UNKNOWN);其在 C3 下為無作用參數之事實待治理裁決。
4. Level 3 不可得(J 節)。
5. git 歷史保留兩個污染引入點之內容(A-6)。
6. 未追蹤 __pycache__/ 目錄(I 節附註)。
7. 次要效率觀察(未修復,依最小變更原則申報):當候選標的即為 BTC 時,每輪重複抓取一次 BTC 1H(regime 用 + 候選用),無害冗餘。

---

(本文件完。編製:Ox Alpha;供 ChatGPT implementation review 使用。)
