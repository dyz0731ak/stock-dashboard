import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_earnings_flash as earnings


class DisclosureMetricsTests(unittest.TestCase):
    def test_quarterly_statement_extracts_four_yoy_metrics(self):
        text = """
        1. 2027年3月期第1四半期の連結業績
        売上高 営業利益 経常利益 親会社株主に帰属する四半期純利益
        2027年3月期第1四半期 673,436 4.0 55,412 △11.4 49,561 △13.3 35,569 △65.0
        2026年3月期第1四半期 647,341 10.3 62,523 141.4 57,137 122.3 101,727 438.7
        """
        metrics = earnings.parse_disclosure_metrics(text, "2027年3月期第1四半期決算短信")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["type"], "実績")
        self.assertIn("+4%", metrics["sales"])
        self.assertIn("-11.4%", metrics["op"])
        self.assertIn("-65%", metrics["net"])

    def test_forecast_revision_extracts_revision_rates(self):
        text = """
        業績予想の修正に関するお知らせ
        2026年12月期第2四半期（中間期）連結業績予想数値の修正
        前回発表予想 (Ａ) 125,000 24,300 25,500 16,000 133円47銭
        今回修正予想 (Ｂ) 139,600 28,800 30,200 20,400 170円13銭
        増減額 (Ｂ－Ａ) 14,600 4,500 4,700 4,400 -
        増減率 (％) 11.7 18.5 18.4 27.5 -
        """
        metrics = earnings.parse_disclosure_metrics(text, "業績予想の修正に関するお知らせ")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["type"], "修正")
        self.assertIn("+11.7%", metrics["sales"])
        self.assertIn("+27.5%", metrics["net"])
        self.assertEqual(
            earnings._classify_metrics(metrics, "その他開示"),
            "大幅上方修正",
        )


if __name__ == "__main__":
    unittest.main()
