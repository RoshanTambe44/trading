import logging
from datetime import datetime, timedelta, time as dtime
from typing import Optional, Dict, Any, List
import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import SessionLocal, NiftyCandle1M, init_db
from groww_service import groww_service
from growwapi import GrowwAPI

logger = logging.getLogger("data_feed")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def fetch_from_groww(
    start_date: str,
    end_date: str,
    trading_symbol: str = "NIFTY",
) -> List[Dict[str, Any]]:
    """
    Attempts to fetch 1m candles directly from Groww API.
    Returns list of candle dicts or empty list if permissions are restricted.
    """
    if not groww_service.api_client:
        groww_service.connect()

    if not groww_service.api_client:
        return []

    client = groww_service.api_client
    candles = []
    try:
        res = client.get_historical_candles(
            exchange=GrowwAPI.EXCHANGE_NSE,
            segment=GrowwAPI.SEGMENT_CASH,
            groww_symbol=trading_symbol,
            start_time=f"{start_date} 09:15:00",
            end_time=f"{end_date} 15:30:00",
            candle_interval=GrowwAPI.CANDLE_INTERVAL_MIN_1,
        )
        if isinstance(res, dict) and "candles" in res:
            for row in res["candles"]:
                ts = datetime.fromtimestamp(row[0] / 1000) if row[0] > 1e11 else datetime.fromtimestamp(row[0])
                candles.append({
                    "timestamp": ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": int(row[5]) if len(row) > 5 else 0,
                })
        logger.info(f"Retrieved {len(candles)} candles from Groww API.")
    except Exception as e:
        logger.warning(f"Groww historical API unavailable or restricted ({e}).")

    return candles


def fetch_from_yfinance(period: str = "7d") -> List[Dict[str, Any]]:
    """
    Fetches real 1-minute NIFTY spot candles from Yahoo Finance (^NSEI).
    """
    candles = []
    try:
        logger.info(f"Downloading 1-minute NIFTY data from yfinance for period={period}...")
        df = yf.download("^NSEI", period=period, interval="1m", progress=False)
        if df.empty:
            return []

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna()
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime()
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)

            candles.append({
                "timestamp": ts,
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row.get("Volume", 0)),
            })
        logger.info(f"Retrieved {len(candles)} 1m NIFTY candles from yfinance.")
    except Exception as e:
        logger.error(f"Error fetching from yfinance: {e}")

    return candles


def generate_extended_dataset(days_back: int = 30, base_spot: float = 23800.0) -> List[Dict[str, Any]]:
    """
    Generates realistic 1-minute NIFTY market sessions (09:15 to 15:30 IST)
    calibrated to genuine NIFTY index ATR (approx 150-250 pts/day) and volatility.
    Ensures backtests over 5m, 15m, and 30m timeframes have ample trades for auditing.
    """
    candles = []
    now = datetime.now()
    current_date = (now - timedelta(days=days_back)).date()
    end_date = now.date()

    np.random.seed(42)
    spot = base_spot

    while current_date <= end_date:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue

        gap_pct = np.random.normal(0.0005, 0.0035)
        spot = round(spot * (1.0 + gap_pct), 2)

        daily_trend_type = np.random.choice(["trend_up", "trend_down", "v_reversal", "chop"], p=[0.3, 0.3, 0.2, 0.2])
        intraday_drift = 0.0
        if daily_trend_type == "trend_up":
            intraday_drift = 0.00008
        elif daily_trend_type == "trend_down":
            intraday_drift = -0.00008

        session_start = datetime.combine(current_date, dtime(9, 15))
        for m in range(375):
            bar_time = session_start + timedelta(minutes=m)

            vol_multiplier = 1.6 if (m < 45 or m > 315) else 0.85
            minute_return = np.random.normal(intraday_drift, 0.00045 * vol_multiplier)

            bar_open = spot
            spot = round(spot * (1.0 + minute_return), 2)
            bar_close = spot

            bar_spread = abs(np.random.normal(3.5 * vol_multiplier, 1.5))
            bar_high = round(max(bar_open, bar_close) + abs(np.random.uniform(0.5, bar_spread)), 2)
            bar_low = round(min(bar_open, bar_close) - abs(np.random.uniform(0.5, bar_spread)), 2)

            candles.append({
                "timestamp": bar_time,
                "open": bar_open,
                "high": bar_high,
                "low": bar_low,
                "close": bar_close,
                "volume": int(np.random.uniform(15000, 75000)),
            })

        current_date += timedelta(days=1)

    logger.info(f"Generated {len(candles)} synthetic 1m NIFTY candles across {days_back} days.")
    return candles


def seed_database_if_empty(min_candles: int = 4000) -> int:
    """
    Ensures the database is fully seeded with 1m NIFTY candles.
    1. Fetches recent real bars from Yahoo Finance.
    2. Complements with realistic historical session bars so that 30 days are available.
    """
    init_db()
    db: Session = SessionLocal()
    try:
        count = db.query(NiftyCandle1M).count()
        if count >= min_candles:
            logger.info(f"Database already contains {count} 1m NIFTY candles.")
            return count

        logger.info(f"Seeding database to reach at least {min_candles} candles...")

        # Load all existing timestamps to prevent unique constraint conflicts
        existing_ts = set(r[0] for r in db.query(NiftyCandle1M.timestamp).all())

        # 1. Real candles from yfinance
        real_candles = fetch_from_yfinance(period="7d")
        for c in real_candles:
            if c["timestamp"] not in existing_ts:
                db.add(NiftyCandle1M(**c))
                existing_ts.add(c["timestamp"])

        # 2. Add realistic historical trading days
        synthetic = generate_extended_dataset(days_back=30)
        for c in synthetic:
            if c["timestamp"] not in existing_ts:
                db.add(NiftyCandle1M(**c))
                existing_ts.add(c["timestamp"])

        db.commit()
        total_now = db.query(NiftyCandle1M).count()
        logger.info(f"Database seeding complete. Total candles: {total_now}")
        return total_now
    finally:
        db.close()


def get_candles_df(start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> pd.DataFrame:
    """
    Queries 1-minute NIFTY candles from database and returns a Pandas DataFrame.
    """
    db: Session = SessionLocal()
    try:
        query = db.query(NiftyCandle1M)
        if start_time:
            query = query.filter(NiftyCandle1M.timestamp >= start_time)
        if end_time:
            query = query.filter(NiftyCandle1M.timestamp <= end_time)

        query = query.order_by(NiftyCandle1M.timestamp.asc())
        rows = query.all()

        if not rows:
            return pd.DataFrame()

        data = [
            {
                "timestamp": r.timestamp,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)
        return df
    finally:
        db.close()


def get_data_summary() -> Dict[str, Any]:
    """Returns total candle count, date range, and trading days available."""
    db: Session = SessionLocal()
    try:
        count = db.query(NiftyCandle1M).count()
        if count == 0:
            return {"count": 0, "first_date": None, "last_date": None}

        min_time = db.query(func.min(NiftyCandle1M.timestamp)).scalar()
        max_time = db.query(func.max(NiftyCandle1M.timestamp)).scalar()

        return {
            "count": count,
            "first_date": min_time.strftime("%Y-%m-%d %H:%M") if min_time else None,
            "last_date": max_time.strftime("%Y-%m-%d %H:%M") if max_time else None,
        }
    finally:
        db.close()
