"""Application entry point for the paper trading bot backend."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Main entry point."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Paper Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["api", "bot", "cli", "live-demo"],
        default="api",
        help="Run mode: api (FastAPI server), bot (CLI bot), cli (CLI commands), live-demo (mock broker demo)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="API host")
    parser.add_argument("--port", type=int, default=8000, help="API port")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--broker", default="mock", help="Broker for live-demo mode (mock, binance, alpaca, etc.)")

    args = parser.parse_args()

    if args.mode == "api":
        import uvicorn
        from api.main import app

        print(f"Starting API server on {args.host}:{args.port}")
        print(f"Swagger UI: http://{args.host}:{args.port}/docs")
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.mode == "bot":
        from cli.main import app as cli_app

        # Run the bot command
        import typer
        typer.run(lambda: cli_app())

    elif args.mode == "cli":
        from cli.main import app as cli_app
        cli_app()

    elif args.mode == "live-demo":
        from bot.config import BotConfig, OrderSide
        from bot.engine import LiveTradingEngine
        from bot.orders import Order
        from brokers.registry import get_broker

        print("=== Live Trading Demo (Mock Broker) ===")
        config = BotConfig()
        broker = get_broker(args.broker)

        if args.broker == "mock":
            broker.connect("demo_key", "demo_secret")
        else:
            print(f"WARNING: {args.broker} requires real API keys.")
            print("Use POST /settings/api-keys to configure them.")
            broker.connect("", "")

        engine = LiveTradingEngine(config, broker)
        engine.start()
        print(f"Engine started. Broker: {broker.name} | Connected: {broker.is_connected()}")
        print(f"Initial balance: {broker.get_balance()}")

        # Execute sample orders
        orders = [
            Order.market("BTC-USD", OrderSide.BUY, 0.1),
            Order.market("ETH-USD", OrderSide.BUY, 1.0),
            Order.limit("BTC-USD", OrderSide.SELL, 0.05, price=70000.0),
        ]
        for order in orders:
            try:
                fill = engine.execute_order(order)
                print(f"  {order.side.value.upper()} {order.symbol}: {fill.filled_qty} @ {fill.filled_price:.2f}")
            except Exception as exc:
                print(f"  {order.side.value.upper()} {order.symbol}: REJECTED — {exc}")

        print(f"\nLive status: {engine.get_live_status()}")
        print(f"Final balance: {broker.get_balance()}")
        print(f"Positions: {broker.get_positions()}")
        print("=== Demo Complete ===")


if __name__ == "__main__":
    main()
