# Exness MT5 five-second bot

Uses the last two **completed M1 candles**: a higher close means BUY, a lower
close means SELL, equal closes mean wait. It checks the signal before every batch.
This is a simple momentum rule, not a forecast.

Opens **ten separate positions of 0.01 lot each (0.10 lot total)** in the selected
direction, waits five seconds after the tenth fill response, then closes the batch
and repeats. Orders are submitted sequentially in quick succession, not atomically;
earlier positions remain open longer than five seconds and closes take time too.
An MT5 **hedging account** is required; netting accounts are rejected.

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
Ctrl+C during the hold attempts to close the position; a crash, lost connection,
or rejected close can leave it open. Inspect MT5 before restarting after errors.

## Validation

Order logic can be tested with `python -m unittest discover -s tests -v` without
MT5 installed. These are simulated API tests; real broker execution must be
verified on the Windows machine. Linux cloud workspaces cannot use the native
Windows MT5 Python connection.
