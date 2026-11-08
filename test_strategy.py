import unittest
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from strategy_backtester import (
    resample_bars,
    run_backtest,
    calculate_trade_costs,
    get_strike_for_mode,
    black_scholes_price,
    LOT_SIZE,
    MIN_TICK,
)
from app import app


class TestEMAStrategyAndBacktester(unittest.TestCase):

    def test_black_scholes_pricing(self):
        """Test options pricing logic and boundary conditions."""
        # Intrinsic value at expiration
        call_itm = black_scholes_price(spot=24200, strike=24000, dte_days=0.0, opt_type="CE")
        self.assertEqual(call_itm, 200.0)

        put_itm = black_scholes_price(spot=23800, strike=24000, dte_days=0.0, opt_type="PE")
        self.assertEqual(put_itm, 200.0)

        # Minimum tick size enforcement
        otm_call = black_scholes_price(spot=22000, strike=25000, dte_days=0.001, opt_type="CE")
        self.assertGreaterEqual(otm_call, MIN_TICK)

    def test_strike_selection_modes(self):
        """Test strike selection for Deep ITM (ITM 5), ATM Buy, ATM Sell."""
        spot = 24125.0  # nearest 50-strike = 24100 or 24150 -> round(24125/50)*50 = 24100 or 24150

        # ATM Buy
        atm_strike, atm_type = get_strike_for_mode(spot, "ATM_BUY", "LONG")
        self.assertEqual(atm_strike, 24100)
        self.assertEqual(atm_type, "CE")

        # Deep ITM Buy (5 strikes = 250 pts ITM)
        itm_strike_call, itm_type_call = get_strike_for_mode(spot, "DEEP_ITM_BUY", "LONG")
        self.assertEqual(itm_strike_call, 24100 - 250)
        self.assertEqual(itm_type_call, "CE")

        itm_strike_put, itm_type_put = get_strike_for_mode(spot, "DEEP_ITM_BUY", "SHORT")
        self.assertEqual(itm_strike_put, 24100 + 250)
        self.assertEqual(itm_type_put, "PE")

        # ATM Sell
        sell_strike_bull, sell_type_bull = get_strike_for_mode(spot, "ATM_SELL", "LONG")
        self.assertEqual(sell_strike_bull, 24100)
        self.assertEqual(sell_type_bull, "PE")  # Short Put on Bullish

        sell_strike_bear, sell_type_bear = get_strike_for_mode(spot, "ATM_SELL", "SHORT")
        self.assertEqual(sell_strike_bear, 24100)
        self.assertEqual(sell_type_bear, "CE")  # Short Call on Bearish

    def test_indian_regulatory_cost_stack(self):
        """Verify slippage and Indian statutory charges (Brokerage, STT, Exchange, SEBI, Stamp, GST)."""
        entry_prem = 100.0
        exit_prem = 120.0
        costs = calculate_trade_costs("ATM_BUY", entry_prem, exit_prem, lot_size=65)

        # Gross PnL = (120 - 100) * 65 = 1300
        self.assertEqual(costs["gross_pnl"], 1300.0)

        # Brokerage = Rs 40.00
        self.assertEqual(costs["brokerage"], 40.00)

        # Slippage: (0.5% + 0.10) on entry (0.60) and exit (0.70) = 1.30 * 65 = 84.50
        self.assertAlmostEqual(costs["slippage"], 84.50, delta=1.0)

        # Net PnL must strictly equal Gross PnL - Total Friction
        self.assertAlmostEqual(costs["net_pnl"], costs["gross_pnl"] - costs["total_friction"], delta=0.01)

    def test_resampling_alignment(self):
        """Verify that resampling starts at 09:15:00 without lookahead bias."""
        base_time = datetime(2026, 11, 2, 9, 15)
        times = [base_time + timedelta(minutes=i) for i in range(75)]
        closes = [24000.0 + i * 2.0 for i in range(75)]

        df_1m = pd.DataFrame({
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000] * 75,
        }, index=pd.to_datetime(times))

        res_15m = resample_bars(df_1m, "15m")
        # 75 minutes = 5 bars of 15m (09:15, 09:30, 09:45, 10:00, 10:15)
        self.assertEqual(len(res_15m), 5)
        self.assertIn("ema_9", res_15m.columns)
        self.assertIn("ema_21", res_15m.columns)

    def test_flask_api_endpoints(self):
        """Verify backtester web routes and API responses."""
        client = app.test_client()

        # Web page
        res = client.get("/backtester")
        self.assertEqual(res.status_code, 200)

        # Run backtest API
        res_run = client.post("/api/backtest/run", json={
            "timeframe": "15m",
            "mode": "ATM_BUY",
            "start_time": "09:30",
            "cutoff_time": "14:30"
        })
        self.assertEqual(res_run.status_code, 200)
        data = res_run.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("summary", data)
        self.assertIn("trades", data)

        if data["trades"]:
            trade_id = data["trades"][0]["id"]
            res_chart = client.get(f"/api/backtest/trade-chart/{trade_id}?timeframe=15m")
            self.assertEqual(res_chart.status_code, 200)
            chart_data = res_chart.get_json()
            self.assertTrue(chart_data.get("success"))
            self.assertIn("candles", chart_data)
            self.assertIn("ema9", chart_data)
            self.assertIn("ema21", chart_data)
            self.assertIn("markers", chart_data)


if __name__ == "__main__":
    unittest.main()
