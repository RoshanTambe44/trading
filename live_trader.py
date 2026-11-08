import logging
import threading
import time
from datetime import datetime, time as dtime, timedelta
from typing import Dict, Any, Optional, List

from growwapi import GrowwAPI
from groww_service import groww_service
from strategy_backtester import (
    get_strike_for_mode,
    black_scholes_price,
    LOT_SIZE,
)
from data_feed import get_candles_df

logger = logging.getLogger("live_trader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class LiveEMABot:
    """
    Intraday 9/21 EMA Crossover Live Trading Engine.
    Supports Paper Trading (safe dry-run) and Live Broker Execution via Groww API.
    """

    def __init__(self):
        self.is_running: bool = False
        self.is_paper: bool = True  # True = Paper Trading, False = Live Broker Execution
        self.timeframe: str = "15m"
        self.mode: str = "ATM_BUY"
        self.start_time_str: str = "09:30"
        self.cutoff_time_str: str = "14:30"
        self.lot_size: int = LOT_SIZE

        # State tracking
        self.status: str = "IDLE"  # IDLE, RUNNING, IN_POSITION, SQUARED_OFF, ERROR
        self.current_position: Optional[Dict[str, Any]] = None
        self.active_trade_count: int = 0
        self.latest_spot: float = 0.0
        self.latest_ema9: float = 0.0
        self.latest_ema21: float = 0.0
        self.last_check_time: Optional[str] = None
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
        if len(self.logs) > 100:
            self.logs.pop()
        logger.info(f"[{level}] {message}")

    def start(
        self,
        timeframe: str = "15m",
        mode: str = "ATM_BUY",
        start_time: str = "09:30",
        cutoff_time: str = "14:30",
        is_paper: bool = True,
    ) -> Dict[str, Any]:
        """Starts the live trading bot thread."""
        if self.is_running:
            return {"success": False, "error": "Bot is already running."}

        self.timeframe = timeframe
        self.mode = mode
        self.start_time_str = start_time
        self.cutoff_time_str = cutoff_time
        self.is_paper = is_paper
        self.status = "RUNNING"
        self.active_trade_count = 0

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.is_running = True

        mode_text = "PAPER TRADING (Simulation)" if is_paper else "LIVE BROKER EXECUTION"
        self.log(f"Bot started: {mode_text} on {timeframe} timeframe | Mode: {mode}")
        return {"success": True, "status": self.status}

    def stop(self) -> Dict[str, Any]:
        """Stops the bot."""
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
        exit_prem = black_scholes_price(
            spot=exit_spot,
            strike=pos["strike"],
            dte_days=pos.get("dte", 1.0),
            opt_type=pos["option_type"],
        )

        # Real order placement if Live mode
        if not self.is_paper and groww_service.api_client:
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

        # PnL Calculation
        if pos["action"] == "BUY":
            gross_pnl = (exit_prem - pos["entry_premium"]) * self.lot_size
        else:
            gross_pnl = (pos["entry_premium"] - exit_prem) * self.lot_size

        self.log(
            f"Position closed ({reason}): {pos['trading_symbol']} @ ₹{exit_prem:.2f} (Gross PnL: ₹{gross_pnl:+.2f})"
        )
        self.current_position = None
        self.status = "RUNNING"
        return {"success": True, "gross_pnl": round(gross_pnl, 2)}

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status for dashboard polling."""
        unrealized_pnl = 0.0
        if self.current_position and self.latest_spot > 0:
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
            "logs": self.logs[:20],
        }

    def _run_loop(self):
        """Worker loop that checks bars and executes strategy signals."""
        while not self._stop_event.is_set():
            try:
                self._check_market_and_execute()
            except Exception as e:
                self.log(f"Worker loop exception: {e}", "ERROR")

            # Check every 10 seconds
            self._stop_event.wait(10)

    def _check_market_and_execute(self):
        """Processes latest candles and executes strategy rules."""
        now = datetime.now()
        curr_time = now.time()
        self.last_check_time = now.strftime("%H:%M:%S")

        start_h, start_m = map(int, self.start_time_str.split(":"))
        cutoff_h, cutoff_m = map(int, self.cutoff_time_str.split(":"))
        t_start = dtime(start_h, start_m)
        t_cutoff = dtime(cutoff_h, cutoff_m)
        t_squareoff = dtime(15, 0)

        # 1. Mandatory square-off at 15:00
        if curr_time >= t_squareoff and self.current_position:
            self.square_off("MANDATORY_1500")
            return

        # 2. Fetch latest candle data from DB
        df = get_candles_df()
        if df.empty or len(df) < 30:
            return

        # Resample to strategy timeframe
        rule_map = {"5m": "5min", "15m": "15min", "30m": "30min"}
        rule = rule_map.get(self.timeframe, "15min")
        res_df = df.resample(rule, origin="start").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()

        if len(res_df) < 22:
            return

        # Calculate EMAs
        res_df["ema_9"] = res_df["close"].ewm(span=9, adjust=False).mean()
        res_df["ema_21"] = res_df["close"].ewm(span=21, adjust=False).mean()

        latest_bar = res_df.iloc[-1]
        prev_bar = res_df.iloc[-2]

        self.latest_spot = round(float(latest_bar["close"]), 2)
        self.latest_ema9 = float(latest_bar["ema_9"])
        self.latest_ema21 = float(latest_bar["ema_21"])

        # Check for crossover
        prev_diff = prev_bar["ema_9"] - prev_bar["ema_21"]
        curr_diff = latest_bar["ema_9"] - latest_bar["ema_21"]

        bullish_cross = (prev_diff <= 0.0 and curr_diff > 0.0)
        bearish_cross = (prev_diff >= 0.0 and curr_diff < 0.0)

        if not (bullish_cross or bearish_cross):
            return

        signal_dir = "LONG" if bullish_cross else "SHORT"
        self.log(f"Crossover Signal Detected: {signal_dir} (EMA9: {self.latest_ema9:.1f}, EMA21: {self.latest_ema21:.1f})")

        # 3. Handle Active Position
        if self.current_position:
            if self.current_position["direction"] != signal_dir:
                self.log(f"Opposing crossover detected! Closing position...")
                self.square_off("OPPOSITE_CROSSOVER")

                # Immediate Reversal inside entry window
                if t_start <= curr_time <= t_cutoff:
                    self._open_position(signal_dir)
        else:
            # Not in position: check if inside entry window
            if t_start <= curr_time <= t_cutoff:
                self._open_position(signal_dir)
            else:
                self.log(f"Signal outside entry window ({self.start_time_str} - {self.cutoff_time_str}). Ignored.")

    def _open_position(self, direction: str):
        """Opens a new simulated or live options position."""
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
        if not self.is_paper and groww_service.api_client:
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
                self.log(f"Broker Order Placed: {res}")
            except Exception as e:
                self.log(f"Broker order execution error: {e}", "ERROR")

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
        self.log(f"Opened Position: {action} {trading_symbol} @ ₹{entry_prem:.2f} (Spot: {self.latest_spot})")


# Singleton live trading bot
live_bot = LiveEMABot()
