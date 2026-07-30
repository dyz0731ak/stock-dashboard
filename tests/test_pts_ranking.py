import datetime
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_pts_ranking as pts


SAMPLE_HTML = """
<html><body>
<p>株価：2026年07月30日 17:58現在</p>
<table>
  <tr><th>銘柄</th><th>通常取引 30日終値</th><th>PTS株価</th>
      <th>通常取引 30日終値比</th><th>出来高</th></tr>
  <tr>
    <th><a href="/stocks/2737/"><p><abbr title="トーメンデバイス">トーメンデバ</abbr></p>
        <div>2737 <span>東P</span></div></a></th>
    <td>17,150</td><td>21,150</td>
    <td><span>+4,000</span><br><span>+23.32<span>%</span></span></td>
    <td>1,200 <span>株</span></td>
  </tr>
</table>
</body></html>
"""


class PtsRankingTests(unittest.TestCase):
    def test_parse_live_ranking(self):
        session_date, as_of, stocks = pts.parse_kabutan_live(SAMPLE_HTML)

        self.assertEqual(session_date, "2026-07-30")
        self.assertEqual(as_of, "2026-07-30T17:58:00+09:00")
        self.assertEqual(len(stocks), 1)
        self.assertEqual(stocks[0]["code"], "2737")
        self.assertEqual(stocks[0]["name"], "トーメンデバイス")
        self.assertEqual(stocks[0]["market_tse"], "東P")
        self.assertEqual(stocks[0]["price"], 21150)
        self.assertEqual(stocks[0]["reference_price"], 17150)
        self.assertEqual(stocks[0]["change_pct"], 23.32)
        self.assertEqual(stocks[0]["volume"], 1200)

    def test_active_session_date_evening(self):
        now = datetime.datetime(2026, 7, 30, 18, 10, tzinfo=pts.JST)
        self.assertEqual(
            pts.active_night_session_date(now),
            datetime.date(2026, 7, 30),
        )

    def test_active_session_date_after_midnight(self):
        now = datetime.datetime(2026, 7, 31, 2, 0, tzinfo=pts.JST)
        self.assertEqual(
            pts.active_night_session_date(now),
            datetime.date(2026, 7, 30),
        )

    def test_outside_session(self):
        now = datetime.datetime(2026, 7, 30, 12, 0, tzinfo=pts.JST)
        self.assertIsNone(pts.active_night_session_date(now))


if __name__ == "__main__":
    unittest.main()
