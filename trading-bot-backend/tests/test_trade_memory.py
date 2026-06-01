"""Trade-memory learning loop: FIFO round-trip reconstruction, recall, stats."""

from __future__ import annotations

import json

import pytest

from learning.trade_memory import TradeMemory, TradeMemoryRecord


def _write_fills(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_backfill_fifo_roundtrips(tmp_path):
    fills = tmp_path / "fills.jsonl"
    _write_fills(fills, [
        {"order_id": "1", "symbol": "BTC", "side": "buy", "filled_qty": 1.0, "filled_price": 100.0, "fee": 0.0, "timestamp": "2026-01-01T00:00:00+00:00", "strategy_id": "macd_1"},
        {"order_id": "2", "symbol": "BTC", "side": "sell", "filled_qty": 1.0, "filled_price": 110.0, "fee": 0.0, "timestamp": "2026-01-01T01:00:00+00:00", "strategy_id": "partial_take_profit"},
        {"order_id": "3", "symbol": "ETH", "side": "buy", "filled_qty": 2.0, "filled_price": 50.0, "fee": 0.0, "timestamp": "2026-01-02T00:00:00+00:00", "strategy_id": "momentum_1"},
        {"order_id": "4", "symbol": "ETH", "side": "sell", "filled_qty": 2.0, "filled_price": 45.0, "fee": 0.0, "timestamp": "2026-01-02T02:00:00+00:00", "strategy_id": "trailing_stop"},
    ])
    tm = TradeMemory(memory_path=str(tmp_path / "mem.jsonl"), vault_dir=str(tmp_path / "vault"))
    n = tm.backfill_from_fills(str(fills))
    assert n == 2

    rows = tm.all()
    btc = next(r for r in rows if r["symbol"] == "BTC")
    assert btc["outcome"] == "win"
    assert btc["pnl"] == pytest.approx(10.0)
    assert btc["pnl_pct"] == pytest.approx(10.0)
    assert btc["holding_minutes"] == pytest.approx(60.0)
    assert btc["exit_reason"] == "take_profit"

    eth = next(r for r in rows if r["symbol"] == "ETH")
    assert eth["outcome"] == "loss"
    assert eth["pnl"] == pytest.approx(-10.0)
    assert eth["exit_reason"] == "stop"
    assert eth["lesson"]  # a lesson was generated

    # Obsidian vault populated
    notes = list((tmp_path / "vault" / "trades").glob("*.md"))
    assert len(notes) == 2
    assert (tmp_path / "vault" / "_dashboard.md").exists()
    assert "[[BTC]]" in (tmp_path / "vault" / "trades" / [n.name for n in notes if "BTC" in n.name][0]).read_text()


def test_partial_fifo_matching(tmp_path):
    """One BUY of 3 closed by a SELL of 2 then a SELL of 1 -> two round-trips."""
    fills = tmp_path / "fills.jsonl"
    _write_fills(fills, [
        {"order_id": "1", "symbol": "SOL", "side": "buy", "filled_qty": 3.0, "filled_price": 10.0, "fee": 0.0, "timestamp": "2026-01-01T00:00:00+00:00"},
        {"order_id": "2", "symbol": "SOL", "side": "sell", "filled_qty": 2.0, "filled_price": 12.0, "fee": 0.0, "timestamp": "2026-01-01T00:30:00+00:00"},
        {"order_id": "3", "symbol": "SOL", "side": "sell", "filled_qty": 1.0, "filled_price": 9.0, "fee": 0.0, "timestamp": "2026-01-01T01:00:00+00:00"},
    ])
    tm = TradeMemory(memory_path=str(tmp_path / "mem.jsonl"), vault_dir=str(tmp_path / "vault"))
    assert tm.backfill_from_fills(str(fills)) == 2
    rows = sorted(tm.all(), key=lambda r: r["exit_time"])
    assert rows[0]["qty"] == pytest.approx(2.0) and rows[0]["pnl"] == pytest.approx(4.0)   # (12-10)*2
    assert rows[1]["qty"] == pytest.approx(1.0) and rows[1]["pnl"] == pytest.approx(-1.0)  # (9-10)*1


def test_unmatched_sell_skipped(tmp_path):
    """A SELL with no prior BUY (pre-existing position) is skipped."""
    fills = tmp_path / "fills.jsonl"
    _write_fills(fills, [
        {"order_id": "1", "symbol": "XRP", "side": "sell", "filled_qty": 5.0, "filled_price": 0.5, "fee": 0.0, "timestamp": "2026-01-01T00:00:00+00:00"},
    ])
    tm = TradeMemory(memory_path=str(tmp_path / "mem.jsonl"), vault_dir=str(tmp_path / "vault"))
    assert tm.backfill_from_fills(str(fills)) == 0


def test_recall_stats_and_worst_setups(tmp_path):
    tm = TradeMemory(memory_path=str(tmp_path / "mem.jsonl"), vault_dir=str(tmp_path / "vault"))
    base = dict(entry_time="2026-01-01T00:00:00+00:00", exit_time="2026-01-01T01:00:00+00:00",
                entry_price=100.0, exit_price=100.0, qty=1.0, holding_minutes=60.0, exit_reason="stop")
    tm.record(TradeMemoryRecord(id="a", symbol="SOL", strategy="mean_reversion", pnl=-5, pnl_pct=-5, outcome="loss", tags=["SOL"], **base))
    tm.record(TradeMemoryRecord(id="b", symbol="SOL", strategy="mean_reversion", pnl=-3, pnl_pct=-3, outcome="loss", tags=["SOL"], **base))
    tm.record(TradeMemoryRecord(id="c", symbol="BTC", strategy="macd", pnl=8, pnl_pct=8, outcome="win", tags=["BTC"], **base))

    assert len(tm.recall(symbol="SOL")) == 2
    assert len(tm.recall(strategy="macd")) == 1
    s = tm.stats()
    assert s["overall"]["trades"] == 3
    assert s["by_setup"]["mean_reversion/SOL"]["win_rate"] == 0.0
    worst = tm.worst_setups(min_trades=2)
    assert worst[0][0] == "mean_reversion/SOL"  # the bleeding setup surfaces first
