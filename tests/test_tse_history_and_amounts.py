import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from earnings_amounts import format_yen, normalize_earnings, normalize_text
from fetch_tse_history import parse_bars, extend_bars
from market_clock import JST
from tdnet_earnings import describe_number


class EarningsAmounts(unittest.TestCase):
    def test_totals_and_boundaries(self):
        for yen, expected in [(1010000000,'10.1億円'),(49000000000,'490億円'),
                              (600000000,'6億円'),(170000000,'1.7億円'),
                              (50000000,'5,000万円'),(-50000000,'-5,000万円'),
                              (-100000000,'-1億円'),(100000000,'1億円'),(99990000,'9,999万円'),(0,'0万円')]:
            self.assertEqual(format_yen(yen),expected)

    def test_cached_comparisons_prose_and_per_share(self):
        data={'highlights':[{'narrative':'取得総額0.5億円、損失△50百万円',
                            'key_numbers':[{'label':'通期 純利益','value':'1,010百万円',
                                            'comparison':'500百万円 → 1,010百万円（前回会社予想比）'},
                                           {'label':'通期 1株配当','value':'160円','comparison':'140円 → 160円'}]}]}
        out=normalize_earnings(data)['highlights'][0]
        self.assertEqual(out['narrative'],'取得総額5,000万円、損失-5,000万円')
        self.assertEqual(out['key_numbers'][0]['comparison'],'5億円 → 10.1億円（前回会社予想比）')
        self.assertEqual(out['key_numbers'][1]['comparison'],'140円 → 160円')
        self.assertEqual(data['highlights'][0]['key_numbers'][0]['value'],'1,010百万円')
        self.assertEqual(normalize_text('1株当たり配当金160円、取得総額5,000,000円'),'1株当たり配当金160円、取得総額500万円')

    def test_buyback_and_dividend(self):
        self.assertEqual(describe_number({'label':'取得上限額','unit':'円'},50000000),'5,000万円')
        self.assertEqual(describe_number({'label':'1株配当','unit':'円'},160),'160円')


class TSEHistory(unittest.TestCase):
    def test_real_ohlc_required_and_duplicates(self):
        now=dt.datetime(2026,9,27,tzinfo=JST)
        stamp=dt.datetime(2026,9,25,tzinfo=JST).timestamp()*1000
        row=[stamp,100,103,99,102]
        self.assertEqual(len(parse_bars({'ohlc_data':[row,row]},now)),1)
        for bad in [[stamp,None,103,99,102],[stamp,100,98,99,102]]:
            with self.assertRaises(ValueError):parse_bars({'ohlc_data':[bad]},now)

    def test_week_aggregation_uses_every_session(self):
        daily=[dict(t=f'2026-09-{day:02d}',o=100+i,h=105+i,l=99+i,c=102+i) for i,day in enumerate(range(7,12))]
        actual=extend_bars([],daily,'1wk')
        self.assertEqual(actual,[dict(t='2026-09-07',o=100,h=109,l=99,c=106)])
        with self.assertRaises(ValueError):extend_bars([],daily[:2]+daily[3:],'1wk')

    def test_partial_first_month_is_not_invented(self):
        daily=[dict(t='2026-09-24',o=100,h=103,l=99,c=102),dict(t='2026-09-25',o=102,h=104,l=101,c=103)]
        with self.assertRaises(ValueError):extend_bars([],daily,'1mo')


if __name__=='__main__': unittest.main()
