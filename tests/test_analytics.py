import unittest

import pandas as pd

from smart_money.analytics import backtest_patterns, detect_latest_patterns, enrich_market_data


def sample_history() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=4, freq="B")
    return pd.DataFrame({
        "InsCode": ["123456789"] * 4,
        "Symbol": ["آزمایشی"] * 4,
        "Date": dates,
        "ClosePrice": [100.0, 99.0, 98.5, 98.7],
        "PreviousClose": [100.0, 100.0, 99.0, 98.5],
        "OpenPrice": [100.0, 99.0, 98.5, 98.6],
        "HighPrice": [101.0, 100.0, 99.0, 99.0],
        "LowPrice": [99.0, 98.0, 98.0, 98.2],
        "TotalVolume": [1000.0] * 4,
        "LegalBuyVolume": [100.0] * 4,
        "LegalSellVolume": [10.0] * 4,
        "LegalBuyValue": [10000.0] * 4,
        "LegalSellValue": [1000.0] * 4,
        "RetailBuyVolume": [900.0] * 4,
        "RetailSellVolume": [900.0] * 4,
        "ClientDataAvailable": [True] * 4,
    })


class AnalyticsTests(unittest.TestCase):
    def test_legal_net_flow_and_shares(self):
        result = enrich_market_data(sample_history())
        self.assertAlmostEqual(result.iloc[-1]["NetLegalVolume"], 90.0)
        self.assertAlmostEqual(result.iloc[-1]["NetLegalPctVolume"], 9.0)
        self.assertAlmostEqual(result.iloc[-1]["LegalBuySharePct"], 10.0)

    def test_latest_accumulation_pattern_is_detected(self):
        result = detect_latest_patterns(sample_history())
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["Type"], "ACCUMULATION")
        self.assertGreater(result.iloc[0]["Score"], 0)

    def test_missing_client_data_does_not_create_signal(self):
        history = sample_history()
        history.loc[3, "ClientDataAvailable"] = False
        result = detect_latest_patterns(history)
        self.assertTrue(result.empty)

    def test_backtest_uses_next_trading_session(self):
        result = backtest_patterns(sample_history(), horizons=(1,))
        accumulation = result[result["Type"] == "ACCUMULATION"]
        self.assertEqual(int(accumulation.iloc[0]["Samples"]), 1)
        self.assertGreater(float(accumulation.iloc[0]["SuccessRatePct"]), 0)


if __name__ == "__main__":
    unittest.main()
