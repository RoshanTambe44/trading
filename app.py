import os
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
import pandas as pd

from config import Config, load_credentials, BASE_DIR
from groww_service import groww_service
from database import SessionLocal, StrategyRun, SimulatedTrade, NiftyCandle1M
from data_feed import get_candles_df, get_data_summary, seed_database_if_empty
from strategy_backtester import run_backtest, save_backtest_run, resample_bars
from live_trader import live_bot

app = Flask(__name__)
app.config.from_object(Config)

# In-memory run cache for instant filter response
RUN_CACHE = {}


# --- Groww Live Terminal Routes ---

@app.route("/")
def index():
    """Renders main trading terminal dashboard."""
    return render_template("index.html")


@app.route("/backtester")
def backtester_page():
    """Renders the 9/21 EMA Crossover Options Backtester & Trade Auditor."""
    return render_template("backtester.html")


@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns Groww connection and authentication status."""
    return jsonify(groww_service.get_status())


@app.route("/api/connect", methods=["POST"])
def connect():
    data = request.get_json(silent=True) or {}
    result = groww_service.connect(
        api_key=data.get("api_key"),
        api_secret=data.get("api_secret"),
        totp_code=data.get("totp_code"),
        totp_secret=data.get("totp_secret"),
    )
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/disconnect", methods=["POST"])
def disconnect():
    result = groww_service.disconnect()
    return jsonify(result)


@app.route("/api/profile", methods=["GET"])
def get_profile():
    result = groww_service.get_profile()
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/funds", methods=["GET"])
def get_funds():
    result = groww_service.get_funds()
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/holdings", methods=["GET"])
def get_holdings():
    result = groww_service.get_holdings()
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/positions", methods=["GET"])
def get_positions():
    result = groww_service.get_positions()
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/orders", methods=["GET"])
def get_orders():
    result = groww_service.get_orders()
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/dashboard-data", methods=["GET"])
def get_dashboard_data():
    status = groww_service.get_status()
    if not status.get("is_connected"):
        if status.get("has_saved_keys"):
            groww_service.connect()
            status = groww_service.get_status()

    if not status.get("is_connected"):
        return jsonify({
            "status": status,
            "profile": None,
            "funds": None,
            "holdings": None,
            "positions": None,
            "orders": None,
        })

    profile_res = groww_service.get_profile()
    funds_res = groww_service.get_funds()
    holdings_res = groww_service.get_holdings()
    positions_res = groww_service.get_positions()
    orders_res = groww_service.get_orders()

    return jsonify({
        "status": status,
        "profile": profile_res.get("profile") if profile_res.get("success") else None,
        "funds": funds_res.get("funds") if funds_res.get("success") else None,
        "holdings": holdings_res if holdings_res.get("success") else None,
        "positions": positions_res if positions_res.get("success") else None,
        "orders": orders_res if orders_res.get("success") else None,
    })


@app.route("/api/save-keys", methods=["POST"])
def save_keys():
    data = request.get_json(silent=True) or {}
    api_key = (data.get("api_key") or "").strip()
    api_secret = (data.get("api_secret") or "").strip()
    totp_secret = (data.get("totp_secret") or "").strip()

    if not api_key:
        return jsonify({"success": False, "error": "api_key cannot be empty"}), 400

    content_lines = [f"api_key = {api_key}\n"]
    if api_secret:
        content_lines.append(f"api_secret = {api_secret}\n")
    if totp_secret:
        content_lines.append(f"totp_secret = {totp_secret}\n")

    content = "".join(content_lines)

    target_files = [BASE_DIR / "keys.txt", BASE_DIR / "key.txt"]
    for tf in target_files:
        try:
            with open(tf, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return jsonify({"success": False, "error": f"Failed to write to {tf}: {e}"}), 500

    return jsonify({"success": True, "message": "Keys saved successfully."})


# --- Backtester & Strategy Routes ---

@app.route("/api/backtest/data-summary", methods=["GET"])
def backtest_data_summary():
    """Returns database summary of 1-minute NIFTY candles."""
    summary = get_data_summary()
    return jsonify(summary)


@app.route("/api/backtest/run", methods=["POST"])
def run_backtest_endpoint():
    """
    Executes backtest or returns cached results.
    Accepts:
      {
        "timeframe": "5m" | "15m" | "30m",
        "mode": "DEEP_ITM_BUY" | "ATM_BUY" | "ATM_SELL",
        "start_time": "09:30" ... "10:30",
        "cutoff_time": "11:30" ... "14:30"
      }
    """
    data = request.get_json(silent=True) or {}
    timeframe = data.get("timeframe", "15m")
    mode = data.get("mode", "ATM_BUY")
    start_time = data.get("start_time", "09:30")
    cutoff_time = data.get("cutoff_time", "14:30")

    cache_key = f"{timeframe}_{mode}_{start_time}_{cutoff_time}"
    if cache_key in RUN_CACHE:
        return jsonify(RUN_CACHE[cache_key])

    df_1m = get_candles_df()
    if df_1m.empty:
        # Seed database if not done yet
        seed_database_if_empty()
        df_1m = get_candles_df()

    results = run_backtest(
        df_1m=df_1m,
        timeframe=timeframe,
        mode=mode,
        start_time_str=start_time,
        cutoff_time_str=cutoff_time,
    )

    # Save to database for persistence
    run_id = save_backtest_run(
        {"timeframe": timeframe, "mode": mode, "start_time": start_time, "cutoff_time": cutoff_time},
        results,
    )

    # Format timestamps for JSON serialization
    serialized_trades = []
    for t in results["trades"]:
        tr_copy = dict(t)
        tr_copy["entry_time_str"] = t["entry_time"].strftime("%Y-%m-%d %H:%M")
        tr_copy["exit_time_str"] = t["exit_time"].strftime("%Y-%m-%d %H:%M")
        tr_copy["date_str"] = t["entry_time"].strftime("%Y-%m-%d")
        tr_copy["entry_timestamp"] = int(t["entry_time"].timestamp())
        tr_copy["exit_timestamp"] = int(t["exit_time"].timestamp())
        # Clean non-serializable objects
        tr_copy.pop("entry_bar_time", None)
        tr_copy.pop("entry_time", None)
        tr_copy.pop("exit_time", None)
        serialized_trades.append(tr_copy)

    payload = {
        "success": True,
        "run_id": run_id,
        "timeframe": timeframe,
        "mode": mode,
        "start_time": start_time,
        "cutoff_time": cutoff_time,
        "summary": results["summary"],
        "trades": serialized_trades,
    }

    RUN_CACHE[cache_key] = payload
    return jsonify(payload)


@app.route("/api/backtest/trade-chart/<trade_id>", methods=["GET"])
def get_trade_chart_data(trade_id):
    """
    Returns the resampled spot candles, 9 EMA, 21 EMA, and marker positions
    for the specific day/window of the selected trade.
    """
    timeframe = request.args.get("timeframe", "15m")
    db = SessionLocal()
    try:
        trade = db.query(SimulatedTrade).filter(SimulatedTrade.id == trade_id).first()
        if not trade:
            return jsonify({"success": False, "error": "Trade not found"}), 404

        # Fetch 1m candles for that entire trading day
        trade_date = trade.entry_time.date()
        day_start = datetime.combine(trade_date, datetime.min.time())
        day_end = datetime.combine(trade_date, datetime.max.time())

        df_day = get_candles_df(day_start, day_end)
        if df_day.empty:
            return jsonify({"success": False, "error": "No candle data for this trade date"}), 404

        # Resample to strategy timeframe
        res_df = resample_bars(df_day, timeframe)
        if res_df.empty:
            return jsonify({"success": False, "error": "Resampling failed"}), 400

        candles = []
        ema9_series = []
        ema21_series = []

        for idx, row in res_df.iterrows():
            epoch = int(idx.timestamp())
            candles.append({
                "time": epoch,
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
            })
            ema9_series.append({
                "time": epoch,
                "value": round(float(row["ema_9"]), 2),
            })
            ema21_series.append({
                "time": epoch,
                "value": round(float(row["ema_21"]), 2),
            })

        # Entry and Exit markers
        entry_epoch = int(trade.entry_time.timestamp())
        exit_epoch = int(trade.exit_time.timestamp())

        # Match nearest candle time for marker alignment
        candle_times = [c["time"] for c in candles]
        entry_marker_time = min(candle_times, key=lambda x: abs(x - entry_epoch))
        exit_marker_time = min(candle_times, key=lambda x: abs(x - exit_epoch))

        entry_marker = {
            "time": entry_marker_time,
            "position": "belowBar" if trade.direction == "LONG" else "aboveBar",
            "color": "#10b981" if trade.direction == "LONG" else "#ef4444",
            "shape": "arrowUp" if trade.direction == "LONG" else "arrowDown",
            "text": f"ENTRY: {trade.direction} {trade.strike} {trade.option_type} @ {trade.entry_premium}",
        }

        exit_marker = {
            "time": exit_marker_time,
            "position": "aboveBar" if trade.direction == "LONG" else "belowBar",
            "color": "#f59e0b",
            "shape": "circle",
            "text": f"EXIT: {trade.exit_reason} @ {trade.exit_premium} (Net: Rs {trade.net_pnl:+.2f})",
        }

        return jsonify({
            "success": True,
            "trade": {
                "id": trade.id,
                "trade_number": trade.trade_number,
                "direction": trade.direction,
                "strike": trade.strike,
                "option_type": trade.option_type,
                "expiry_date": trade.expiry_date,
                "dte": trade.dte,
                "nifty_entry": trade.nifty_entry,
                "nifty_exit": trade.nifty_exit,
                "entry_premium": trade.entry_premium,
                "exit_premium": trade.exit_premium,
                "gross_pnl": trade.gross_pnl,
                "slippage": trade.slippage,
                "brokerage": trade.brokerage,
                "stt": trade.stt,
                "exchange_charges": trade.exchange_charges,
                "sebi_charges": trade.sebi_charges,
                "stamp_duty": trade.stamp_duty,
                "gst": trade.gst,
                "total_friction": trade.total_friction,
                "net_pnl": trade.net_pnl,
                "exit_reason": trade.exit_reason,
                "is_whipsaw": trade.is_whipsaw,
                "entry_time_str": trade.entry_time.strftime("%Y-%m-%d %H:%M"),
                "exit_time_str": trade.exit_time.strftime("%Y-%m-%d %H:%M"),
            },
            "candles": candles,
            "ema9": ema9_series,
            "ema21": ema21_series,
            "markers": [entry_marker, exit_marker],
        })
    finally:
        db.close()


# --- Live / Paper Trading Bot Routes ---

@app.route("/api/bot/status", methods=["GET"])
def get_bot_status():
    """Returns real-time status of the Live / Paper trading bot."""
    return jsonify(live_bot.get_status())


@app.route("/api/bot/start", methods=["POST"])
def start_bot():
    """Starts the 9/21 EMA live/paper trading bot."""
    data = request.get_json(silent=True) or {}
    timeframe = data.get("timeframe", "15m")
    mode = data.get("mode", "ATM_BUY")
    start_time = data.get("start_time", "09:30")
    cutoff_time = data.get("cutoff_time", "14:30")
    is_paper = data.get("is_paper", True)

    res = live_bot.start(
        timeframe=timeframe,
        mode=mode,
        start_time=start_time,
        cutoff_time=cutoff_time,
        is_paper=is_paper,
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():
    """Stops the live/paper trading bot."""
    res = live_bot.stop()
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@app.route("/api/bot/squareoff", methods=["POST"])
def bot_squareoff():
    """Immediately exits any open position."""
    res = live_bot.square_off("MANUAL_PANIC_SQUAREOFF")
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


# --- Export Backtest & Webhook Routes ---

@app.route("/api/backtest/export-csv", methods=["POST"])
def export_backtest_csv():
    """Generates and returns downloadable CSV of backtest trades."""
    data = request.get_json(silent=True) or {}
    trades = data.get("trades", [])
    if not trades:
        return jsonify({"error": "No trades to export"}), 400

    import io
    import csv
    from flask import Response

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Trade #", "Date", "Direction", "Strike", "Option Type", "DTE",
        "NIFTY Entry", "NIFTY Exit", "Entry Premium", "Exit Premium",
        "Gross PnL (Rs)", "Slippage (Rs)", "Brokerage (Rs)", "STT (Rs)",
        "Exchange (Rs)", "SEBI (Rs)", "Stamp Duty (Rs)", "GST (Rs)",
        "Total Friction (Rs)", "Net PnL (Rs)", "Exit Reason", "Whipsaw"
    ])

    for t in trades:
        writer.writerow([
            t.get("trade_number"),
            t.get("date_str"),
            t.get("direction"),
            t.get("strike"),
            t.get("option_type"),
            t.get("dte"),
            t.get("nifty_entry") or t.get("entry_spot"),
            t.get("nifty_exit") or t.get("exit_spot"),
            t.get("entry_premium"),
            t.get("exit_premium"),
            t.get("gross_pnl"),
            t.get("slippage"),
            t.get("brokerage"),
            t.get("stt"),
            t.get("exchange_charges"),
            t.get("sebi_charges"),
            t.get("stamp_duty"),
            t.get("gst"),
            t.get("total_friction"),
            t.get("net_pnl"),
            t.get("exit_reason"),
            "YES" if t.get("is_whipsaw") else "NO"
        ])

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=nifty_ema_backtest_trades.csv"}
    )


@app.route("/api/webhook/tradingview", methods=["POST"])
def tradingview_webhook():
    """
    Webhook endpoint to receive automated alert payloads from TradingView.
    Payload:
      {
        "secret": "groww-trading-terminal-secret-key-2026",
        "symbol": "NIFTY",
        "action": "BUY" | "SELL" | "SQUAREOFF",
        "direction": "LONG" | "SHORT"
      }
    """
    data = request.get_json(silent=True) or {}
    secret = data.get("secret")
    if secret != Config.SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized webhook secret"}), 401

    action = (data.get("action") or "").upper()
    direction = (data.get("direction") or "LONG").upper()

    if action == "SQUAREOFF":
        res = live_bot.square_off("TRADINGVIEW_WEBHOOK_SQUAREOFF")
        return jsonify(res)
    elif action in ["BUY", "SELL"]:
        live_bot._open_position(direction)
        return jsonify({"success": True, "message": f"Executed {action} {direction} via TradingView webhook"})

    return jsonify({"success": False, "error": "Unknown webhook action"}), 400


if __name__ == "__main__":
    print(f"[*] Starting Groww Trading Terminal on http://{Config.HOST}:{Config.PORT}")
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
