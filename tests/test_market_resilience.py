import datetime as dt
import io
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import zipfile

import pandas as pd
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from market_clock import JST
from market_index_specs import MARKET_INDICES
from fetch_market_indices import parse_yahoo, merge_cached
from fetch_market_history import parse_bars, months_before
from market_http import get
from tdnet_earnings import parse_list, parse_xbrl, parse_buyback, select_impact, relevant

NOW=dt.datetime(2026,9,25,14,tzinfo=JST)


class MarketResilienceTests(unittest.TestCase):
    def test_yfinance_timestamp_and_currency_alias(self):
        spec=MARKET_INDICES[3]
        history=pd.DataFrame({'Close':[150,151]},index=pd.to_datetime(['2026-09-24','2026-09-25']))
        meta=dict(symbol='USDJPY=X',instrumentType='CURRENCY',regularMarketTime=pd.Timestamp(NOW),
                  regularMarketPrice=151,exchangeTimezoneName='Asia/Tokyo')
        row=parse_yahoo(spec,history,meta,NOW)
        self.assertEqual(row['prev_close'],150)
        self.assertEqual(row['as_of'],NOW.isoformat())

    def test_cache_preserves_source_time_and_expires_after_24h(self):
        old=dict(MARKET_INDICES[0],price=123,fetched_at=(NOW-dt.timedelta(hours=9)).isoformat(),as_of='original')
        failures=[(None,dict(id=s['id'],error='429')) for s in MARKET_INDICES]
        rows,_=merge_cached(failures,{'items':[old]},NOW)
        self.assertEqual(rows[0]['fetched_at'],old['fetched_at'])
        self.assertEqual(rows[0]['as_of'],'original')
        self.assertEqual(rows[0]['cache_status'],'previous')
        self.assertFalse(merge_cached(failures,{'items':[old]},NOW+dt.timedelta(hours=16))[0])

    def test_cash_cache_rejects_futures(self):
        old=dict(MARKET_INDICES[0],ticker='NIY=F',price=123,fetched_at=NOW.isoformat())
        failures=[(None,dict(id=s['id'],error='timeout')) for s in MARKET_INDICES]
        self.assertFalse(merge_cached(failures,{'items':[old]},NOW)[0])

    @patch('market_http.time.sleep')
    @patch('market_http.requests.get')
    def test_retry_transient_and_honor_long_rate_limit(self,request,sleep):
        response=Mock(status_code=429,headers={'Retry-After':'30'})
        response.raise_for_status.side_effect=requests.HTTPError('rate limited',response=response)
        request.return_value=response
        with self.assertRaises(requests.HTTPError):get('https://example.test')
        self.assertEqual(request.call_count,1)
        sleep.assert_not_called()
        request.reset_mock();request.side_effect=[requests.Timeout('timeout'),Mock()]
        get('https://example.test')
        self.assertEqual(request.call_count,2)
        sleep.assert_called_once()

    def test_history_never_synthesizes_missing_ohlc(self):
        times=[int((NOW-dt.timedelta(days=i)).timestamp()) for i in range(249,-1,-1)]
        q={'open':[100]*250,'high':[110]*250,'low':[90]*250,'close':[105]*250}
        q['open'][1]=None
        q['high'][2]=101
        r=dict(meta=dict(symbol='^DJI',instrumentType='INDEX',exchangeTimezoneName='America/New_York'),timestamp=times,indicators={'quote':[q]})
        rows=parse_bars(r,MARKET_INDICES[1],NOW)
        self.assertEqual(len(rows),248)
        r['meta']['instrumentType']='FUTURE'
        with self.assertRaises(ValueError):parse_bars(r,MARKET_INDICES[1],NOW)

    def test_calendar_month_cutoff(self):
        self.assertEqual(months_before(dt.date(2024,3,31),1),dt.date(2024,2,29))


class TdnetTests(unittest.TestCase):
    def test_small_list_and_new_alphanumeric_code(self):
        html='''<div id="kaiji-date-1">2026年09月25日</div><table><tr><td class="kjTime">15:30</td><td class="kjCode">428A0</td><td class="kjName">Ｇ－会社</td><td class="kjTitle"><a href="1401.pdf">業績予想の修正</a></td><td class="kjXbrl"></td></tr></table>'''
        rows,_=parse_list(html,'2026-09-25')
        self.assertEqual(rows[0]['code'],'428A')
        with self.assertRaises(ValueError):parse_list(html,'2026-09-26')

    def test_new_buyback_included_but_monthly_progress_excluded(self):
        self.assertTrue(relevant('自己株式取得に係る事項の決定に関するお知らせ'))
        self.assertFalse(relevant('自己株式の取得状況及び取得終了に関するお知らせ'))
        rows=parse_buyback('取得する株式の総数 200,000株（上限）\n発行済株式総数（自己株式を除く）に対する割合3.52％\n株式の取得価額の総額400,000,000円（上限）')
        self.assertEqual({r['label']:r['current'] for r in rows},{'取得上限額':400000000,'取得上限株数':200000,'発行済株式比':3.52})

    def xbrl(self,facts):
        entries=''.join(f'<ix:nonFraction name="tse:{name}" contextRef="{ctx}" scale="{scale}" {sign}>{value}</ix:nonFraction>' for name,ctx,value,scale,sign in facts)
        html=f'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:tse="urn:tse"><body>{entries}</body></html>'
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr('summary-ixbrl.htm',html)
        return parse_xbrl(buffer.getvalue())[0]

    def test_banks_consolidation_units_and_revised_dividend(self):
        facts=[]
        for member in ['ConsolidatedMember','NonConsolidatedMember']:
            for version,value in [('PreviousMember','26,000'),('CurrentMember','29,600' if member=='ConsolidatedMember' else '29,200')]:
                facts.append(('OrdinaryIncome',f'CurrentYearDuration_{member}_{version}_ForecastMember',value,6,''))
        for part,old,new in [('SecondQuarterMember',100,100),('YearEndMember',18,22)]:
            for version,value in [('PreviousMember',old),('CurrentMember',new)]:
                facts.append(('DividendPerShare',f'CurrentYearDuration_{part}_NonConsolidatedMember_{version}_ForecastMember',value,0,''))
        rows=self.xbrl(facts)
        profit=next(r for r in rows if r['label']=='経常利益')
        self.assertEqual(profit['current'],29600000000)
        dividend=next(r for r in rows if r['label']=='1株配当')
        self.assertEqual((dividend['period'],dividend['previous'],dividend['current']),('期末',18,22))

    def test_turnaround_and_negative_surprises_are_ranked(self):
        base=dict(code='1000',title='業績予想修正',document_url='https://example.test/a.pdf',published_date='2026-09-25',time='15:30')
        c=dict(label='純利益',current=-200e6,previous=100e6,pct=-300,basis='前回会社予想比',period='通期',unit='百万円')
        item=select_impact(base,[c],[])
        self.assertEqual(item['impact_zone'],'negative')
        self.assertIn('赤字転落',item['impact_summary'])
        self.assertNotIn('市場予想比',item['impact_summary'])
        c.update(current=110e6,pct=10,basis='前年同期比')
        self.assertIsNone(select_impact(base,[c],[]))


if __name__=='__main__':unittest.main()
