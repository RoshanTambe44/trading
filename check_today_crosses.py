import yfinance as yf
import pandas as pd

df = yf.download("^NSEI", period="1d", interval="1m", progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

print(f"Total 1m bars today: {len(df)}")
if df.empty:
    print("No data returned for today.")
    exit()

print("First bar:", df.index[0], "| Last bar:", df.index[-1])

# Resample to 15m
res_15m = df.resample("15min", origin="start").agg({
    "Open": "first", "High": "max", "Low": "min", "Close": "last"
}).dropna()

res_15m["ema_9"] = res_15m["Close"].ewm(span=9, adjust=False).mean()
res_15m["ema_21"] = res_15m["Close"].ewm(span=21, adjust=False).mean()
res_15m["spread"] = (res_15m["ema_9"] - res_15m["ema_21"]).round(2)

print("\n=== ALL 15-MINUTE BARS TODAY ===")
for idx, row in res_15m.iterrows():
    bar_t = idx.strftime("%H:%M")
    trend = "BULLISH (9 > 21)" if row["spread"] > 0 else "BEARISH (9 < 21)"
    close_val = row["Close"]
    e9 = row["ema_9"]
    e21 = row["ema_21"]
    sp = row["spread"]
    print(f"{bar_t} | Close: {close_val:,.2f} | 9 EMA: {e9:,.2f} | 21 EMA: {e21:,.2f} | Spread: {sp:+.2f} | {trend}")

crosses_15m = []
for i in range(1, len(res_15m)):
    prev = res_15m.iloc[i-1]
    curr = res_15m.iloc[i]
    if prev["spread"] <= 0 and curr["spread"] > 0:
        crosses_15m.append((curr.name.strftime("%H:%M"), "BULLISH CROSS (9 crossed ABOVE 21)"))
    elif prev["spread"] >= 0 and curr["spread"] < 0:
        crosses_15m.append((curr.name.strftime("%H:%M"), "BEARISH CROSS (9 crossed BELOW 21)"))

print("\n=== 15M CROSSOVERS TODAY ===")
if crosses_15m:
    for c in crosses_15m:
        print("  ->", c[0], ":", c[1])
else:
    print("  -> NO CROSSOVER OCCURRED ON 15M TODAY!")

# Check 5m
res_5m = df.resample("5min", origin="start").agg({
    "Open": "first", "High": "max", "Low": "min", "Close": "last"
}).dropna()
res_5m["ema_9"] = res_5m["Close"].ewm(span=9, adjust=False).mean()
res_5m["ema_21"] = res_5m["Close"].ewm(span=21, adjust=False).mean()
res_5m["spread"] = (res_5m["ema_9"] - res_5m["ema_21"]).round(2)

crosses_5m = []
for i in range(1, len(res_5m)):
    prev = res_5m.iloc[i-1]
    curr = res_5m.iloc[i]
    if prev["spread"] <= 0 and curr["spread"] > 0:
        crosses_5m.append((curr.name.strftime("%H:%M"), "BULLISH CROSS"))
    elif prev["spread"] >= 0 and curr["spread"] < 0:
        crosses_5m.append((curr.name.strftime("%H:%M"), "BEARISH CROSS"))

print("\n=== 5M CROSSOVERS TODAY ===")
if crosses_5m:
    for c in crosses_5m:
        print("  ->", c[0], ":", c[1])
else:
    print("  -> NO CROSSOVER OCCURRED ON 5M TODAY!")

# Check 30m
res_30m = df.resample("30min", origin="start").agg({
    "Open": "first", "High": "max", "Low": "min", "Close": "last"
}).dropna()
res_30m["ema_9"] = res_30m["Close"].ewm(span=9, adjust=False).mean()
res_30m["ema_21"] = res_30m["Close"].ewm(span=21, adjust=False).mean()
res_30m["spread"] = (res_30m["ema_9"] - res_30m["ema_21"]).round(2)

crosses_30m = []
for i in range(1, len(res_30m)):
    prev = res_30m.iloc[i-1]
    curr = res_30m.iloc[i]
    if prev["spread"] <= 0 and curr["spread"] > 0:
        crosses_30m.append((curr.name.strftime("%H:%M"), "BULLISH CROSS"))
    elif prev["spread"] >= 0 and curr["spread"] < 0:
        crosses_30m.append((curr.name.strftime("%H:%M"), "BEARISH CROSS"))

print("\n=== 30M CROSSOVERS TODAY ===")
if crosses_30m:
    for c in crosses_30m:
        print("  ->", c[0], ":", c[1])
else:
    print("  -> NO CROSSOVER OCCURRED ON 30M TODAY!")
