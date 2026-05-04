import { useState, useEffect, useRef } from "react";
import { LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from "recharts";

// ── Simulated live data ───────────────────────────────────────────────────────
const generatePnlHistory = () => {
    const data = [];
    let val = 10000;
    for (let i = 120; i >= 0; i--) {
        const change = (Math.random() - 0.46) * 180;
        val = Math.max(val + change, 8000);
        const d = new Date(Date.now() - i * 5 * 60 * 1000);
        data.push({
            time: d.getHours().toString().padStart(2, "0") + ":" + d.getMinutes().toString().padStart(2, "0"),
            value: parseFloat(val.toFixed(2)),
            pnl: parseFloat((val - 10000).toFixed(2)),
        });
    }
    return data;
};

const REGIMES = {
    trending_bull: { label: "TRENDING ▲", color: "#00ffa3", bg: "rgba(0,255,163,0.08)" },
    trending_bear: { label: "TRENDING ▼", color: "#ff4d6d", bg: "rgba(255,77,109,0.08)" },
    ranging: { label: "RANGING ⟷", color: "#ffd166", bg: "rgba(255,209,102,0.08)" },
    high_volatility: { label: "HIGH VOL ⚡", color: "#f77f00", bg: "rgba(247,127,0,0.08)" },
    low_volatility: { label: "LOW VOL ◎", color: "#90e0ef", bg: "rgba(144,224,239,0.08)" },
    breakout: { label: "BREAKOUT ⬆", color: "#c77dff", bg: "rgba(199,125,255,0.08)" },
};

const STRATEGY_COLORS = {
    trend_following: "#00ffa3",
    mean_reversion: "#ffd166",
    arbitrage: "#90e0ef",
    market_making: "#c77dff",
};

const MOCK_STATE = {
    capital: 0,
    peak: 0,
    dailyPnl: 0,
    totalPnl: 0,
    drawdown: 0,
    openPositions: 0,
    tradesToday: 0,
    winRate: 0,
    sharpe: 0,
    regimes: {},
    positions: [],
    recentTrades: [],
    engine_status: "offline",
};

const API_BASE = import.meta.env?.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const normalizeV12Data = (api) => {
    if (!api) return null;

    return {
        capital: api.portfolio?.capital ?? 0,
        peak: api.portfolio?.peak ?? 0,
        dailyPnl: api.pnl?.daily ?? 0,
        totalPnl: api.pnl?.total ?? 0,
        drawdown: api.risk?.drawdown ?? 0,
        openPositions: api.positions?.length ?? 0,
        tradesToday: api.trades?.today ?? 0,
        winRate: api.metrics?.win_rate ?? 0,
        sharpe: api.metrics?.sharpe ?? 0,

        regimes: api.market?.regimes ?? {},
        positions: api.positions ?? [],
        recentTrades: api.trades?.recent ?? [],

        // ⭐ V12 missing layer (IMPORTANT)
        engine_status: api.engine?.status ?? "unknown",
        signal_quality: api.metrics?.signal_quality ?? 0,
        strategy_allocation: api.strategy?.allocation ?? {},
        risk: api.risk ?? {},
    };
};

const isValidV12 = (data) => {
    return data
        && data.portfolio
        && data.pnl
        && data.market
        && data.positions
        && data.trades;
};

const useV12Data = () => {
    const [data, setData] = useState(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/v12/live`);
                const json = await res.json();
                setData(json);
            } catch (e) {
                console.log("V12 data not available, using mock");
                setData(null);
            }
        };

        fetchData();
        const t = setInterval(fetchData, 5000);
        return () => clearInterval(t);
    }, []);

    if (!isValidV12(data)) {
        return MOCK_STATE;
    }

    return normalizeV12Data(data);
};

// ── Sparkline data for strategy performance ───────────────────────────────────
const strategyPerfData = [
    { name: "trend_following", win: 68, trades: 47, pnl: 412.20 },
    { name: "mean_reversion", win: 62, trades: 38, pnl: 228.80 },
    { name: "arbitrage", win: 89, trades: 22, pnl: 134.40 },
    { name: "market_making", win: 71, trades: 81, pnl: 71.93 },
];

// ── Helper ────────────────────────────────────────────────────────────────────
const fmt = (n, dec = 2) => n?.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
const pct = (n) => (n >= 0 ? "+" : "") + (n * 100).toFixed(2) + "%";
const sign = (n) => (n >= 0 ? "+" : "") + fmt(n);

export default function QuantDashboard() {
    const apiState = useV12Data();
    const state = apiState || MOCK_STATE;
    const [pnlHistory] = useState(generatePnlHistory);
    const [activeTab, setActiveTab] = useState("overview");
    const [tick, setTick] = useState(0);
    const systemOn = state.engine_status === "running";

    useEffect(() => {
        const t = setInterval(() => setTick(x => x + 1), 3000);
        return () => clearInterval(t);
    }, []);

    const drawdownColor = state.drawdown > 8 ? "#ff4d6d" : state.drawdown > 5 ? "#f77f00" : "#00ffa3";
    const currentCapital = state.capital;
    const sendControl = async (action) => {
        try {
            await fetch(`${API_BASE}/api/v12/control`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action }),
            });
        } catch (e) {
            console.log("V12 control not available");
        }
    };

    return (
        <div style={{
            background: "#070b14",
            minHeight: "100vh",
            color: "#c8d8e8",
            fontFamily: "'DM Mono', 'Courier New', monospace",
            position: "relative",
            overflow: "hidden",
        }}>
            {/* Google Font */}
            <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Syncopate:wght@400;700&display=swap');

        * { box-sizing: border-box; }

        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #0d1520; }
        ::-webkit-scrollbar-thumb { background: #1e3a5f; border-radius: 2px; }

        @keyframes scanline {
          0%   { transform: translateY(-100%); }
          100% { transform: translateY(100vh); }
        }
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.4; transform: scale(0.7); }
        }
        @keyframes fade-in {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0; }
        }
        .panel {
          background: rgba(13, 21, 32, 0.9);
          border: 1px solid rgba(0, 180, 220, 0.12);
          border-radius: 4px;
          position: relative;
          overflow: hidden;
          animation: fade-in 0.4s ease both;
        }
        .panel::before {
          content: '';
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 1px;
          background: linear-gradient(90deg, transparent, rgba(0,200,255,0.4), transparent);
        }
        .tab-btn {
          background: none;
          border: none;
          font-family: 'DM Mono', monospace;
          font-size: 11px;
          letter-spacing: 0.12em;
          padding: 8px 18px;
          cursor: pointer;
          border-bottom: 2px solid transparent;
          transition: all 0.2s;
        }
        .tab-btn.active {
          color: #00d4ff;
          border-bottom-color: #00d4ff;
        }
        .tab-btn:not(.active) {
          color: #4a6880;
        }
        .tab-btn:hover:not(.active) { color: #7aa8c8; }

        .regime-badge {
          font-family: 'Syncopate', sans-serif;
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.1em;
          padding: 4px 10px;
          border-radius: 2px;
        }
        .metric-label {
          font-size: 9px;
          letter-spacing: 0.18em;
          color: #3d6280;
          text-transform: uppercase;
        }
        .metric-value {
          font-family: 'Syncopate', sans-serif;
          font-size: 18px;
          letter-spacing: 0.02em;
          line-height: 1.1;
        }
        .trade-row:hover { background: rgba(0,200,255,0.03); }
        .grid-bg {
          position: fixed;
          inset: 0;
          background-image:
            linear-gradient(rgba(0,180,220,0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(0,180,220,0.03) 1px, transparent 1px);
          background-size: 40px 40px;
          pointer-events: none;
        }
      `}</style>

            <div className="grid-bg" />

            {/* Scanline effect */}
            <div style={{
                position: "fixed", top: 0, left: 0, right: 0, height: "120px",
                background: "linear-gradient(to bottom, transparent, rgba(0,200,255,0.015), transparent)",
                animation: "scanline 8s linear infinite", pointerEvents: "none", zIndex: 1,
            }} />

            {/* ── Header ─────────────────────────────────────────────────── */}
            <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "16px 28px", borderBottom: "1px solid rgba(0,180,220,0.1)",
                background: "rgba(7,11,20,0.95)", position: "sticky", top: 0, zIndex: 50,
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                    <div style={{ fontFamily: "'Syncopate', sans-serif", fontSize: 13, fontWeight: 700, letterSpacing: "0.15em", color: "#00d4ff" }}>
                        QUANT<span style={{ color: "#c77dff" }}>CORE</span>
                    </div>
                    <div style={{ fontSize: 9, color: "#2a4a6a", letterSpacing: "0.2em" }}>MULTI-LAYER CRYPTO ENGINE v2.0</div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
                    {/* Live indicator */}
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <div style={{
                            width: 6, height: 6, borderRadius: "50%",
                            background: systemOn ? "#00ffa3" : "#ff4d6d",
                            animation: systemOn ? "pulse-dot 1.5s ease-in-out infinite" : "none",
                        }} />
                        <span style={{ fontSize: 9, letterSpacing: "0.18em", color: systemOn ? "#00ffa3" : "#ff4d6d" }}>
                            {systemOn ? "LIVE" : "HALTED"}
                        </span>
                    </div>

                    {/* Clock */}
                    <div style={{ fontSize: 11, color: "#3d6280", letterSpacing: "0.1em" }}>
                        {new Date().toLocaleTimeString("en-GB")}
                    </div>

                    {/* Toggle */}
                    <button onClick={() => sendControl(systemOn ? "stop" : "start")} style={{
                        background: systemOn ? "rgba(0,255,163,0.08)" : "rgba(255,77,109,0.08)",
                        border: `1px solid ${systemOn ? "rgba(0,255,163,0.3)" : "rgba(255,77,109,0.3)"}`,
                        color: systemOn ? "#00ffa3" : "#ff4d6d",
                        padding: "5px 14px", borderRadius: 2, cursor: "pointer",
                        fontFamily: "'Syncopate', sans-serif", fontSize: 9, letterSpacing: "0.12em",
                        transition: "all 0.2s",
                    }}>
                        {systemOn ? "RUNNING" : "STOPPED"}
                    </button>
                </div>
            </div>

            {/* ── Tab Nav ─────────────────────────────────────────────────── */}
            <div style={{
                display: "flex", gap: 0, padding: "0 28px",
                borderBottom: "1px solid rgba(0,180,220,0.08)",
                background: "rgba(7,11,20,0.7)",
            }}>
                {["overview", "positions", "strategies", "trades", "settings"].map(tab => (
                    <button key={tab} className={`tab-btn ${activeTab === tab ? "active" : ""}`}
                        onClick={() => setActiveTab(tab)}
                    >{tab.toUpperCase()}</button>
                ))}
            </div>

            {/* ── Main Content ─────────────────────────────────────────────── */}
            <div style={{ padding: "20px 28px", maxWidth: 1400, margin: "0 auto" }}>

                {activeTab === "overview" && (
                    <div style={{ display: "grid", gap: 16 }}>

                        {/* Top KPI row */}
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 12 }}>
                            {[
                                { label: "Portfolio NAV", value: `$${fmt(currentCapital)}`, color: "#c8d8e8" },
                                { label: "Total P&L", value: sign(state.totalPnl), color: state.totalPnl >= 0 ? "#00ffa3" : "#ff4d6d", suffix: " USDT" },
                                { label: "Today's P&L", value: sign(state.dailyPnl), color: state.dailyPnl >= 0 ? "#00ffa3" : "#ff4d6d" },
                                { label: "Max Drawdown", value: state.drawdown.toFixed(2) + "%", color: drawdownColor },
                                { label: "Sharpe Ratio", value: state.sharpe.toFixed(2), color: "#c77dff" },
                                { label: "Win Rate", value: (state.winRate * 100).toFixed(1) + "%", color: "#ffd166" },
                            ].map(({ label, value, color, suffix }) => (
                                <div key={label} className="panel" style={{ padding: "14px 16px" }}>
                                    <div className="metric-label">{label}</div>
                                    <div className="metric-value" style={{ color, marginTop: 6, fontSize: 15 }}>
                                        {value}
                                        {suffix && <span style={{ fontSize: 10, color: "#3d6280" }}>{suffix}</span>}
                                    </div>
                                </div>
                            ))}
                        </div>

                        {/* PnL Chart + Regime Status */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16 }}>

                            {/* Chart */}
                            <div className="panel" style={{ padding: "18px 20px" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                                    <div style={{ fontSize: 9, letterSpacing: "0.18em", color: "#3d6280" }}>PORTFOLIO VALUE (USDT) — LAST 10H</div>
                                    <div style={{ fontSize: 11, color: "#00ffa3" }}>+{pct(state.totalPnl / 10000)}</div>
                                </div>
                                <ResponsiveContainer width="100%" height={200}>
                                    <AreaChart data={pnlHistory} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                                        <defs>
                                            <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="5%" stopColor="#00d4ff" stopOpacity={0.18} />
                                                <stop offset="95%" stopColor="#00d4ff" stopOpacity={0} />
                                            </linearGradient>
                                        </defs>
                                        <XAxis dataKey="time" tick={{ fontSize: 8, fill: "#2a4a6a" }} interval={24} />
                                        <YAxis domain={["auto", "auto"]} tick={{ fontSize: 8, fill: "#2a4a6a" }} />
                                        <Tooltip
                                            contentStyle={{ background: "#0d1520", border: "1px solid #1e3a5f", borderRadius: 2, fontSize: 11 }}
                                            labelStyle={{ color: "#7aa8c8" }}
                                            itemStyle={{ color: "#00d4ff" }}
                                        />
                                        <Area type="monotone" dataKey="value" stroke="#00d4ff" strokeWidth={1.5}
                                            fill="url(#pnlGrad)" dot={false} />
                                    </AreaChart>
                                </ResponsiveContainer>
                            </div>

                            {/* Market Regime Panel */}
                            <div className="panel" style={{ padding: "18px 20px" }}>
                                <div style={{ fontSize: 9, letterSpacing: "0.18em", color: "#3d6280", marginBottom: 14 }}>MARKET REGIME DETECTOR</div>
                                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                                    {Object.entries(state.regimes).map(([symbol, info]) => {
                                        const regimeKey = info?.regime ?? "ranging";
                                        const r = REGIMES[regimeKey] || REGIMES.ranging;
                                        return (
                                            <div key={symbol} style={{ background: r.bg, border: `1px solid ${r.color}22`, borderRadius: 3, padding: "12px 14px" }}>
                                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                                                    <span style={{ fontSize: 11, color: "#c8d8e8", letterSpacing: "0.08em" }}>{symbol}</span>
                                                    <span className="regime-badge" style={{ color: r.color, background: `${r.color}15` }}>{r.label}</span>
                                                </div>
                                                {/* Confidence bar */}
                                                <div style={{ marginBottom: 8 }}>
                                                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                                                        <span style={{ fontSize: 8, color: "#3d6280", letterSpacing: "0.15em" }}>CONFIDENCE</span>
                                                        <span style={{ fontSize: 9, color: r.color }}>{(info.confidence * 100).toFixed(0)}%</span>
                                                    </div>
                                                    <div style={{ height: 3, background: "rgba(255,255,255,0.05)", borderRadius: 2 }}>
                                                        <div style={{ height: "100%", width: `${info.confidence * 100}%`, background: r.color, borderRadius: 2, transition: "width 0.5s" }} />
                                                    </div>
                                                </div>
                                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                                    {(info.strategies ?? []).map(s => (
                                                        <span key={s} style={{
                                                            fontSize: 8, padding: "2px 7px", borderRadius: 2,
                                                            background: `${STRATEGY_COLORS[s]}15`,
                                                            color: STRATEGY_COLORS[s],
                                                            border: `1px solid ${STRATEGY_COLORS[s]}30`,
                                                            letterSpacing: "0.05em",
                                                        }}>{s.replace("_", " ")}</span>
                                                    ))}
                                                </div>
                                                <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
                                                    <span style={{ fontSize: 8, color: "#3d6280" }}>ADX <span style={{ color: "#7aa8c8" }}>{info.adx.toFixed(1)}</span></span>
                                                    <span style={{ fontSize: 8, color: "#3d6280" }}>VOL <span style={{ color: "#7aa8c8" }}>{info.vol.toFixed(2)}</span></span>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>

                                {/* System stats */}
                                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid rgba(0,180,220,0.08)" }}>
                                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                                        {[
                                            { label: "Open Positions", value: state.openPositions },
                                            { label: "Trades Today", value: state.tradesToday },
                                        ].map(({ label, value }) => (
                                            <div key={label}>
                                                <div style={{ fontSize: 8, color: "#3d6280", letterSpacing: "0.15em", marginBottom: 2 }}>{label}</div>
                                                <div style={{ fontSize: 16, fontFamily: "'Syncopate', sans-serif", color: "#c8d8e8" }}>{value}</div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Positions table preview */}
                        <div className="panel" style={{ padding: "18px 20px" }}>
                            <div style={{ fontSize: 9, letterSpacing: "0.18em", color: "#3d6280", marginBottom: 14 }}>OPEN POSITIONS</div>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                                <thead>
                                    <tr style={{ borderBottom: "1px solid rgba(0,180,220,0.08)" }}>
                                        {["Symbol", "Strategy", "Side", "Size", "Entry", "Mark", "Unr. PnL", "Exchange"].map(h => (
                                            <th key={h} style={{ textAlign: "left", padding: "0 10px 8px 0", fontSize: 8, color: "#3d6280", letterSpacing: "0.15em", fontWeight: 400 }}>{h}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {state.positions.map((pos, i) => (
                                        <tr key={i} className="trade-row" style={{ borderBottom: "1px solid rgba(0,180,220,0.04)" }}>
                                            <td style={{ padding: "10px 10px 10px 0", color: "#c8d8e8" }}>{pos.symbol}</td>
                                            <td style={{ padding: "10px 10px 10px 0" }}>
                                                <span style={{ color: STRATEGY_COLORS[pos.strategy], fontSize: 10 }}>{pos.strategy.replace("_", " ")}</span>
                                            </td>
                                            <td style={{ padding: "10px 10px 10px 0", color: pos.side === "LONG" ? "#00ffa3" : "#ff4d6d", fontFamily: "'Syncopate',sans-serif", fontSize: 9 }}>{pos.side}</td>
                                            <td style={{ padding: "10px 10px 10px 0" }}>{pos.size}</td>
                                            <td style={{ padding: "10px 10px 10px 0" }}>${fmt(pos.entry)}</td>
                                            <td style={{ padding: "10px 10px 10px 0" }}>${fmt(pos.current)}</td>
                                            <td style={{ padding: "10px 10px 10px 0", color: pos.pnl >= 0 ? "#00ffa3" : "#ff4d6d" }}>{sign(pos.pnl)}</td>
                                            <td style={{ padding: "10px 0", color: "#4a6880", fontSize: 10 }}>{pos.exchange}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                    </div>
                )}

                {activeTab === "strategies" && (
                    <div style={{ display: "grid", gap: 16 }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                            {strategyPerfData.map(s => {
                                const color = STRATEGY_COLORS[s.name];
                                const barData = Array.from({ length: 20 }, (_, i) => ({
                                    i, v: Math.random() * (s.win / 100) * 80 + 10
                                }));
                                return (
                                    <div key={s.name} className="panel" style={{ padding: "20px 22px" }}>
                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                                            <div>
                                                <div style={{ fontFamily: "'Syncopate',sans-serif", fontSize: 11, color, letterSpacing: "0.08em" }}>
                                                    {s.name.replace(/_/g, " ").toUpperCase()}
                                                </div>
                                                <div style={{ fontSize: 8, color: "#3d6280", marginTop: 4, letterSpacing: "0.15em" }}>
                                                    {s.trades} TRADES EXECUTED
                                                </div>
                                            </div>
                                            <div style={{ textAlign: "right" }}>
                                                <div style={{ color: "#00ffa3", fontFamily: "'Syncopate',sans-serif", fontSize: 14 }}>+${fmt(s.pnl)}</div>
                                                <div style={{ fontSize: 9, color: "#3d6280", marginTop: 2 }}>Total PnL</div>
                                            </div>
                                        </div>

                                        {/* Win rate bar */}
                                        <div style={{ marginBottom: 12 }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                                <span style={{ fontSize: 8, color: "#3d6280", letterSpacing: "0.12em" }}>WIN RATE</span>
                                                <span style={{ fontSize: 10, color }}>{s.win}%</span>
                                            </div>
                                            <div style={{ height: 4, background: "rgba(255,255,255,0.04)", borderRadius: 2 }}>
                                                <div style={{ height: "100%", width: `${s.win}%`, background: color, borderRadius: 2 }} />
                                            </div>
                                        </div>

                                        {/* Mini bar chart */}
                                        <ResponsiveContainer width="100%" height={60}>
                                            <BarChart data={barData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                                                <Bar dataKey="v" radius={[1, 1, 0, 0]}>
                                                    {barData.map((_, idx) => (
                                                        <Cell key={idx} fill={`${color}${idx % 3 === 0 ? "cc" : "44"}`} />
                                                    ))}
                                                </Bar>
                                            </BarChart>
                                        </ResponsiveContainer>

                                        {/* Regime routing */}
                                        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid rgba(0,180,220,0.06)" }}>
                                            <div style={{ fontSize: 8, color: "#3d6280", letterSpacing: "0.12em", marginBottom: 6 }}>ACTIVE IN REGIMES</div>
                                            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                                                {({
                                                    trend_following: ["trending_bull", "trending_bear", "breakout"],
                                                    mean_reversion: ["ranging", "low_volatility"],
                                                    arbitrage: ["ranging", "low_volatility"],
                                                    market_making: ["high_volatility", "low_volatility"],
                                                }[s.name] || []).map(r => (
                                                    <span key={r} style={{
                                                        fontSize: 7, padding: "2px 6px", borderRadius: 2,
                                                        background: `${REGIMES[r]?.color}12`,
                                                        color: REGIMES[r]?.color, letterSpacing: "0.05em",
                                                        border: `1px solid ${REGIMES[r]?.color}25`,
                                                    }}>{REGIMES[r]?.label}</span>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>

                        {/* Layer Architecture diagram */}
                        <div className="panel" style={{ padding: "20px 22px" }}>
                            <div style={{ fontSize: 9, letterSpacing: "0.18em", color: "#3d6280", marginBottom: 16 }}>SYSTEM ARCHITECTURE — MULTI-LAYER FLOW</div>
                            <div style={{ display: "flex", alignItems: "center", gap: 0, overflowX: "auto" }}>
                                {[
                                    { layer: "L1", name: "Market Regime\nDetector", color: "#00d4ff", desc: "ADX · Hurst · ATR · BB Width" },
                                    { layer: "L2", name: "Strategy\nRouter", color: "#c77dff", desc: "Regime → Strategy Mapping" },
                                    { layer: "L3", name: "Signal\nGenerator", color: "#ffd166", desc: "4 Strategy Modules" },
                                    { layer: "L4", name: "Risk\nManager", color: "#f77f00", desc: "Drawdown · Size · Exposure" },
                                    { layer: "L5", name: "Exchange\nConnector", color: "#00ffa3", desc: "Binance · OKX Futures" },
                                ].map((item, i) => (
                                    <div key={i} style={{ display: "flex", alignItems: "center" }}>
                                        <div style={{
                                            minWidth: 160, padding: "14px 16px",
                                            background: `${item.color}08`,
                                            border: `1px solid ${item.color}25`,
                                            borderRadius: 3,
                                        }}>
                                            <div style={{ fontSize: 8, color: item.color, letterSpacing: "0.15em", marginBottom: 4 }}>{item.layer}</div>
                                            <div style={{ fontSize: 11, color: "#c8d8e8", whiteSpace: "pre-line", lineHeight: 1.3, marginBottom: 6 }}>{item.name}</div>
                                            <div style={{ fontSize: 8, color: "#3d6280" }}>{item.desc}</div>
                                        </div>
                                        {i < 4 && (
                                            <div style={{ padding: "0 8px", color: "#2a4a6a", fontSize: 16 }}>→</div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}

                {activeTab === "positions" && (
                    <div className="panel" style={{ padding: "20px 22px" }}>
                        <div style={{ fontSize: 9, letterSpacing: "0.18em", color: "#3d6280", marginBottom: 16 }}>OPEN POSITIONS — FUTURES/PERP</div>
                        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                            <thead>
                                <tr style={{ borderBottom: "1px solid rgba(0,180,220,0.1)" }}>
                                    {["Symbol", "Strategy", "Side", "Size", "Entry Price", "Mark Price", "Unr. PnL", "% PnL", "Exchange", "Action"].map(h => (
                                        <th key={h} style={{ textAlign: "left", padding: "0 12px 10px 0", fontSize: 8, color: "#3d6280", letterSpacing: "0.12em", fontWeight: 400 }}>{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {state.positions.map((pos, i) => {
                                    const pnlPct = ((pos.current - pos.entry) / pos.entry) * (pos.side === "SHORT" ? -1 : 1);
                                    return (
                                        <tr key={i} className="trade-row" style={{ borderBottom: "1px solid rgba(0,180,220,0.04)" }}>
                                            <td style={{ padding: "12px 12px 12px 0", color: "#c8d8e8", fontFamily: "'Syncopate',sans-serif", fontSize: 10 }}>{pos.symbol}</td>
                                            <td style={{ padding: "12px 12px 12px 0" }}>
                                                <span style={{ color: STRATEGY_COLORS[pos.strategy], fontSize: 10 }}>{pos.strategy.replace("_", " ")}</span>
                                            </td>
                                            <td style={{ padding: "12px 12px 12px 0", color: pos.side === "LONG" ? "#00ffa3" : "#ff4d6d", fontFamily: "'Syncopate',sans-serif", fontSize: 10 }}>{pos.side}</td>
                                            <td style={{ padding: "12px 12px 12px 0" }}>{pos.size}</td>
                                            <td style={{ padding: "12px 12px 12px 0" }}>${fmt(pos.entry)}</td>
                                            <td style={{ padding: "12px 12px 12px 0" }}>${fmt(pos.current)}</td>
                                            <td style={{ padding: "12px 12px 12px 0", color: pos.pnl >= 0 ? "#00ffa3" : "#ff4d6d" }}>{sign(pos.pnl)}</td>
                                            <td style={{ padding: "12px 12px 12px 0", color: pnlPct >= 0 ? "#00ffa3" : "#ff4d6d" }}>{pct(pnlPct)}</td>
                                            <td style={{ padding: "12px 12px 12px 0", color: "#4a6880", fontSize: 10 }}>{pos.exchange}</td>
                                            <td style={{ padding: "12px 0" }}>
                                                <button style={{
                                                    background: "rgba(255,77,109,0.08)", border: "1px solid rgba(255,77,109,0.25)",
                                                    color: "#ff4d6d", padding: "4px 10px", borderRadius: 2, cursor: "pointer",
                                                    fontSize: 9, fontFamily: "'DM Mono',monospace", letterSpacing: "0.05em",
                                                }}>CLOSE</button>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}

                {activeTab === "trades" && (
                    <div className="panel" style={{ padding: "20px 22px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                            <div style={{ fontSize: 9, letterSpacing: "0.18em", color: "#3d6280" }}>TRADE LOG — TODAY</div>
                            <div style={{ fontSize: 9, color: "#3d6280" }}>{state.recentTrades.length} TRADES</div>
                        </div>
                        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                            <thead>
                                <tr style={{ borderBottom: "1px solid rgba(0,180,220,0.1)" }}>
                                    {["Time", "Symbol", "Strategy", "Side", "Qty", "Price", "Status", "Realized PnL"].map(h => (
                                        <th key={h} style={{ textAlign: "left", padding: "0 12px 10px 0", fontSize: 8, color: "#3d6280", letterSpacing: "0.12em", fontWeight: 400 }}>{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {state.recentTrades.map((t, i) => (
                                    <tr key={i} className="trade-row" style={{ borderBottom: "1px solid rgba(0,180,220,0.04)", opacity: t.status === "rejected" ? 0.4 : 1 }}>
                                        <td style={{ padding: "10px 12px 10px 0", color: "#4a6880", fontSize: 10 }}>{t.time}</td>
                                        <td style={{ padding: "10px 12px 10px 0", color: "#c8d8e8" }}>{t.symbol}</td>
                                        <td style={{ padding: "10px 12px 10px 0", color: STRATEGY_COLORS[t.strategy], fontSize: 10 }}>{t.strategy.replace("_", " ")}</td>
                                        <td style={{ padding: "10px 12px 10px 0", color: t.side === "BUY" ? "#00ffa3" : "#ff4d6d", fontFamily: "'Syncopate',sans-serif", fontSize: 9 }}>{t.side}</td>
                                        <td style={{ padding: "10px 12px 10px 0" }}>{t.qty}</td>
                                        <td style={{ padding: "10px 12px 10px 0" }}>${fmt(t.price)}</td>
                                        <td style={{ padding: "10px 12px 10px 0" }}>
                                            <span style={{
                                                fontSize: 8, padding: "2px 8px", borderRadius: 2, letterSpacing: "0.08em",
                                                background: t.status === "filled" ? "rgba(0,255,163,0.08)" : "rgba(255,77,109,0.08)",
                                                color: t.status === "filled" ? "#00ffa3" : "#ff4d6d",
                                                border: `1px solid ${t.status === "filled" ? "rgba(0,255,163,0.2)" : "rgba(255,77,109,0.2)"}`,
                                            }}>{t.status.toUpperCase()}</span>
                                        </td>
                                        <td style={{ padding: "10px 0", color: t.pnl === null ? "#3d6280" : t.pnl >= 0 ? "#00ffa3" : "#ff4d6d" }}>
                                            {t.pnl === null ? "—" : sign(t.pnl)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}

                {activeTab === "settings" && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                        {/* Risk limits */}
                        <div className="panel" style={{ padding: "20px 22px" }}>
                            <div style={{ fontSize: 9, letterSpacing: "0.18em", color: "#3d6280", marginBottom: 16 }}>RISK PARAMETERS</div>
                            {[
                                { label: "Max Drawdown", value: "10.00%", color: "#ff4d6d" },
                                { label: "Daily Loss Limit", value: "3.00%", color: "#f77f00" },
                                { label: "Max Open Positions", value: "5", color: "#ffd166" },
                                { label: "Max Total Exposure", value: "50.00%", color: "#ffd166" },
                                { label: "Min Signal Confidence", value: "55.00%", color: "#c77dff" },
                                { label: "Position Size Limit", value: "15.00%", color: "#00d4ff" },
                            ].map(({ label, value, color }) => (
                                <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px solid rgba(0,180,220,0.05)" }}>
                                    <span style={{ fontSize: 11, color: "#7aa8c8" }}>{label}</span>
                                    <span style={{ fontFamily: "'Syncopate',sans-serif", fontSize: 12, color }}>{value}</span>
                                </div>
                            ))}
                        </div>

                        {/* Exchange config */}
                        <div className="panel" style={{ padding: "20px 22px" }}>
                            <div style={{ fontSize: 9, letterSpacing: "0.18em", color: "#3d6280", marginBottom: 16 }}>EXCHANGE CONFIGURATION</div>
                            {["Binance", "OKX"].map(ex => (
                                <div key={ex} style={{ marginBottom: 16, padding: "14px", background: "rgba(0,180,220,0.03)", border: "1px solid rgba(0,180,220,0.08)", borderRadius: 3 }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                                        <span style={{ fontFamily: "'Syncopate',sans-serif", fontSize: 11, color: "#c8d8e8" }}>{ex.toUpperCase()}</span>
                                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                            <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#00ffa3", animation: "pulse-dot 1.5s ease-in-out infinite" }} />
                                            <span style={{ fontSize: 8, color: "#00ffa3", letterSpacing: "0.12em" }}>CONNECTED</span>
                                        </div>
                                    </div>
                                    <div style={{ fontSize: 9, color: "#3d6280" }}>API KEY: ****{ex === "Binance" ? "8f2a" : "c91e"}</div>
                                    <div style={{ fontSize: 9, color: "#3d6280", marginTop: 4 }}>MODE: TESTNET · FUTURES/PERP</div>
                                </div>
                            ))}
                            <div style={{ padding: "12px", background: "rgba(0,180,220,0.02)", border: "1px dashed rgba(0,180,220,0.1)", borderRadius: 3, textAlign: "center" }}>
                                <div style={{ fontSize: 9, color: "#2a4a6a", letterSpacing: "0.12em" }}>+ ADD EXCHANGE</div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
