"""Export MT5 M1 bars and bid/ask ticks; never sends trading orders."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--symbol', default='XAUUSDm')
    p.add_argument('--days', type=int, default=7)
    p.add_argument('--output', default='market-data')
    p.add_argument('--terminal')
    a = p.parse_args()
    if a.days < 2:
        p.error('Export at least two days')
    import MetaTrader5 as mt
    if not (mt.initialize(a.terminal) if a.terminal else mt.initialize()):
        raise SystemExit(f'MT5 connection failed: {mt.last_error()}')
    try:
        account = mt.account_info()
        if account is None or account.currency != 'USD':
            raise RuntimeError('This XAUUSD research model requires a USD account')
        if not mt.symbol_select(a.symbol, True):
            raise RuntimeError('Unknown symbol')
        info = mt.symbol_info(a.symbol)
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = end - timedelta(days=a.days)
        out = Path(a.output)
        out.mkdir(parents=True, exist_ok=False)
        bars = mt.copy_rates_range(a.symbol, mt.TIMEFRAME_M1, start, end)
        if bars is None or len(bars) < 200:
            raise RuntimeError('Not enough M1 history; open M1 chart, load history, then retry with a new output folder')
        with (out / 'bars.csv').open('w', newline='') as f:
            w = csv.writer(f); w.writerow(['time', 'open', 'high', 'low', 'close'])
            for b in bars:
                if int(b['time']) < int(end.timestamp()):
                    w.writerow([b[k] for k in ['time', 'open', 'high', 'low', 'close']])
        count = 0
        first_tick = last_tick = None
        cursor = start
        with (out / 'ticks.csv').open('w', newline='') as f:
            w = csv.writer(f); w.writerow(['time_msc', 'bid', 'ask'])
            while cursor < end:
                boundary = min(cursor + timedelta(hours=6), end)
                ticks = mt.copy_ticks_range(a.symbol, cursor, boundary, mt.COPY_TICKS_ALL)
                if ticks is None:
                    raise RuntimeError(f'Tick download failed: {mt.last_error()}')
                lo, hi = int(cursor.timestamp()*1000), int(boundary.timestamp()*1000)
                for t in ticks:
                    if lo <= int(t['time_msc']) < hi and 0 < t['bid'] <= t['ask']:
                        tick_time = int(t['time_msc'])
                        if first_tick is None:
                            first_tick = tick_time
                        last_tick = tick_time
                        w.writerow([tick_time, t['bid'], t['ask']]); count += 1
                print(f'{boundary.isoformat()}: {count} ticks exported', flush=True)
                cursor = boundary
        if not count:
            raise RuntimeError('No tick history available')
        actual_start = datetime.fromtimestamp(first_tick / 1000, timezone.utc)
        actual_end = datetime.fromtimestamp(last_tick / 1000, timezone.utc)
        coverage_warning = actual_start - start > timedelta(days=1)
        (out / 'metadata.json').write_text(json.dumps(dict(
            symbol=a.symbol, currency='USD', contract_size=info.trade_contract_size,
            start_utc=start.isoformat(), end_utc=end.isoformat(), ticks=count,
            actual_tick_start_utc=actual_start.isoformat(),
            actual_tick_end_utc=actual_end.isoformat(),
            requested_start_missing_over_one_day=coverage_warning,
            model='linear XAUUSD spot CFD in USD'), indent=2))
        print(f'ACTUAL tick coverage UTC: {actual_start.isoformat()} to {actual_end.isoformat()}')
        if coverage_warning:
            print('WARNING: More than one day of the requested starting period was not returned. This can include closed sessions or unavailable history; do not assume the requested number of days was exported.')
        print(f'Export complete: {out}. Zip this folder and share it for analysis.')
    finally:
        mt.shutdown()


if __name__ == '__main__':
    main()
