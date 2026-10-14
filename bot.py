"""Repeated spot buys followed by a sell five seconds after the buy fills."""

import argparse
import os
import time


def wait_for_fill(exchange, order, symbol):
    deadline = time.monotonic() + 60
    while order.get('status') != 'closed':
        if order.get('status') in ('canceled', 'expired', 'rejected'):
            raise RuntimeError(f'Order did not complete: {order["id"]}')
        if time.monotonic() >= deadline:
            raise RuntimeError(f'Order {order["id"]} still unresolved; inspect it on the exchange.')
        time.sleep(0.5)
        order = exchange.fetch_order(order['id'], symbol)
    return order


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exchange', default='binance')
    parser.add_argument('--symbol', default='BTC/USDT')
    parser.add_argument('--amount', type=float, default=0.001, help='Base asset quantity per buy')
    parser.add_argument('--cycles', type=int, default=0, help='0 repeats indefinitely')
    parser.add_argument('--live', action='store_true', help='Place real spot market orders')
    args = parser.parse_args()
    if args.amount <= 0 or args.cycles < 0:
        parser.error('amount must be positive and cycles must be nonnegative')

    exchange = None
    if args.live:
        import ccxt

        exchange_class = getattr(ccxt, args.exchange)
        exchange = exchange_class({
            'apiKey': os.environ['EXCHANGE_API_KEY'],
            'secret': os.environ['EXCHANGE_API_SECRET'],
            'password': os.environ.get('EXCHANGE_API_PASSWORD'),
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        exchange.load_markets()
        market = exchange.market(args.symbol)
        if not market.get('spot'):
            raise RuntimeError('Choose a spot trading pair.')
        if not exchange.has.get('fetchOrder'):
            raise RuntimeError('This exchange needs a custom order-status implementation.')

    cycle = 0
    while not args.cycles or cycle < args.cycles:
        cycle += 1
        quantity = args.amount
        if exchange:
            order = wait_for_fill(exchange, exchange.create_order(
                args.symbol, 'market', 'buy', quantity
            ), args.symbol)
            quantity = float(order['filled'])
            fees = order.get('fees') or ([order['fee']] if order.get('fee') else [])
            quantity -= sum(float(fee.get('cost') or 0) for fee in fees
                            if fee.get('currency') == market['base'])
            quantity = float(exchange.amount_to_precision(args.symbol, quantity))
            if quantity <= 0:
                raise RuntimeError('No sellable quantity after fees and rounding.')
        print(f'{cycle}: BUY {quantity} {args.symbol}' + (' [paper]' if not exchange else ''), flush=True)
        time.sleep(5)
        if exchange:
            wait_for_fill(exchange, exchange.create_order(
                args.symbol, 'market', 'sell', quantity
            ), args.symbol)
        print(f'{cycle}: SELL {quantity} {args.symbol}' + (' [paper]' if not exchange else ''), flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. Any open position remains on the exchange.')
