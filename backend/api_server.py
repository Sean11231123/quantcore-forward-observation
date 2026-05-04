from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine import ENGINE_CONFIG, TradingEngine


ControlAction = Literal["start", "stop", "halt"]


class ControlRequest(BaseModel):
    action: ControlAction


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


STATE = {
    "engine_status": "stopped",
    "halt_reason": "",
    "portfolio": {
        "capital": 10000.0,
        "peak": 10320.0,
    },
    "pnl": {
        "daily": 84.25,
        "total": 320.0,
    },
    "risk": {
        "drawdown": 0.031,
        "is_halted": False,
        "halt_reason": "",
        "max_drawdown": 0.10,
        "daily_loss_limit": 0.03,
    },
    "positions": [
        {
            "symbol": "ETH/USDT",
            "side": "long",
            "quantity": 0.42,
            "entry": 2298.4,
            "mark": 2312.7,
            "pnl": 6.01,
            "value_usdt": 971.33,
        },
        {
            "symbol": "SOL/USDT",
            "side": "long",
            "quantity": 3.1,
            "entry": 143.2,
            "mark": 145.8,
            "pnl": 8.06,
            "value_usdt": 451.98,
        },
    ],
    "trades_recent": [
        {
            "timestamp": "2026-05-02T07:12:30Z",
            "symbol": "ETH/USDT",
            "strategy": "v12_trend",
            "side": "buy",
            "price": 2298.4,
            "quantity": 0.42,
            "status": "filled",
            "exchange": "binance",
            "confidence": 0.78,
            "fee_usdt": 0.48,
        },
        {
            "timestamp": "2026-05-02T07:20:05Z",
            "symbol": "SOL/USDT",
            "strategy": "v12_trend",
            "side": "buy",
            "price": 143.2,
            "quantity": 3.1,
            "status": "filled",
            "exchange": "binance",
            "confidence": 0.74,
            "fee_usdt": 0.22,
        },
    ],
    "market": {
        "regimes": {
            "BTC/USDT": {
                "regime": "trending_bull",
                "confidence": 0.72,
                "strategies": ["v12_trend", "trend_following"],
                "btc_adx": 31.4,
                "btc_adx_1h": 26.8,
                "btc_re": 0.34,
                "updated_at": "2026-05-02T07:25:00Z",
            },
            "ETH/USDT": {
                "regime": "breakout",
                "confidence": 0.66,
                "strategies": ["v12_trend"],
                "updated_at": "2026-05-02T07:25:00Z",
            },
        }
    },
    "metrics": {
        "win_rate": 0.64,
        "sharpe": 1.38,
        "signal_quality": 0.75,
    },
    "strategy": {
        "allocation": {
            "v12_trend": 0.70,
            "trend_following": 0.20,
            "cash": 0.10,
        }
    },
}

ENGINE = TradingEngine(ENGINE_CONFIG)
ENGINE_TASK: asyncio.Task | None = None

app = FastAPI(title="QuantCore V12 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _ensure_engine_running() -> None:
    global ENGINE_TASK
    if ENGINE_TASK is not None and not ENGINE_TASK.done():
        await ENGINE.start()
        return

    await ENGINE.prepare_start()
    ENGINE_TASK = asyncio.create_task(ENGINE.run())


@app.on_event("startup")
async def startup_engine() -> None:
    await _ensure_engine_running()


@app.on_event("shutdown")
async def shutdown_engine() -> None:
    global ENGINE_TASK
    await ENGINE.stop()
    if ENGINE_TASK is not None:
        ENGINE_TASK.cancel()
        try:
            await ENGINE_TASK
        except asyncio.CancelledError:
            pass
        ENGINE_TASK = None


def _engine_status_snapshot() -> dict:
    return ENGINE.get_status()

def _live_snapshot() -> dict:
    state = deepcopy(STATE)
    state["timestamp"] = _now_iso()

    engine_snapshot = _engine_status_snapshot()
    state["engine"] = {
        "status": "running" if engine_snapshot.get("running") else "stopped",
        "halted": bool(engine_snapshot.get("halted")),
        "halt_reason": engine_snapshot.get("halt_reason", ""),
        "updated_at": engine_snapshot.get("updated_at"),
    }
    state["portfolio"]["capital"] = engine_snapshot.get("capital_usdt", state["portfolio"]["capital"])
    state["portfolio"]["peak"] = engine_snapshot.get("peak_capital", state["portfolio"]["peak"])
    state["pnl"]["daily"] = engine_snapshot.get("daily_pnl", state["pnl"]["daily"])
    state["pnl"]["total"] = engine_snapshot.get("total_pnl", state["pnl"]["total"])
    state["risk"]["drawdown"] = engine_snapshot.get("drawdown_pct", state["risk"]["drawdown"])
    state["risk"]["is_halted"] = bool(engine_snapshot.get("halted"))
    state["risk"]["halt_reason"] = engine_snapshot.get("halt_reason", "")
    state["positions"] = engine_snapshot.get("positions", state["positions"])
    state["market"]["regimes"] = engine_snapshot.get("regimes", state["market"]["regimes"])
    state["trades_recent"] = engine_snapshot.get("recent_trades", state["trades_recent"])
    state["metrics"].update(engine_snapshot.get("metrics", {}))
    state["strategy"]["allocation"] = engine_snapshot.get(
        "strategy_allocation",
        state["strategy"]["allocation"],
    )

    recent = state.pop("trades_recent")
    state.pop("engine_status", None)
    state.pop("halt_reason", None)
    state["trades"] = {
        "today": engine_snapshot.get("trade_count_today", len(recent)),
        "recent": recent[-100:],
    }
    state.update(_mock_state_compat(state))
    return state


def _mock_state_compat(state: dict) -> dict:
    """Top-level shape used by dashboard/quant_dashboard.jsx MOCK_STATE."""
    positions = state.get("positions", [])
    trades = state.get("trades", {})
    metrics = state.get("metrics", {})
    return {
        "capital": state.get("portfolio", {}).get("capital", 0),
        "peak": state.get("portfolio", {}).get("peak", 0),
        "dailyPnl": state.get("pnl", {}).get("daily", 0),
        "totalPnl": state.get("pnl", {}).get("total", 0),
        "drawdown": state.get("risk", {}).get("drawdown", 0),
        "openPositions": len(positions),
        "tradesToday": trades.get("today", 0),
        "winRate": metrics.get("win_rate", 0),
        "sharpe": metrics.get("sharpe", 0),
        "regimes": state.get("market", {}).get("regimes", {}),
        "recentTrades": trades.get("recent", []),
    }


@app.get("/api/v12/live")
def get_live() -> dict:
    return _live_snapshot()


@app.get("/api/v12/trades")
def get_trades() -> list[dict]:
    return _live_snapshot()["trades"]["recent"][-100:]


@app.get("/api/v12/positions")
def get_positions() -> list[dict]:
    return _live_snapshot()["positions"]


@app.get("/api/v12/regime")
def get_regime() -> dict:
    regimes = _live_snapshot()["market"]["regimes"]
    return regimes.get("BTC/USDT") or regimes.get("BTC_USDT") or {}


@app.post("/api/v12/control")
async def control(req: ControlRequest) -> dict:
    if req.action == "start":
        await _ensure_engine_running()
    elif req.action == "stop":
        await ENGINE.stop()
    elif req.action == "halt":
        await ENGINE.halt()
    else:
        raise HTTPException(status_code=400, detail="Unsupported action")

    return {"ok": True, "action": req.action, "engine": _live_snapshot()["engine"]}
