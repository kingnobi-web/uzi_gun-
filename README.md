# Exness MT5 five-second bot

Uses the last two **completed M1 candles**: a higher close means BUY, a lower
close means SELL, equal closes mean wait. It checks the signal before every batch.
This is a simple momentum rule, not a forecast.

Opens **ten separate positions of 0.01 lot each (0.10 lot total)** in the selected
direction, then monitors their combined floating P/L every 0.2 seconds.
Default exit rules (first one reached closes the whole batch):

- Profit target: +1.00 plus a 0.50 cost buffer, so +1.50 floating P/L.
- Loss limit: -5.00 floating P/L.
- Timeout: 60 seconds after all ten orders finish opening, even if losing.

Amounts are in account currency (USD on a USD account), for the whole batch.
Floating P/L includes swap and bid/ask spread but excludes commissions. The buffer
is an allowance, not a measurement of fees or a guarantee of realized profit.
Orders and closes execute sequentially; execution delay and slippage can move the
final P/L beyond any threshold. These are Python-managed exits, not broker-held
stop-loss or take-profit orders: they cannot run while the bot or connection is down.
This change does not establish a profitable strategy or guarantee more winning trades.
An MT5 **hedging account** is required; netting accounts are rejected.

Customize exits with `--profit-target 1 --cost-buffer 0.5 --loss-limit 5 --max-hold 60`.

## Run on Windows

1. Install 64-bit Python and the Exness MetaTrader 5 desktop terminal on the same Windows PC or VPS.
2. Log into your intended Exness account in MT5. Enable algorithmic trading and permit trading through the external Python API in MT5 settings.
3. In Market Watch, find the exact gold symbol. It may be `XAUUSD`, `XAUUSDm`, or another account-specific name.
4. Open a terminal in this folder and install:

```powershell
py -m pip install -r requirements.txt
```

Run one real ten-trade batch, replacing the account number and symbol with yours:

```powershell
py bot.py --account 12345678 --symbol XAUUSDm --cycles 1
```

For continuous ten-trade batches:

```powershell
py bot.py --account 12345678 --symbol XAUUSDm
```

If multiple terminals are installed, select yours with
`--terminal "C:\Program Files\MetaTrader 5\terminal64.exe"`.
Credentials stay in the logged-in terminal; no password belongs in this code.
The account argument verifies the connected account, rather than logging in.

0.01 means broker lots, not 0.01 ounce. The bot displays the broker's contract size.
It requires this symbol to have no existing positions or pending orders before
each cycle. Avoid concurrent trading on that symbol. Rejected, partial, or
ambiguous orders stop further entries and attempt to close all visible bot positions.
A rejected close does not prevent attempts to close the other positions.
Use only one instance of this bot per account and symbol.
Ctrl+C during monitoring attempts to close the position; a crash, lost connection,
or rejected close can leave it open. Inspect MT5 before restarting after errors.

## Validation

Order logic can be tested with `python -m unittest discover -s tests -v` without
MT5 installed. These are simulated API tests; real broker execution must be
verified on the Windows machine. Linux cloud workspaces cannot use the native
Windows MT5 Python connection.
