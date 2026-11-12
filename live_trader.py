import logging
import threading
import time
from datetime import datetime, time as dtime, timedelta
from typing import Dict, Any, Optional, List
import pandas as pd
import yfinance as yf

from growwapi import GrowwAPI
from groww_service import groww_service
from strategy_backtester import (
    get_strike_for_mode,
    black_scholes_price,
    LOT_SIZE,
)
from database import SessionLocal, NiftyCandle1M
from telegram_notifier import telegram_notifier

logger = logging.getLogger("live_trader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class LiveEMABot:
    """
    Intraday 9/21 EMA Crossover Live & Paper Trading Engine.
    Continuously fetches live 1-minute NIFTY market data, resamples to the strategy timeframe,
    monitors EMA crossovers on closed bars, and executes paper/live option trades.
    """

    def __init__(self):
        self.is_running: bool = False
        self.is_paper: bool = True  # True = Paper Trading (Simulation), False = Live Broker Execution
        self.symbol: str = "^NSEI"
        self.currency: str = "₹"
        self.is_us: bool = False
        self.timeframe: str = "15m"
        self.mode: str = "ATM_BUY"
        self.start_time_str: str = "09:30"
        self.cutoff_time_str: str = "14:30"
        self.lot_size: int = LOT_SIZE

        # State tracking
        self.status: str = "IDLE"  # IDLE, RUNNING, IN_POSITION, SQUARED_OFF, ERROR
        self.current_position: Optional[Dict[str, Any]] = None
        self.completed_trades: List[Dict[str, Any]] = []
        self.total_realized_pnl: float = 0.0
        self.active_trade_count: int = 0
        self.latest_spot: float = 0.0
        self.latest_ema9: float = 0.0
        self.latest_ema21: float = 0.0
        self.last_check_time: Optional[str] = None
        self.last_logged_bar_time: Optional[Any] = None
        self.last_heartbeat_time: float = 0.0
        self.logs: List[Dict[str, str]] = []

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def log(self, message: str, level: str = "INFO"):
        """Appends a timestamped log entry."""
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "level": level,
        }
        self.logs.insert(0, entry)
        if len(self.logs) > 150:
            self.logs.pop()
        logger.info(f"[{level}] {message}")

    def start(
        self,
        symbol: str = "^NSEI",
        timeframe: str = "15m",
        mode: str = "ATM_BUY",
        start_time: str = "09:30",
        cutoff_time: str = "14:30",
        is_paper: bool = True,
    ) -> Dict[str, Any]:
        """Starts the live trading bot background thread."""
        if self.is_running:
            return {"success": False, "error": "Bot is already running."}

        sym = symbol.upper().strip()
        self.symbol = sym
        self.is_us = sym not in ["^NSEI", "NIFTY", "NIFTY50", "NIFTY 50"]
        self.currency = "$" if self.is_us else "₹"
        self.timeframe = timeframe
        self.mode = mode
        self.start_time_str = start_time
        self.cutoff_time_str = cutoff_time
        self.is_paper = is_paper
        self.status = "RUNNING"
        self.active_trade_count = 0
        self.last_logged_bar_time = None
        self.last_heartbeat_time = 0.0

        if self.is_us:
            self.lot_size = 10
            if "50" in mode:
                self.lot_size = 50
            elif "100" in mode:
                self.lot_size = 100
        else:
            self.lot_size = LOT_SIZE

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.is_running = True

        mode_text = "PAPER TRADING (Simulation)" if is_paper else "LIVE BROKER EXECUTION"
        market_label = "US Market (NYSE/NASDAQ)" if self.is_us else "Indian Market (NSE)"
        self.log(f"Bot started: {mode_text} on {self.symbol} [{market_label}] ({timeframe}) | Mode: {mode}")
        self.log(f"Entry Window: {start_time} - {cutoff_time} IST | Lot: {self.lot_size} | Currency: {self.currency}")

        # Send Telegram notification on startup
        try:
            telegram_notifier.notify_startup(is_paper, timeframe, mode, symbol=self.symbol)
        except Exception:
            pass

        return {"success": True, "status": self.status}

    def stop(self) -> Dict[str, Any]:
        """Stops the live trading bot."""
        if not self.is_running:
            return {"success": False, "error": "Bot is not running."}

        self._stop_event.set()
        self.is_running = False
        self.status = "IDLE"
        self.log("Bot stopped by user.")
        return {"success": True, "status": self.status}

    def square_off(self, reason: str = "MANUAL_SQUAREOFF") -> Dict[str, Any]:
        """Force-closes current active position."""
        if not self.current_position:
            return {"success": False, "error": "No open position to square off."}

        pos = self.current_position
        exit_spot = self.latest_spot or pos["entry_spot"]

        if self.is_us:
            exit_prem = exit_spot
            if pos["action"] == "BUY":
                gross_pnl = (exit_prem - pos["entry_premium"]) * self.lot_size
            else:
                gross_pnl = (pos["entry_premium"] - exit_prem) * self.lot_size
        else:
            exit_prem = black_scholes_price(
                spot=exit_spot,
                strike=pos["strike"],
                dte_days=pos.get("dte", 1.0),
                opt_type=pos["option_type"],
            )
            # Real broker order if Live mode
            if not self.is_paper:
                if groww_service.api_client:
                    try:
                        exit_side = (
                            GrowwAPI.TRANSACTION_TYPE_SELL
                            if pos["action"] == "BUY"
                            else GrowwAPI.TRANSACTION_TYPE_BUY
                        )
                        groww_service.api_client.place_order(
                            validity=GrowwAPI.VALIDITY_DAY,
                            exchange=GrowwAPI.EXCHANGE_NSE,
                            order_type=GrowwAPI.ORDER_TYPE_MARKET,
                            product=GrowwAPI.PRODUCT_MIS,
                            quantity=self.lot_size,
                            segment=GrowwAPI.SEGMENT_FNO,
                            trading_symbol=pos["trading_symbol"],
                            transaction_type=exit_side,
                        )
                    except Exception as e:
                        self.log(f"Broker order exit error: {e}", "ERROR")
                else:
                    self.log("Groww API disconnected during live exit; simulated paper exit.", "WARNING")

            if pos["action"] == "BUY":
                gross_pnl = (exit_prem - pos["entry_premium"]) * self.lot_size
            else:
                gross_pnl = (pos["entry_premium"] - exit_prem) * self.lot_size

        self.log(
            f"Position closed ({reason}): {pos['trading_symbol']} @ {self.currency}{exit_prem:.2f} (Gross PnL: {self.currency}{gross_pnl:+.2f})"
        )

        # Record completed paper / live trade
        trade_record = {
            "symbol": pos["trading_symbol"],
            "direction": pos["direction"],
            "action": pos["action"],
            "entry_price": pos["entry_premium"],
            "exit_price": exit_prem,
            "entry_time": pos["entry_time"],
            "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pnl": round(gross_pnl, 2),
            "reason": reason,
            "currency": self.currency,
            "is_paper": self.is_paper,
        }
        self.completed_trades.insert(0, trade_record)
        self.total_realized_pnl += gross_pnl

        # Telegram Alert on Exit
        try:
            telegram_notifier.notify_trade_exit(
                symbol=pos["trading_symbol"],
                reason=reason,
                exit_price=exit_prem,
                net_pnl=round(gross_pnl, 2),
                is_paper=self.is_paper,
                currency=self.currency,
            )
        except Exception:
            pass

        self.current_position = None
        self.status = "RUNNING"
        return {"success": True, "gross_pnl": round(gross_pnl, 2)}

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status for web UI polling."""
        unrealized_pnl = 0.0
        if self.current_position and self.latest_spot > 0:
            if self.is_us:
                if self.current_position["action"] == "BUY":
                    unrealized_pnl = (self.latest_spot - self.current_position["entry_premium"]) * self.lot_size
                else:
                    unrealized_pnl = (self.current_position["entry_premium"] - self.latest_spot) * self.lot_size
            else:
                current_prem = black_scholes_price(
                    spot=self.latest_spot,
                    strike=self.current_position["strike"],
                    dte_days=self.current_position.get("dte", 1.0),
                    opt_type=self.current_position["option_type"],
                )
                if self.current_position["action"] == "BUY":
                    unrealized_pnl = (current_prem - self.current_position["entry_premium"]) * self.lot_size
                else:
                    unrealized_pnl = (self.current_position["entry_premium"] - current_prem) * self.lot_size

        return {
            "is_running": self.is_running,
            "status": self.status,
            "symbol": self.symbol,
            "currency": self.currency,
            "is_us": self.is_us,
            "is_paper": self.is_paper,
            "timeframe": self.timeframe,
            "mode": self.mode,
            "start_time": self.start_time_str,
            "cutoff_time": self.cutoff_time_str,
            "latest_spot": self.latest_spot,
            "latest_ema9": round(self.latest_ema9, 2),
            "latest_ema21": round(self.latest_ema21, 2),
            "last_check_time": self.last_check_time,
            "current_position": self.current_position,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "active_trade_count": self.active_trade_count,
            "completed_trades": self.completed_trades[:20],
            "total_realized_pnl": round(self.total_realized_pnl, 2),
            "win_count": sum(1 for t in self.completed_trades if t.get("pnl", 0) > 0),
            "loss_count": sum(1 for t in self.completed_trades if t.get("pnl", 0) <= 0),
            "logs": self.logs[:30],
        }

    def _fetch_today_live_bars(self) -> pd.DataFrame:
        """Fetches today's live 1-minute candles and syncs to database."""
        try:
            fetch_sym = self.symbol if self.is_us else "^NSEI"
            df = yf.download(fetch_sym, period="1d", interval="1m", progress=False)
            if df.empty:
                return pd.DataFrame()

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.dropna()
            # Convert to Indian Standard Time (IST) if US symbol
            if df.index.tz is not None:
                df = df.tz_convert("Asia/Kolkata").tz_localize(None)

            clean_df = pd.DataFrame({
                "open": df["Open"].astype(float).round(2),
                "high": df["High"].astype(float).round(2),
                "low": df["Low"].astype(float).round(2),
                "close": df["Close"].astype(float).round(2),
                "volume": df.get("Volume", 0).astype(int),
            }, index=df.index)

            # Sync to database if NIFTY
            if not self.is_us:
                db = SessionLocal()
                try:
                    for idx, row in clean_df.iterrows():
                        ts = idx.to_pydatetime()
                        existing = db.query(NiftyCandle1M).filter(NiftyCandle1M.timestamp == ts).first()
                        if not existing:
                            db.add(NiftyCandle1M(
                                timestamp=ts,
                                open=row["open"],
                                high=row["high"],
                                low=row["low"],
                                close=row["close"],
                                volume=row["volume"],
                            ))
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()

            return clean_df
        except Exception as e:
            logger.error(f"Error fetching live 1m bars for {self.symbol}: {e}")
            return pd.DataFrame()

    def _run_loop(self):
        """Worker loop checking market ticks every 10 seconds."""
        # Initial check immediately
        try:
            self._check_market_and_execute()
        except Exception as e:
            self.log(f"Initial check error: {e}", "ERROR")

        while not self._stop_event.is_set():
            # Wait 10 seconds between checks
            if self._stop_event.wait(10):
                break
            try:
                self._check_market_and_execute()
            except Exception as e:
                self.log(f"Worker loop exception: {e}", "ERROR")

    def _check_market_and_execute(self):
        """Processes latest candles and executes strategy rules."""
        now = datetime.now()
        curr_time = now.time()
        self.last_check_time = now.strftime("%H:%M:%S")

        start_h, start_m = map(int, self.start_time_str.split(":"))
        cutoff_h, cutoff_m = map(int, self.cutoff_time_str.split(":"))
        t_start = dtime(start_h, start_m)
        t_cutoff = dtime(cutoff_h, cutoff_m)

        # 1. Mandatory square-off check
        if self.is_us:
            is_squareoff = (curr_time >= dtime(2, 25) and curr_time < dtime(20, 0))
        else:
            is_squareoff = (curr_time >= dtime(15, 0))

        if is_squareoff and self.current_position:
            self.square_off("MANDATORY_CLOSE")
            return

        # 2. Fetch today's live 1-minute candles
        df_today = self._fetch_today_live_bars()
        if df_today.empty or len(df_today) < 3:
            # Fallback to DB if yfinance is temporarily empty (for NIFTY)
            if not self.is_us:
                db = SessionLocal()
                try:
                    today_start = datetime.combine(now.date(), dtime(9, 15))
                    rows = db.query(NiftyCandle1M).filter(NiftyCandle1M.timestamp >= today_start).order_by(NiftyCandle1M.timestamp.asc()).all()
                    if rows:
                        data = [{"open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume} for r in rows]
                        df_today = pd.DataFrame(data, index=[r.timestamp for r in rows])
                finally:
                    db.close()

        if df_today.empty or len(df_today) < 3:
            self.log(f"Waiting for live {self.symbol} market candles...", "WARNING")
            return

        # Update latest spot
        latest_1m_bar = df_today.iloc[-1]
        self.latest_spot = round(float(latest_1m_bar["close"]), 2)

        # 2b. Hard Max-Loss Stop Loss Circuit Breaker
        if self.current_position and self.latest_spot > 0:
            current_status = self.get_status()
            unrealized = current_status.get("unrealized_pnl", 0.0)
            max_loss_limit = -50.0 if self.is_us else -1800.0  # -$50 for US, -₹1800 for NIFTY
            if unrealized <= max_loss_limit:
                self.log(
                    f"🛑 HARD STOP-LOSS TRIGGERED: Loss reached {self.currency}{unrealized:.2f} (Limit: {self.currency}{max_loss_limit}). Exiting immediately!",
                    "WARNING"
                )
                self.square_off("HARD_STOP_LOSS_CIRCUIT_BREAKER")
                return

        # 3. Resample today's bars to strategy timeframe
        rule_map = {"5m": "5min", "15m": "15min", "30m": "30min"}
        rule = rule_map.get(self.timeframe, "15min")
        res_df = df_today.resample(rule, origin="start").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()

        if len(res_df) < 2:
            self.log(f"Waiting for at least 2 closed {self.timeframe} bars (currently {len(res_df)})...")
            return

        # Calculate EMAs
        res_df["ema_9"] = res_df["close"].ewm(span=9, adjust=False).mean()
        res_df["ema_21"] = res_df["close"].ewm(span=21, adjust=False).mean()

        latest_closed_bar = res_df.iloc[-1]
        prev_closed_bar = res_df.iloc[-2]

        self.latest_ema9 = float(latest_closed_bar["ema_9"])
        self.latest_ema21 = float(latest_closed_bar["ema_21"])
        bar_timestamp = latest_closed_bar.name

        # Calculate EMA spread & trend
        spread = round(self.latest_ema9 - self.latest_ema21, 2)
        trend = "BULLISH" if spread > 0 else "BEARISH"

        # Check for crossover
        prev_diff = prev_closed_bar["ema_9"] - prev_closed_bar["ema_21"]
        curr_diff = latest_closed_bar["ema_9"] - latest_closed_bar["ema_21"]

        bullish_cross = (prev_diff <= 0.0 and curr_diff > 0.0)
        bearish_cross = (prev_diff >= 0.0 and curr_diff < 0.0)

        # 4. Heartbeat logging when bar closes or every 45 seconds
        current_epoch = time.time()
        is_new_bar = (self.last_logged_bar_time != bar_timestamp)
        is_heartbeat_due = (current_epoch - self.last_heartbeat_time >= 45)

        if is_new_bar or is_heartbeat_due:
            self.last_logged_bar_time = bar_timestamp
            self.last_heartbeat_time = current_epoch

            bar_time_str = bar_timestamp.strftime("%H:%M") if hasattr(bar_timestamp, "strftime") else str(bar_timestamp)
            if self.current_position:
                unrealized = self.get_status().get("unrealized_pnl", 0.0)
                pnl_sign = "+" if unrealized >= 0 else ""
                self.log(
                    f"[{bar_time_str}] {self.symbol}: {self.currency}{self.latest_spot:.2f} | 9 EMA: {self.latest_ema9:.1f} | 21 EMA: {self.latest_ema21:.1f} | Pos: {self.current_position['trading_symbol']} ({pnl_sign}{self.currency}{unrealized:.2f})"
                )
            else:
                self.log(
                    f"[{bar_time_str}] {self.symbol}: {self.currency}{self.latest_spot:.2f} | 9 EMA: {self.latest_ema9:.1f} | 21 EMA: {self.latest_ema21:.1f} | Spread: {spread:+.1f} pts ({trend}) | Waiting for cross"
                )

        # 5. Handle Crossover Signals
        in_entry_window = False
        if t_start <= t_cutoff:
            in_entry_window = (t_start <= curr_time <= t_cutoff)
        else:
            in_entry_window = (curr_time >= t_start or curr_time <= t_cutoff)

        if bullish_cross or bearish_cross:
            signal_dir = "LONG" if bullish_cross else "SHORT"
            self.log(f"🚨 CROSSOVER SIGNAL: {signal_dir}! (9 EMA crossed 21 EMA: {self.latest_ema9:.1f} vs {self.latest_ema21:.1f})")

            # Check active position
            if self.current_position:
                if self.current_position["direction"] != signal_dir:
                    self.log(f"Opposing cross confirmed! Exiting current {self.current_position['direction']} position...")
                    self.square_off("OPPOSITE_CROSSOVER")

                    # Immediate Reversal inside entry window
                    if in_entry_window:
                        self.log("Immediate Reversal: Opening reverse position inside entry window...")
                        self._open_position(signal_dir)
                    else:
                        self.log(f"Reversal skipped: Current time {self.last_check_time} outside entry window ({self.start_time_str} - {self.cutoff_time_str}).")
            else:
                # Not in position: check if inside entry window
                if in_entry_window:
                    self._open_position(signal_dir)
                else:
                    self.log(f"Signal ignored: {curr_time.strftime('%H:%M')} is outside entry window ({self.start_time_str} - {self.cutoff_time_str}).")

    def _open_position(self, direction: str):
        """Opens a new simulated or live position."""
        if self.is_us:
            action = "BUY" if direction == "LONG" else "SHORT"
            trading_symbol = f"{self.symbol} ({self.lot_size} Shares)"
            entry_prem = self.latest_spot

            self.active_trade_count += 1
            self.current_position = {
                "trading_symbol": trading_symbol,
                "direction": direction,
                "action": action,
                "strike": int(round(self.latest_spot)),
                "option_type": "SHARES",
                "entry_spot": self.latest_spot,
                "entry_premium": entry_prem,
                "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "dte": 0.0,
            }
            self.status = "IN_POSITION"
            self.log(f"🎯 Opened Paper Position: {action} {trading_symbol} @ {self.currency}{entry_prem:.2f} (Spot: {self.currency}{self.latest_spot:.2f}, Qty: {self.lot_size})")

            try:
                telegram_notifier.notify_trade_entry(
                    mode=self.mode,
                    symbol=trading_symbol,
                    action=action,
                    price=entry_prem,
                    spot=self.latest_spot,
                    qty=self.lot_size,
                    is_paper=self.is_paper,
                    currency=self.currency,
                )
            except Exception:
                pass
            return

        # NIFTY Options
        strike, opt_type = get_strike_for_mode(self.latest_spot, self.mode, direction)
        expiry_str = (datetime.now() + timedelta(days=2)).strftime("%d%b%y").upper()
        trading_symbol = f"NIFTY{expiry_str}{strike}{opt_type}"

        dte = 2.0
        entry_prem = black_scholes_price(
            spot=self.latest_spot,
            strike=strike,
            dte_days=dte,
            opt_type=opt_type,
        )

        action = "BUY"
        if self.mode == "ATM_SELL":
            action = "SELL"

        # Place broker order if Live mode
        if not self.is_paper:
            if groww_service.api_client:
                try:
                    txn_type = (
                        GrowwAPI.TRANSACTION_TYPE_BUY
                        if action == "BUY"
                        else GrowwAPI.TRANSACTION_TYPE_SELL
                    )
                    res = groww_service.api_client.place_order(
                        validity=GrowwAPI.VALIDITY_DAY,
                        exchange=GrowwAPI.EXCHANGE_NSE,
                        order_type=GrowwAPI.ORDER_TYPE_MARKET,
                        product=GrowwAPI.PRODUCT_MIS,
                        quantity=self.lot_size,
                        segment=GrowwAPI.SEGMENT_FNO,
                        trading_symbol=trading_symbol,
                        transaction_type=txn_type,
                    )
                    self.log(f"⚡ Groww Broker Order Response: {res}")
                except Exception as e:
                    self.log(f"Broker order execution error: {e}", "ERROR")
            else:
                self.log("⚠️ Groww API disconnected! Order fell back to Paper execution.", "WARNING")

        self.active_trade_count += 1
        self.current_position = {
            "trading_symbol": trading_symbol,
            "direction": direction,
            "action": action,
            "strike": strike,
            "option_type": opt_type,
            "entry_spot": self.latest_spot,
            "entry_premium": entry_prem,
            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dte": dte,
        }
        self.status = "IN_POSITION"
        self.log(f"🎯 Opened Position: {action} {trading_symbol} @ ₹{entry_prem:.2f} (Spot: ₹{self.latest_spot:.2f}, Qty: {self.lot_size})")

        # Telegram Alert on Entry
        try:
            telegram_notifier.notify_trade_entry(
                mode=self.mode,
                symbol=trading_symbol,
                action=action,
                price=entry_prem,
                spot=self.latest_spot,
                qty=self.lot_size,
                is_paper=self.is_paper,
                currency="₹",
            )
        except Exception:
            pass


# Singleton live trading bot
live_bot = LiveEMABot()
