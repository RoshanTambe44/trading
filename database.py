import os
from datetime import datetime
from pathlib import Path
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    String,
    DateTime,
    Boolean,
    BigInteger,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config import BASE_DIR

Base = declarative_base()


class NiftyCandle1M(Base):
    """1-minute NIFTY spot index candlestick data."""

    __tablename__ = "nifty_1m_candles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, unique=True, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, default=0)

    __table_args__ = (Index("idx_candle_time", "timestamp"),)


class StockCandle1M(Base):
    """1-minute candlestick data for multi-asset / US stocks (SPY, QQQ, TSLA, AAPL, NVDA, etc.)."""

    __tablename__ = "stock_1m_candles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, default=0)

    __table_args__ = (Index("idx_stock_sym_time", "symbol", "timestamp", unique=True),)


class StrategyRun(Base):
    """Cached backtest run results and summary KPIs."""

    __tablename__ = "strategy_runs"

    id = Column(String(64), primary_key=True)
    timeframe = Column(String(10), nullable=False)  # "5m", "15m", "30m"
    mode = Column(String(30), nullable=False)  # "DEEP_ITM_BUY", "ATM_BUY", "ATM_SELL"
    start_time = Column(String(10), nullable=False)  # e.g., "09:30"
    cutoff_time = Column(String(10), nullable=False)  # e.g., "14:30"

    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)

    gross_pnl = Column(Float, default=0.0)
    total_friction = Column(Float, default=0.0)
    net_pnl = Column(Float, default=0.0)

    profit_factor = Column(Float, default=0.0)
    payoff_ratio = Column(Float, default=0.0)
    expectancy = Column(Float, default=0.0)
    max_drawdown_amount = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)

    trades = relationship("SimulatedTrade", back_populates="run", cascade="all, delete-orphan")


class SimulatedTrade(Base):
    """Individual trade generated during a backtest run."""

    __tablename__ = "simulated_trades"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("strategy_runs.id"), nullable=False, index=True)
    trade_number = Column(Integer, nullable=False)
    cross_number = Column(Integer, default=1)  # 1 for first cross of the day, 2 for second, etc.
    direction = Column(String(10), nullable=False)  # "LONG", "SHORT"

    entry_time = Column(DateTime, nullable=False)
    exit_time = Column(DateTime, nullable=False)

    nifty_entry = Column(Float, nullable=False)
    nifty_exit = Column(Float, nullable=False)

    strike = Column(Integer, nullable=False)
    option_type = Column(String(5), nullable=False)  # "CE", "PE"
    expiry_date = Column(String(20), nullable=False)
    dte = Column(Integer, default=0)

    entry_premium = Column(Float, nullable=False)
    exit_premium = Column(Float, nullable=False)

    gross_pnl = Column(Float, nullable=False)
    slippage = Column(Float, default=0.0)
    brokerage = Column(Float, default=0.0)
    stt = Column(Float, default=0.0)
    exchange_charges = Column(Float, default=0.0)
    sebi_charges = Column(Float, default=0.0)
    stamp_duty = Column(Float, default=0.0)
    gst = Column(Float, default=0.0)
    total_friction = Column(Float, default=0.0)
    net_pnl = Column(Float, nullable=False)

    exit_reason = Column(String(50), nullable=False)  # "OPPOSITE_CROSSOVER", "CUTOFF_SQUAREOFF", "MANDATORY_1500"
    is_whipsaw = Column(Boolean, default=False)

    run = relationship("StrategyRun", back_populates="trades")


# Database URL config
def get_engine():
    pg_url = os.getenv("POSTGRES_URL")
    if pg_url:
        try:
            eng = create_engine(pg_url, pool_pre_ping=True)
            with eng.connect():
                pass
            return eng
        except Exception as e:
            print(f"[Database] Could not connect to Postgres URL ({e}). Falling back to SQLite.")

    # SQLite fallback
    sqlite_path = BASE_DIR / "nifty_trading.db"
    return create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initializes tables in database."""
    Base.metadata.create_all(bind=engine)
    print(f"[Database] Initialized tables successfully with engine: {engine.url}")
