# Exness MT5 five-second bot

Places real market buys of **0.1 lot**, waits five seconds after the execution
response, closes that exact position, and repeats. Actual holding time includes
network and broker latency. No paper mode.

## Run on Windows

1. Install 64-bit Python and the Exness MetaTrader 5 desktop terminal on the same Windows PC or VPS.
2. Log into your intended Exness account in MT5. Enable algorithmic trading and permit trading through the external Python API in MT5 settings.
3. In Market Watch, find the exact gold symbol. It may be `XAUUSD`, `XAUUSDm`, or another account-specific name.
4. Open a terminal in this folder and install:

```powershell
py -m pip install -r requirements.txt
```

Run one real cycle, replacing the account number and symbol with yours:

```powershell
py bot.py --account 12345678 --symbol XAUUSDm --cycles 1
```

For continuous cycles:

```powershell
py bot.py --account 12345678 --symbol XAUUSDm
```

If multiple terminals are installed, select yours with
`--terminal "C:\Program Files\MetaTrader 5\terminal64.exe"`.
Credentials stay in the logged-in terminal; no password belongs in this code.
The account argument verifies the connected account, rather than logging in.

0.1 means broker lots, not 0.1 ounce. The bot displays the broker's contract size.
It requires this symbol to have no existing positions or pending orders before
each cycle. Avoid concurrent trading on that symbol. Rejected, partial, or
ambiguous orders stop the bot without automatically repeating the order.
Ctrl+C during the hold attempts to close the position; a crash, lost connection,
or rejected close can leave it open. Inspect MT5 before restarting after errors.

## Validation

Order logic can be tested with `python -m unittest discover -s tests -v` without
MT5 installed. These are simulated API tests; real broker execution must be
verified on the Windows machine. Linux cloud workspaces cannot use the native
Windows MT5 Python connection.
