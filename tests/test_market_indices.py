import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from market_clock import JST
from market_index_specs import MARKET_INDICES, TSE_INDICES
from fetch_market_indices import parse_yahoo, parse_gold
from fetch_tse_indices import parse_jpx
import prerender


NOW = dt.datetime(2026, 9, 25, 14, 0, tzinfo=JST)


class MarketIndicesTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame({'Close': [100, 110, float('nan')]},
                            index=pd.to_datetime(['2026-09-23', '2026-09-24', '2026-09-25']).tz_localize('Asia/Tokyo'))

    def metadata(self):
        return dict(symbol='^N225', instrumentType='INDEX', regularMarketTime=NOW.timestamp(),
                    regularMarketPrice=121, exchangeTimezoneName='Asia/Tokyo')

    def jpx(self):
        return {'TseMarketType': {spec['ticker']: dict(marketName=spec['label'], currentPrice='1,010.00',
                      previousDayComparison='10.00', previousDayRatio='1.00') for spec in TSE_INDICES}}

    def test_current_cash_quote_uses_previous_session_and_skips_nan(self):
        item = parse_yahoo(MARKET_INDICES[0], self.history(), self.metadata(), NOW)
        self.assertEqual(item['prev_close'], 110)
        self.assertEqual(item['price'], 121)
        self.assertEqual(item['pct'], 10)
        self.assertEqual(item['chart'][-1], {'t': '2026-09-25', 'c': 121})

    def test_futures_payload_cannot_be_relabelled_as_cash_index(self):
        metadata = dict(self.metadata(), instrumentType='FUTURE')
        with self.assertRaises(ValueError):
            parse_yahoo(MARKET_INDICES[0], self.history(), metadata, NOW)

    def test_old_and_future_quotes_rejected(self):
        for offset in [dt.timedelta(days=-7), dt.timedelta(hours=1)]:
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                parse_yahoo(MARKET_INDICES[0], self.history(),
                            dict(self.metadata(), regularMarketTime=(NOW+offset).timestamp()), NOW)

    def test_full_market_growth_is_not_growth_250(self):
        payload = self.jpx()
        payload['TseMarketType']['TseGrowthMarketIndex']['marketName'] = '東証グロース市場250指数'
        items, failures = parse_jpx(payload, '202609251359', NOW)
        self.assertEqual(len(items), 2)
        self.assertEqual(failures[0]['id'], 'tse-growth')

    def test_jpx_correct_group_and_daily_change(self):
        items, failures = parse_jpx(self.jpx(), '202609251359', NOW)
        self.assertFalse(failures)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]['prev_close'], 1000)
        self.assertEqual(items[0]['as_of'], '2026-09-25T13:59:00+09:00')

    def test_jpx_stale_snapshot_does_not_get_fresh_fetch_timestamp(self):
        for stamp in ['202609241659', '202609251200']:
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                parse_jpx(self.jpx(), stamp, NOW)

    def test_gold_spot_without_previous_close_is_not_zero_percent(self):
        item = parse_gold(dict(symbol='XAU', currency='USD', price=4200, updatedAt=NOW.isoformat()), NOW)
        self.assertIsNone(item['pct'])
        self.assertIsNone(item['change'])
        self.assertEqual(item['chart'], [])
        self.assertEqual(item['unit'], 'USD / トロイオンス')
        self.assertEqual(item['instrument_type'], 'SPOT')

    def test_gold_wrong_currency_stale_and_nonfinite_are_rejected(self):
        valid = dict(symbol='XAU', currency='USD', price=4200, updatedAt=NOW.isoformat())
        for changes in [dict(currency='JPY'), dict(price=float('nan')),
                        dict(updatedAt=(NOW-dt.timedelta(hours=4)).isoformat())]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_gold(dict(valid, **changes), NOW)

    def test_renderer_retains_nine_slots_and_hides_stale_or_legacy_values(self):
        # Check mixed fresh and expired rows at the same rendering time.
        current = dt.datetime.now(JST)
        item = parse_gold(dict(symbol='XAU', currency='USD', price=4321.25, updatedAt=current.isoformat()), current)
        data = dict(items=[item], fetched_at=current.isoformat(), updated_at=current.isoformat())
        html = prerender.build_idx(data)
        self.assertEqual(html.count('class="idx-card'), 6)
        self.assertIn('4,321.25', html)
        self.assertNotIn('0.00%', html)
        self.assertEqual(prerender.build_idx(None, TSE_INDICES).count('class="idx-card'), 3)
        expired = copy.deepcopy(data)
        expired['items'][0]['valid_until'] = (current-dt.timedelta(minutes=1)).isoformat()
        self.assertNotIn('4,321.25', prerender.build_idx(expired))
        legacy = dict(data, items=[dict(MARKET_INDICES[0], ticker='NIY=F', price=99999,
                                       fetched_at=current.isoformat())])
        self.assertNotIn('99,999', prerender.build_idx(legacy))


if __name__ == '__main__':
    unittest.main()
