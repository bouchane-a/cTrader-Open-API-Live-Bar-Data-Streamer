# cTrader Open API – Live Bar Data Streamer

## Overview

This project is a fully asynchronous Python client that connects to the cTrader (Spotware) Open API over Protobuf/TCP,
authenticates with your trading account, and streams live OHLC (Open, High, Low, Close) “bar” data.

It is meant as a lightweight starting point for traders and quants who need fast, programmatic access to minute-by-minute
market bars without running the full cTrader desktop terminal.

### Features

- ✅ Uses the official cTrader Open API (Protobuf/TCP) for low-latency data
- ✅ Built on Twisted for non-blocking networking and coroutine support
- ✅ Handles both application and account authentication flows out of the box
- ✅ Subscribes to spot prices and live trend-bars for any list of symbol IDs
- ✅ Detects bar-rollover in real time and prints freshly closed OHLC values
- ✅ Designed for easy extension – drop in your own analytics or order logic

### Requirements

    pip install ctrader-open-api service-identity twisted protobuf google

### Getting Started

    python ctrader_open_api.py

    # 1. Put your credentials JSON somewhere safe (e.g. config/CREDENTIALS.json).
    # 2. Adjust CREDENTIALS, SYMBOL_IDS, SYMBOL_NAMES, TIMEFRAME as described below.

The script will:

1. Open a TCP connection to the demo or live cTrader host you choose.
2. Perform application → account authentication using your client ID, secret, and access token.
3. Subscribe to spot price updates and TIMEFRAME trend-bars for every symbol in SYMBOL_IDS.
4. Continuously stream updates; on each closed bar it prints:
       SYMBOL,  YYYY-MM-DD HH:MM:SS,  open,  high,  low,  close
5. Keep the connection alive so you can bolt on alerts or trading logic.

---

How to Use
----------

This script is intended to load symbols’ OHLC data via cTrader’s Open API.
Update four variables in `ctrader_open_api.py` before running:

    - CREDENTIALS: JSON block with auth details (see below)
    - SYMBOL_IDS:  List of FIX Symbol IDs
    - SYMBOL_NAMES: Human-readable names matching those IDs
    - TIMEFRAME: Bar period (e.g. M1, H4, D1, ...)

### CREDENTIALS format

    {
        "ClientId": "8070_rHB1NkjH********************************5uyVn7G0s2",
        "Secret": "vIOIAyiAiX1r******************************yK21jWDk",
        "HostType": "demo",
        "AccessToken": "tjrDOG****************************3Go-PfY-4",
        "AccountId": 41*****0
    }

How to get ClientId and Secret:
1) Go to https://openapi.ctrader.com/ and log in.
2) Go to Applications > Add new app and fill details.
3) Once approved, go to https://openapi.ctrader.com/apps, locate your app, click Credentials, and copy both values.

How to get AccessToken:
1) On the same Applications page, click Sandbox next to Credentials.
2) Select “Account info” in Scope, click “Get token”, choose your account(s), and allow access.
3) Your access token will appear on the next page.

How to get HostType and AccountId:
1) Below the access token you’ll find "Trading accounts" – click to see a JSON file.
2) In cTrader terminal, log in and note your broker + account number.
3) Match this with the JSON file, and copy the correct accountId (not accountNumber).
4) Use "demo" or "live" in HostType based on the account type.

### SYMBOL_NAMES

Plain-text names of the symbols you trade, e.g. EURUSD, US30, ...

### SYMBOL_IDS

For each symbol:
1) In cTrader, open its chart.
2) On the right side, click the arrow to open “Symbol Info”.
3) Under the “Symbol” tab, find “FIX Symbol ID” – that’s what you use.

### TIMEFRAME

Possible values:
    M1, M2, M3, M4, M5, M10, M15, M30, H1, H4, H12, D1, W1.

### License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### Contact

For questions or suggestions, please contact `bouchane.dev@gmail.com`.