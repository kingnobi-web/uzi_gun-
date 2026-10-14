"""Exness MT5: ten directional 0.1-lot trades, hold five seconds, close, repeat (real orders)."""
import argparse
from decimal import Decimal
import time

MAGIC = 510005


def positions(mt5, symbol):
    result = mt5.positions_get(symbol=symbol)
    if result is None:
        raise RuntimeError(f"Cannot read positions: {mt5.last_error()}")
    return result


def filling_mode(mt5, info):
    if info.filling_mode & 1:
        return mt5.ORDER_FILLING_FOK
    if info.filling_mode & 2:
        return mt5.ORDER_FILLING_IOC
    if info.trade_exemode != mt5.SYMBOL_TRADE_EXECUTION_MARKET:
        return mt5.ORDER_FILLING_RETURN
    raise RuntimeError("Symbol has no supported filling policy")


def send(mt5, symbol, volume, side, filling, deviation, ticket=None):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or tick.ask <= 0 or tick.bid <= 0:
        raise RuntimeError("No usable quote from MT5")
    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
        "volume": volume, "type": side,
        "price": tick.ask if side == mt5.ORDER_TYPE_BUY else tick.bid,
        "deviation": deviation, "magic": MAGIC,
        "comment": "five second bot", "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }
    if ticket is not None:
        request["position"] = ticket
    result = mt5.order_send(request)
    if result is None:
        raise RuntimeError(f"Order result unknown: {mt5.last_error()}; inspect MT5 before restarting")
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"Order incomplete: {result.retcode} {result.comment}; inspect MT5 before restarting")
    return result


def direction(mt5, symbol):
    # Position 1 skips the currently forming M1 candle.
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, 2)
    if bars is None or len(bars) != 2:
        raise RuntimeError("Need two completed M1 candles; load the symbol chart in MT5")
    bars = sorted(bars, key=lambda bar: bar["time"])
    if time.time() - int(bars[-1]["time"]) > 180:
        raise RuntimeError("M1 candles are stale; check market hours and connection")
    change = float(bars[-1]["close"]) - float(bars[0]["close"])
    if change == 0:
        return None
    return mt5.ORDER_TYPE_BUY if change > 0 else mt5.ORDER_TYPE_SELL


def close_batch(mt5, args, filling):
    errors = []
    for p in positions(mt5, args.symbol):
        if p.magic != MAGIC:
            continue
        side = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        try:
            send(mt5, args.symbol, p.volume, side, filling, args.deviation, ticket=p.ticket)
            print(f"CLOSED position {p.ticket}", flush=True)
        except Exception as error:
            errors.append(str(error))
    remaining = [p.ticket for p in positions(mt5, args.symbol) if p.magic == MAGIC]
    if errors or remaining:
        raise RuntimeError(f"Batch cleanup incomplete: {errors}; remaining tickets {remaining}; inspect MT5")


def run(mt5, args):
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if account is None or terminal is None:
        raise RuntimeError("Log into your Exness account in the desktop MT5 terminal")
    if account.login != args.account:
        raise RuntimeError("The logged-in MT5 account does not match --account")
    if account.margin_mode != mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
        raise RuntimeError("Ten separate positions require an MT5 hedging account")
    if not account.trade_allowed or not account.trade_expert or not terminal.trade_allowed:
        raise RuntimeError("Enable algorithmic trading and external Python trading in MT5")
    if not mt5.symbol_select(args.symbol, True):
        raise RuntimeError("Symbol unavailable; use its exact Market Watch name, e.g. XAUUSDm")
    info = mt5.symbol_info(args.symbol)
    lot = Decimal("0.1")
    if info is None or not Decimal(str(info.volume_min)) <= lot <= Decimal(str(info.volume_max)):
        raise RuntimeError("This symbol does not permit 0.1 lot")
    if lot % Decimal(str(info.volume_step)):
        raise RuntimeError("0.1 lot does not match this symbol's volume step")
    filling = filling_mode(mt5, info)
    print(f"Account {account.login} on {account.server}; {args.symbol}; 0.1 lot; contract size {info.trade_contract_size}", flush=True)
    cycle = 0
    while args.cycles == 0 or cycle < args.cycles:
        # A flat symbol also avoids merging with existing trades on netting accounts.
        if positions(mt5, args.symbol):
            raise RuntimeError("Close existing positions on this symbol before starting another cycle")
        pending = mt5.orders_get(symbol=args.symbol)
        if pending is None or pending:
            raise RuntimeError("Cannot establish that this symbol has no pending orders")
        side = direction(mt5, args.symbol)
        if side is None:
            print("M1 closes equal; waiting for direction", flush=True)
            time.sleep(1)
            continue
        label = "BUY" if side == mt5.ORDER_TYPE_BUY else "SELL"
        print(f"Batch {cycle + 1}: {label} ten positions of 0.1 lot (1.0 lot total)", flush=True)
        # Cleanup covers failed/partial opens as well as an interrupted hold.
        try:
            for number in range(10):
                send(mt5, args.symbol, 0.1, side, filling, args.deviation)
                owned = [p for p in positions(mt5, args.symbol) if p.magic == MAGIC]
                if len(owned) != number + 1 or any(p.type != side for p in owned):
                    raise RuntimeError("Cannot verify batch positions; stopping opening orders")
                print(f"OPENED {number + 1}/10 {label}", flush=True)
            time.sleep(5)
        finally:
            close_batch(mt5, args, filling)
        cycle += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", type=int, required=True, help="Expected MT5 account number")
    parser.add_argument("--symbol", default="XAUUSD", help="Exact broker Market Watch symbol")
    parser.add_argument("--terminal", help="Path to the Windows terminal64.exe")
    parser.add_argument("--cycles", type=int, default=0, help="0 repeats indefinitely")
    parser.add_argument("--deviation", type=int, default=20, help="Allowed deviation in broker points")
    args = parser.parse_args()
    if args.cycles < 0 or args.deviation < 0:
        parser.error("cycles and deviation must be nonnegative")
    import MetaTrader5 as mt5
    initialized = mt5.initialize(args.terminal) if args.terminal else mt5.initialize()
    if not initialized:
        raise RuntimeError(f"Cannot connect to desktop MT5: {mt5.last_error()}")
    try:
        run(mt5, args)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped. Check MT5 to confirm the final position is closed.")
    except Exception as error:
        raise SystemExit(f"Stopped: {error}")
