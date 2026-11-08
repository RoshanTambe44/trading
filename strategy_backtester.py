import math
import uuid
from datetime import datetime, time as dtime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy.stats import norm

from database import SessionLocal, StrategyRun, SimulatedTrade

# Sizing & parameters
LOT_SIZE = 65
MIN_TICK = 0.05
RISK_FREE_RATE = 0.07  # 7% Indian risk-free rate
DEFAULT_IV = 0.135  # 13.5% IV for NIFTY


# --- Black-Scholes Options Pricing ---

def black_scholes_price(
    spot: float,
    strike: float,
    dte_days: float,
    opt_type: str = "CE",
    iv: float = DEFAULT_IV,
    r: float = RISK_FREE_RATE,
) -> float:
    """
    Computes Black-Scholes theoretical price for European option.
    dte_days: remaining time in days (supports fractional days for intraday).
    """
    if dte_days <= 0.0001:
        # At expiration: intrinsic value
        if opt_type == "CE":
            return max(0.0, spot - strike)
        else:
            return max(0.0, strike - spot)

    T = dte_days / 365.0
    sigma_sqrt_t = iv * math.sqrt(T)

    d1 = (math.log(spot / strike) + (r + 0.5 * iv**2) * T) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t

    if opt_type == "CE":
        price = spot * norm.cdf(d1) - strike * math.exp(-r * T) * norm.cdf(d2)
    else:
        price = strike * math.exp(-r * T) * norm.cdf(-d2) - spot * norm.cdf(-d1)

    return max(MIN_TICK, round(price, 2))


def get_strike_for_mode(spot: float, mode: str, signal_direction: str) -> Tuple[int, str]:
    """
    Determines strike and option type based on mode and signal direction.
    Modes:
      DEEP_ITM_BUY: Call = Spot - 250, Put = Spot + 250
      ATM_BUY: Call/Put = nearest 50-strike
      ATM_SELL: Short Put for Bullish, Short Call for Bearish
    """
    atm_strike = int(round(spot / 50.0) * 50)

    if mode == "DEEP_ITM_BUY":
        if signal_direction == "LONG":
            # Buy ITM Call (5 strikes in the money = 250 pts below spot)
            return atm_strike - 250, "CE"
        else:
            # Buy ITM Put (5 strikes in the money = 250 pts above spot)
            return atm_strike + 250, "PE"

    elif mode == "ATM_BUY":
        if signal_direction == "LONG":
            return atm_strike, "CE"
        else:
            return atm_strike, "PE"

    elif mode == "ATM_SELL":
        if signal_direction == "LONG":
            # Bullish: Sell ATM Put
            return atm_strike, "PE"
        else:
            # Bearish: Sell ATM Call
            return atm_strike, "CE"

    return atm_strike, "CE"


# --- Friction & Indian Regulatory Cost Stack ---

def calculate_trade_costs(
    mode: str,
    entry_premium: float,
    exit_premium: float,
    lot_size: int = LOT_SIZE,
) -> Dict[str, float]:
    """
    Calculates detailed Indian options cost stack and slippage.
    Slippage: 0.5% of premium + 0.10 pts; sell price floored at 0.05 tick.
    """
    is_seller = (mode == "ATM_SELL")

    # Slippage
    entry_slip = 0.005 * entry_premium + 0.10
    exit_slip = 0.005 * exit_premium + 0.10
    total_slippage_cost = round((entry_slip + exit_slip) * lot_size, 2)

    # Executed prices after slippage
    if not is_seller:
        # Buyer: pays more on entry, receives less on exit
        adj_entry_prem = entry_premium + entry_slip
        adj_exit_prem = max(MIN_TICK, exit_premium - exit_slip)
        buy_turnover = adj_entry_prem * lot_size
        sell_turnover = adj_exit_prem * lot_size
        gross_pnl = (exit_premium - entry_premium) * lot_size
    else:
        # Seller: receives less on entry, pays more on exit
        adj_entry_prem = max(MIN_TICK, entry_premium - entry_slip)
        adj_exit_prem = exit_premium + exit_slip
        sell_turnover = adj_entry_prem * lot_size
        buy_turnover = adj_exit_prem * lot_size
        gross_pnl = (entry_premium - exit_premium) * lot_size

    total_turnover = buy_turnover + sell_turnover

    # 1. Brokerage: flat Rs 20 per executed order (round-trip = Rs 40)
    brokerage = 40.00

    # 2. STT: 0.1% on sell-side turnover
    stt = round(0.001 * sell_turnover, 2)

    # 3. Exchange transaction charges: 0.0505% on total turnover
    exchange_charges = round(0.000505 * total_turnover, 2)

    # 4. SEBI turnover fee: Rs 10 per crore = 0.0001%
    sebi_charges = round(0.000001 * total_turnover, 2)

    # 5. Stamp duty: 0.003% on buy-side turnover
    stamp_duty = round(0.00003 * buy_turnover, 2)

    # 6. GST: 18% on (Brokerage + Exchange + SEBI)
    gst = round(0.18 * (brokerage + exchange_charges + sebi_charges), 2)

    regulatory_charges = round(brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst, 2)
    total_friction = round(total_slippage_cost + regulatory_charges, 2)
    net_pnl = round(gross_pnl - total_friction, 2)

    return {
        "gross_pnl": round(gross_pnl, 2),
        "slippage": total_slippage_cost,
        "brokerage": brokerage,
        "stt": stt,
        "exchange_charges": exchange_charges,
        "sebi_charges": sebi_charges,
        "stamp_duty": stamp_duty,
        "gst": gst,
        "total_friction": total_friction,
        "net_pnl": net_pnl,
    }


