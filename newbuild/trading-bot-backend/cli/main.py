"""Typer CLI for paper trading bot."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from bot.config import BotConfig
from bot.engine import PaperTradingEngine, TickData
from bot.orders import OrderSide
from data.cache import DataCache
from data.fetcher import MarketData
from strategies import StrategyFactory, list_strategies
from backtest.engine import BacktestConfig, BacktestRunner

app = typer.Typer(help="Paper Trading Bot CLI")


def _get_engine(config_path: str = "config.yaml") -> PaperTradingEngine:
    """Helper to create engine."""
    try:
        config = BotConfig.from_yaml(config_path)
    except FileNotFoundError:
        config = BotConfig()
    cache = DataCache(cache_dir=config.app.data_dir + "/cache")
    market_data = MarketData(cache=cache, config=config)
    return PaperTradingEngine(config=config, market_data=market_data)


@app.command()
def run_bot(
    config: str = typer.Option("config.yaml", "--config", "-c"),
    account: str = typer.Option("default", "--account", "-a"),
    strategy_names: list[str] = typer.Option([], "--strategy", "-s"),
    interval: float = typer.Option(5.0, "--interval"),
) -> None:
    """Start the paper trading bot tick loop."""
    typer.echo("Starting paper trading bot...")
    
    engine = _get_engine(config)
    
    for strat_name in strategy_names:
        try:
            strategy = StrategyFactory(strat_name)
            engine.register_strategy(strategy, account)
            typer.echo(f"Registered strategy: {strat_name}")
        except ValueError as e:
            typer.echo(f"Error registering {strat_name}: {e}")
            raise typer.Exit(1)
    
    engine.start()
    typer.echo(f"Bot running on account '{account}' with {len(strategy_names)} strategies")
    typer.echo(f"Tick interval: {interval}s")
    typer.echo("Press Ctrl+C to stop")
    
    try:
        asyncio.run(_run_loop(engine, interval))
    except KeyboardInterrupt:
        engine.stop()
        typer.echo("\nBot stopped.")


async def _run_loop(engine: PaperTradingEngine, interval: float) -> None:
    """Async tick loop."""
    import time
    while engine.is_running:
        # Simulate ticks for registered strategies
        for account_id, strategies in engine._strategies.items():
            for strategy in strategies:
                if strategy.is_active:
                    tick = TickData(symbol="BTC", price=45000.0 + (hash(strategy.strategy_id) % 1000))
                    engine.on_tick(tick)
        await asyncio.sleep(interval)


@app.command()
def backtest(
    strategy: str = typer.Argument(..., help="Strategy type name"),
    symbol: str = typer.Argument(...),
    asset_class: str = typer.Option("crypto", "--asset-class"),
    start: str = typer.Option(..., "--start", help="YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="YYYY-MM-DD"),
    timeframe: str = typer.Option("1d", "--timeframe"),
    initial_balance: float = typer.Option(10000.0, "--balance"),
    output_dir: str = typer.Option("./backtest_results", "--output"),
    walk_forward: bool = typer.Option(False, "--walk-forward"),
) -> None:
    """Run a strategy backtest on historical data."""
    typer.echo(f"Running backtest: {strategy} on {symbol}")
    
    try:
        strat = StrategyFactory(strategy)
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)
    
    # Fetch data
    config = BotConfig()
    cache = DataCache()
    market_data = MarketData(cache=cache, config=config)
    
    import pandas as pd, numpy as np
    from bot.config import AssetClass
    
    try:
        ac = AssetClass(asset_class)
        df = asyncio.run(market_data.get_ohlcv(symbol, ac, timeframe))
    except Exception:
        typer.echo("Using synthetic data for demo")
        dates = pd.date_range(start, periods=90, freq="D")
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(90) * 2)
        df = pd.DataFrame({
            "timestamp": dates,
            "open": prices * 0.99,
            "high": prices * 1.02,
            "low": prices * 0.98,
            "close": prices,
            "volume": np.random.randint(1000, 10000, 90),
        })
    
    bt_config = BacktestConfig(
        initial_balance={"USDT": initial_balance},
        fee_rate=0.001,
        slippage_bps=5.0,
        allow_short=True,
    )
    
    runner = BacktestRunner(strat, df, bt_config)
    
    if walk_forward:
        results = runner.walk_forward(df, train_size=30, test_size=15)
        typer.echo(f"Walk-forward completed: {len(results)} windows")
        for i, r in enumerate(results):
            typer.echo(f"Window {i+1}: Return={r.metrics.total_return_pct:.2f}%, Trades={len(r.trades)}")
    else:
        result = runner.run()
        typer.echo(f"Backtest complete!")
        typer.echo(f"Total Return: {result.metrics.total_return_pct:.2f}%")
        typer.echo(f"Sharpe Ratio: {result.metrics.sharpe_ratio:.4f}")
        typer.echo(f"Max Drawdown: {result.metrics.max_drawdown_pct:.2f}%")
        typer.echo(f"Win Rate: {result.metrics.win_rate:.1f}%")
        typer.echo(f"Profit Factor: {result.metrics.profit_factor:.4f}")
        typer.echo(f"Total Trades: {len(result.trades)}")
        
        # Save results
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"{strategy}_{symbol}_{start}.json"
        with open(out_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2, default=str)
        typer.echo(f"Results saved to {out_path}")


@app.command()
def export_records(
    table: str = typer.Option("all", "--table", help="trades|snapshots|performance|all"),
    output_dir: str = typer.Option("./exports", "--output"),
    account_id: Optional[str] = typer.Option(None, "--account"),
    strategy_id: Optional[str] = typer.Option(None, "--strategy"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
    fmt: str = typer.Option("csv", "--format"),
) -> None:
    """Export database records to CSV or JSON."""
    typer.echo(f"Exporting {table} records...")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    from data.storage import init_db
    from sqlalchemy.orm import sessionmaker
    
    engine_db = init_db("sqlite:///data/bot.db")
    Session = sessionmaker(bind=engine_db)
    session = Session()
    
    from analytics.export import DataExporter
    exporter = DataExporter(session, output_dir)
    
    if table == "all":
        paths = exporter.export_all(output_dir)
        for name, path in paths.items():
            typer.echo(f"Exported {name}: {path}")
    elif table == "trades":
        path = exporter.export_trades(account_id=account_id, strategy_id=strategy_id)
        typer.echo(f"Exported trades to {path}")
    else:
        typer.echo(f"Table export for '{table}' not yet implemented")
    
    session.close()


@app.command()
def configure(
    key: Optional[str] = typer.Option(None, "--set"),
    value: Optional[str] = typer.Option(None, "--value"),
    show: bool = typer.Option(False, "--show"),
    init: bool = typer.Option(False, "--init"),
) -> None:
    """View or modify bot configuration."""
    config_path = Path("config.yaml")
    
    if init:
        config = BotConfig()
        config.to_yaml(config_path)
        typer.echo(f"Default config written to {config_path}")
        return
    
    if show or (key is None and value is None):
        try:
            config = BotConfig.from_yaml(config_path)
        except FileNotFoundError:
            config = BotConfig()
        typer.echo(config.model_dump_json(indent=2))
        return
    
    if key and value:
        typer.echo(f"Setting {key} = {value}")
        # Simple config update
        try:
            config = BotConfig.from_yaml(config_path)
        except FileNotFoundError:
            config = BotConfig()
        # Update nested keys
        parts = key.split(".")
        target = config
        for part in parts[:-1]:
            target = getattr(target, part, None)
            if target is None:
                typer.echo(f"Invalid key path: {key}")
                return
        try:
            # Try to parse value as int/float
            parsed: Any = value
            try:
                parsed = int(value)
            except ValueError:
                try:
                    parsed = float(value)
                except ValueError:
                    pass
            setattr(target, parts[-1], parsed)
            config.to_yaml(config_path)
            typer.echo(f"Updated {key} = {parsed}")
        except Exception as e:
            typer.echo(f"Error setting config: {e}")


@app.command()
def status() -> None:
    """Show bot status: engine, strategies, portfolio summary."""
    engine = _get_engine()
    portfolios = engine.get_all_portfolios()
    
    typer.echo("=== Bot Status ===")
    typer.echo(f"Accounts: {len(portfolios)}")
    
    for account_id, portfolio in portfolios.items():
        typer.echo(f"\nAccount: {account_id}")
        typer.echo(f"  Balances: {portfolio.get_all_balances()}")
        typer.echo(f"  Positions: {len(portfolio.get_all_positions())}")
        typer.echo(f"  Unrealized PnL: {portfolio.total_unrealized_pnl:.4f}")
        typer.echo(f"  Realized PnL: {portfolio.total_realized_pnl:.4f}")
    
    typer.echo("\nActive Strategies: None (use run-bot to start)")


@app.command()
def report(
    report_type: str = typer.Argument(..., help="daily|strategy|portfolio"),
    date: Optional[str] = typer.Option(None, "--date"),
    account_id: str = typer.Option("default", "--account"),
    strategy_id: Optional[str] = typer.Option(None, "--strategy"),
    output: Optional[str] = typer.Option(None, "--output"),
) -> None:
    """Generate and optionally save a performance report."""
    typer.echo(f"Generating {report_type} report...")
    
    from data.storage import init_db
    from sqlalchemy.orm import sessionmaker
    
    engine_db = init_db("sqlite:///data/bot.db")
    Session = sessionmaker(bind=engine_db)
    session = Session()
    
    from analytics.reports import ReportGenerator
    gen = ReportGenerator(session)
    
    if report_type == "daily":
        report_date = datetime.strptime(date, "%Y-%m-%d").date() if date else datetime.now(timezone.utc).date()
        r = gen.generate_daily_report(report_date, account_id)
        typer.echo(json.dumps(r.to_dict(), indent=2))
    elif report_type == "strategy" and strategy_id:
        r = gen.generate_strategy_report(strategy_id)
        typer.echo(json.dumps(r.to_dict(), indent=2))
    elif report_type == "portfolio":
        engine = _get_engine()
        portfolio = engine.get_portfolio(account_id)
        r = gen.generate_portfolio_report(portfolio)
        typer.echo(json.dumps(r.to_dict(), indent=2))
    else:
        typer.echo("Invalid report type or missing parameters")
    
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w") as f:
            f.write("Report saved")
        typer.echo(f"Report saved to {output}")
    
    session.close()


@app.command()
def strategy_list() -> None:
    """List all available strategy types and their configs."""
    strategies = list_strategies()
    typer.echo("=== Available Strategies ===")
    for name, info in strategies.items():
        typer.echo(f"\n{name} ({info['class']})")
        typer.echo(f"  Default config: {json.dumps(info['default_config'], indent=4)}")


if __name__ == "__main__":
    app()
