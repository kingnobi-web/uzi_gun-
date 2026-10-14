"""Exness MT5: buy 0.1 lot, hold five seconds, close, repeat (real orders)."""
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


def run(mt5, args):
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if account is None or terminal is None:
        raise RuntimeError("Log into your Exness account in the desktop MT5 terminal")
    if account.login != args.account:
        raise RuntimeError("The logged-in MT5 account does not match --account")
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
        bought = send(mt5, args.symbol, 0.1, mt5.ORDER_TYPE_BUY, filling, args.deviation)
        started = time.monotonic()
        opened = positions(mt5, args.symbol)
        owned = [p for p in opened if p.magic == MAGIC and p.type == mt5.ORDER_TYPE_BUY]
        if len(opened) != 1 or len(owned) != 1:
            raise RuntimeError(f"Cannot identify bought position (deal {bought.deal}); inspect MT5")
        position = owned[0]
        print(f"BUY 0.1 lot; position {position.ticket}", flush=True)
        try:
            time.sleep(max(0, 5 - (time.monotonic() - started)))
        finally:
            # Ctrl+C during the hold still attempts to close this exact position.
            current = positions(mt5, args.symbol)
            matches = [p for p in current if p.ticket == position.ticket]
            if matches:
                p = matches[0]
                send(mt5, args.symbol, p.volume, mt5.ORDER_TYPE_SELL, filling,
                     args.deviation, ticket=p.ticket)
            if positions(mt5, args.symbol):
                raise RuntimeError("Position remains open after close; inspect MT5")
            print(f"CLOSED position {position.ticket}", flush=True)
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