# --- Resampling & Indicators ---

def resample_bars(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resamples 1m spot bars to 5m, 15m, or 30m, aligned strictly to 09:15 open.
    """
    if df_1m.empty:
        return pd.DataFrame()

    rule_map = {"5m": "5min", "15m": "15min", "30m": "30min"}
    rule = rule_map.get(timeframe, "15min")

    resampled_days = []
    # Resample day by day so bars don't bleed across overnight gaps
    for date, group in df_1m.groupby(df_1m.index.date):
        daily_res = group.resample(rule, origin="start").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()
        resampled_days.append(daily_res)

    if not resampled_days:
        return pd.DataFrame()

    res = pd.concat(resampled_days)

    # Calculate EMAs on closed bars
    res["ema_9"] = res["close"].ewm(span=9, adjust=False).mean()
    res["ema_21"] = res["close"].ewm(span=21, adjust=False).mean()

    return res


# --- Backtester Engine ---

def run_backtest(
    df_1m: pd.DataFrame,
    timeframe: str = "15m",
    mode: str = "ATM_BUY",
    start_time_str: str = "09:30",
    cutoff_time_str: str = "14:30",
) -> Dict[str, Any]:
    """
    Executes the 9/21 EMA crossover strategy backtest across the provided 1m dataset.
    """
    if df_1m.empty:
        return {"summary": {}, "trades": []}

    res_df = resample_bars(df_1m, timeframe)
    if res_df.empty or len(res_df) < 25:
        return {"summary": {}, "trades": []}

    # Parse start and cutoff times
    start_h, start_m = map(int, start_time_str.split(":"))
    cutoff_h, cutoff_m = map(int, cutoff_time_str.split(":"))
    t_start = dtime(start_h, start_m)
    t_cutoff = dtime(cutoff_h, cutoff_m)
    t_squareoff = dtime(15, 0)  # Mandatory square-off at 15:00

    trades: List[Dict[str, Any]] = []
    trade_counter = 0

    # Process day by day
    for trade_date, day_bars in res_df.groupby(res_df.index.date):
        day_bars = day_bars.copy()
        if len(day_bars) < 5:
            continue

        active_trade: Optional[Dict[str, Any]] = None
        day_cross_count = 0

        bar_indices = list(range(1, len(day_bars)))
        for i in bar_indices:
            curr_bar = day_bars.iloc[i]
            prev_bar = day_bars.iloc[i - 1]
            bar_time = curr_bar.name.time()

            # Check for EMA crossover on closed bars
            prev_diff = prev_bar["ema_9"] - prev_bar["ema_21"]
            curr_diff = curr_bar["ema_9"] - curr_bar["ema_21"]

            bullish_cross = (prev_diff <= 0.0 and curr_diff > 0.0)
            bearish_cross = (prev_diff >= 0.0 and curr_diff < 0.0)

            # Mandatory square-off at 15:00
            if active_trade and bar_time >= t_squareoff:
                exit_spot = curr_bar["close"]
                exit_time = curr_bar.name
                _close_trade(active_trade, exit_time, exit_spot, "MANDATORY_1500", trades, mode)
                active_trade = None

            # Handle Crossover Signals
            if bullish_cross or bearish_cross:
                day_cross_count += 1
                new_direction = "LONG" if bullish_cross else "SHORT"

                # 1. If currently in a trade: check for opposite crossover exit
                if active_trade:
                    if active_trade["direction"] != new_direction:
                        exit_spot = curr_bar["close"]
                        exit_time = curr_bar.name
                        _close_trade(active_trade, exit_time, exit_spot, "OPPOSITE_CROSSOVER", trades, mode)
                        active_trade = None

                        # Immediate Reversal: open reverse trade if still inside entry window
                        if t_start <= bar_time <= t_cutoff:
                            trade_counter += 1
                            active_trade = _create_trade(
                                trade_counter, day_cross_count, new_direction,
                                curr_bar.name, curr_bar["close"], mode, trade_date
                            )
                else:
                    # Not in trade: check if within entry window
                    if t_start <= bar_time <= t_cutoff:
                        trade_counter += 1
                        active_trade = _create_trade(
                            trade_counter, day_cross_count, new_direction,
                            curr_bar.name, curr_bar["close"], mode, trade_date
                        )

        # End of day check: if a trade is somehow still open, force close it at last bar
        if active_trade:
            last_bar = day_bars.iloc[-1]
            _close_trade(active_trade, last_bar.name, last_bar["close"], "CUTOFF_SQUAREOFF", trades, mode)
            active_trade = None

    # Calculate summary metrics
    summary = calculate_summary_metrics(trades)

    return {
        "summary": summary,
        "trades": trades,
    }


def _create_trade(
    trade_num: int,
    cross_num: int,
    direction: str,
    entry_time: datetime,
    entry_spot: float,
    mode: str,
    trade_date: Any,
) -> Dict[str, Any]:
    """Initializes a new trade record with option parameters."""
    strike, opt_type = get_strike_for_mode(entry_spot, mode, direction)
    dte_days = 2.0  # Approx weekly DTE for standard testing

    entry_prem = black_scholes_price(
        spot=entry_spot,
        strike=strike,
        dte_days=dte_days,
        opt_type=opt_type,
    )

    return {
        "id": str(uuid.uuid4()),
        "trade_number": trade_num,
        "cross_number": cross_num,
        "direction": direction,
        "entry_time": entry_time,
        "entry_spot": entry_spot,
        "strike": strike,
        "option_type": opt_type,
        "expiry_date": (entry_time + timedelta(days=int(dte_days))).strftime("%Y-%m-%d"),
        "dte": int(dte_days),
        "entry_premium": entry_prem,
        "entry_bar_time": entry_time,
    }


def _close_trade(
    trade: Dict[str, Any],
    exit_time: datetime,
    exit_spot: float,
    exit_reason: str,
    trades_list: List[Dict[str, Any]],
    mode: str,
):
    """Calculates exit option price, friction, and appends to completed trades."""
    # Compute elapsed intraday time in days for theta decay
    minutes_elapsed = max(1, (exit_time - trade["entry_time"]).total_seconds() / 60.0)
    decay_fraction = minutes_elapsed / (375.0 * 5.0)  # Fraction of weekly time
    dte_at_exit = max(0.01, trade["dte"] - decay_fraction)

    exit_prem = black_scholes_price(
        spot=exit_spot,
        strike=trade["strike"],
        dte_days=dte_at_exit,
        opt_type=trade["option_type"],
    )

    # Cost stack calculation
    cost_data = calculate_trade_costs(
        mode=mode,
        entry_premium=trade["entry_premium"],
        exit_premium=exit_prem,
        lot_size=LOT_SIZE,
    )

    # Whipsaw detection: closed due to opposite cross within <= 30 mins at a loss
    is_whipsaw = (exit_reason == "OPPOSITE_CROSSOVER" and cost_data["net_pnl"] < 0 and minutes_elapsed <= 30)

    trade.update({
        "exit_time": exit_time,
        "exit_spot": exit_spot,
        "exit_premium": exit_prem,
        "exit_reason": exit_reason,
        "is_whipsaw": is_whipsaw,
        **cost_data,
    })

    trades_list.append(trade)


def calculate_summary_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes comprehensive performance KPIs across all trades."""
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "total_friction": 0.0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "payoff_ratio": 0.0,
            "expectancy": 0.0,
            "max_drawdown_amount": 0.0,
            "max_drawdown_pct": 0.0,
        }

    total_trades = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]

    winning_count = len(wins)
    losing_count = len(losses)
    win_rate = round((winning_count / total_trades) * 100, 2)

    gross_pnl = round(sum(t["gross_pnl"] for t in trades), 2)
    total_friction = round(sum(t["total_friction"] for t in trades), 2)
    net_pnl = round(sum(t["net_pnl"] for t in trades), 2)

    total_gain = sum(t["net_pnl"] for t in wins)
    total_loss = abs(sum(t["net_pnl"] for t in losses))

    profit_factor = round(total_gain / total_loss, 2) if total_loss > 0 else 99.99

    avg_win = total_gain / winning_count if winning_count > 0 else 0.0
    avg_loss = total_loss / losing_count if losing_count > 0 else 0.0
    payoff_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

    p_win = winning_count / total_trades
    p_loss = losing_count / total_trades
    expectancy = round((p_win * avg_win) - (p_loss * avg_loss), 2)

    # Max Drawdown calculation on cumulative equity curve
    cumulative = []
    curr = 0.0
    for t in trades:
        curr += t["net_pnl"]
        cumulative.append(curr)

    cum_series = pd.Series(cumulative)
    peak = cum_series.cummax()
    drawdown = cum_series - peak
    max_dd_amount = round(abs(drawdown.min()), 2) if not drawdown.empty else 0.0

    # Max Drawdown % based on peak initial margin reference (e.g. Rs 1,50,000 for options)
    initial_capital = 150000.0
    max_dd_pct = round((max_dd_amount / initial_capital) * 100, 2)

    return {
        "total_trades": total_trades,
        "winning_trades": winning_count,
        "losing_trades": losing_count,
        "win_rate": win_rate,
        "gross_pnl": gross_pnl,
        "total_friction": total_friction,
        "net_pnl": net_pnl,
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "expectancy": expectancy,
        "max_drawdown_amount": max_dd_amount,
        "max_drawdown_pct": max_dd_pct,
    }


def save_backtest_run(run_params: Dict[str, Any], results: Dict[str, Any]) -> str:
    """Caches backtest run and trades to database."""
    run_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        summary = results.get("summary", {})
        st_run = StrategyRun(
            id=run_id,
            timeframe=run_params.get("timeframe", "15m"),
            mode=run_params.get("mode", "ATM_BUY"),
            start_time=run_params.get("start_time", "09:30"),
            cutoff_time=run_params.get("cutoff_time", "14:30"),
            total_trades=summary.get("total_trades", 0),
            winning_trades=summary.get("winning_trades", 0),
            losing_trades=summary.get("losing_trades", 0),
            win_rate=summary.get("win_rate", 0.0),
            gross_pnl=summary.get("gross_pnl", 0.0),
            total_friction=summary.get("total_friction", 0.0),
            net_pnl=summary.get("net_pnl", 0.0),
            profit_factor=summary.get("profit_factor", 0.0),
            payoff_ratio=summary.get("payoff_ratio", 0.0),
            expectancy=summary.get("expectancy", 0.0),
            max_drawdown_amount=summary.get("max_drawdown_amount", 0.0),
            max_drawdown_pct=summary.get("max_drawdown_pct", 0.0),
        )
        db.add(st_run)

        for t in results.get("trades", []):
            db_trade = SimulatedTrade(
                id=t["id"],
                run_id=run_id,
                trade_number=t["trade_number"],
                cross_number=t.get("cross_number", 1),
                direction=t["direction"],
                entry_time=t["entry_time"],
                exit_time=t["exit_time"],
                nifty_entry=t["entry_spot"],
                nifty_exit=t["exit_spot"],
                strike=t["strike"],
                option_type=t["option_type"],
                expiry_date=t["expiry_date"],
                dte=t.get("dte", 0),
                entry_premium=t["entry_premium"],
                exit_premium=t["exit_premium"],
                gross_pnl=t["gross_pnl"],
                slippage=t["slippage"],
                brokerage=t["brokerage"],
                stt=t["stt"],
                exchange_charges=t["exchange_charges"],
                sebi_charges=t["sebi_charges"],
                stamp_duty=t["stamp_duty"],
                gst=t["gst"],
                total_friction=t["total_friction"],
                net_pnl=t["net_pnl"],
                exit_reason=t["exit_reason"],
                is_whipsaw=t.get("is_whipsaw", False),
            )
            db.add(db_trade)

        db.commit()
        return run_id
    finally:
        db.close()
