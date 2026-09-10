import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_clock as mc
import data_status as ds
import safe_save as ss
import fetch_japan_stocks as jp
import fetch_pts_ranking as pts
import prerender as pr
import run_fetch

@contextlib.contextmanager
def directory():
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as path:
        os.chdir(path)
        try: yield Path(path)
        finally: os.chdir(old)

def now(s): return dt.datetime.fromisoformat(s).replace(tzinfo=mc.JST)

class MarketClockTests(unittest.TestCase):
    def test_cash_market_boundaries(self):
        for t,state in [('08:59','preopen'),('09:00','open'),('11:30','lunch'),('12:30','open'),('15:30','closed')]:
            self.assertEqual(mc.market_context('tse',now('2026-09-10T'+t))['state'],state)
    def test_silver_week_and_substitute_holiday(self):
        for date in ['2026-09-21','2026-09-22','2026-09-23','2026-05-06','2026-12-31','2027-01-01']:
            self.assertFalse(mc.business_day(dt.date.fromisoformat(date)))
        self.assertEqual(mc.market_context('tse',now('2026-09-23T14:00'))['session_date'],'2026-09-18')
    def test_friday_night_saturday_and_sunday(self):
        self.assertEqual(pts.active_night_session_date(now('2026-09-12T05:59')),dt.date(2026,9,11))
        for stamp in ['2026-09-12T06:00','2026-09-12T18:00','2026-09-13T02:00','2026-09-21T18:00','2026-09-11T16:59']:
            self.assertIsNone(pts.active_night_session_date(now(stamp)))
        self.assertEqual(pts.active_night_session_date(now('2026-09-11T17:00')),dt.date(2026,9,11))
    def test_ended_cash_session_survives_weekend(self):
        end=mc.session_valid_until('2026-09-18','tse','2026-09-18T16:00:00+09:00',now=now('2026-09-20T13:00'))
        self.assertEqual(end,'2026-09-24T09:30:00+09:00')
    def test_intraday_snapshot_expires_even_on_weekend(self):
        end=mc.session_valid_until('2026-09-18','tse','2026-09-18T14:00:00+09:00',now=now('2026-09-20T13:00'))
        self.assertEqual(end,'2026-09-18T15:00:00+09:00')
    def test_source_date_not_fetch_date(self):
        d={'updated_at':'2026-09-10T18:00:00+09:00','session_date':'2026-09-03'}
        ds.stamp_data('japan_stocks.json',d,now('2026-09-10T18:00'))
        self.assertFalse(ds.is_fresh(d,36,now('2026-09-10T18:01')))
    def test_delayed_pts_snapshot_expires(self):
        until=mc.session_valid_until('2026-09-10','pts','2026-09-10T23:59:00+09:00','2026-09-10T20:00:00+09:00',now('2026-09-10T23:59'))
        self.assertEqual(until,'2026-09-10T21:00:00+09:00')

class SaveTests(unittest.TestCase):
    def test_ten_row_fallback_replaces_thirty(self):
        with directory():
            ss._write_json_atomic('data/test.json',{'updated_at':'2026-09-03T00:00:00+09:00','all_stocks':[{}]*30})
            self.assertTrue(ss.safe_save('data/test.json',{'updated_at':dt.datetime.now(mc.JST).isoformat(),'all_stocks':[{}]*10,'fetch_status':'fallback'},lambda d:len(d['all_stocks'])))
            self.assertEqual(len(ss._load_existing('data/test.json')['all_stocks']),10)
    def test_empty_failure_preserves_time_and_payload(self):
        with directory():
            ss._write_json_atomic('data/test.json',{'updated_at':'old','items':[{'code':'1234'}]})
            self.assertFalse(ss.safe_save('data/test.json',{'updated_at':'new','items':[]},lambda d:len(d['items']),failure_reason='HTTP 503 source=x'))
            saved=ss._load_existing('data/test.json')
            self.assertEqual(saved['updated_at'],'old');self.assertEqual(saved['items'],[{'code':'1234'}]);self.assertEqual(saved['fetch_status'],'stale');self.assertIn('503',saved['fetch_error'])
    def test_first_failure_has_no_success_time(self):
        with directory():
            ss.safe_save('data/test.json',{'updated_at':'now','items':[]},lambda d:len(d['items']))
            self.assertNotIn('updated_at',ss._load_existing('data/test.json'))
    def test_nan_does_not_destroy_existing(self):
        with directory():
            ss._write_json_atomic('data/test.json',{'items':[1],'updated_at':'old'})
            self.assertFalse(ss.safe_save('data/test.json',{'items':[float('nan')]},lambda d:len(d['items'])))
            self.assertEqual(ss._load_existing('data/test.json')['items'],[1])

class SourceTests(unittest.TestCase):
    def test_rakuten_both_locales(self):
        jp_time=jp.parse_rakuten_timestamp('<div class="rankingBox">26/09/11 00:43</div>')
        en_time=jp.parse_rakuten_timestamp('<div class="rankingBox">Thu Sep 10 15:43:00 GMT 2026</div>')
        self.assertEqual(jp_time,en_time)
    def test_all_old_heatmap_values_are_rejected(self):
        data={'updated_at':'2026-09-10T18:00:00+09:00','items':[{'price_date':'2026-09-09','price':123}]}
        ds.stamp_data('nikkei225.json',data,now('2026-09-10T18:00'))
        self.assertEqual(data['fetch_status'],'stale');self.assertEqual(data['items'],[])
    def test_partial_heatmap_keeps_only_current_values(self):
        data={'updated_at':'2026-09-10T18:00:00+09:00','items':[{'price_date':'2026-09-09','price':1},{'price_date':'2026-09-10','price':2}]}
        ds.stamp_data('nikkei225.json',data,now('2026-09-10T18:00'))
        self.assertEqual(data['fetch_status'],'partial');self.assertEqual(len(data['items']),1);self.assertEqual(data['items'][0]['price'],2)
    def test_jpx_xlsx_discovery_and_host_validation(self):
        text='<a href="https://example.com/data_j.xlsx">bad</a><a href="/new/data_j.xlsx">current</a>'
        self.assertEqual(jp.discover_master_url(text),'https://www.jpx.co.jp/new/data_j.xlsx')
        with self.assertRaises(ValueError): jp.discover_master_url('<a href="https://example.com/data_j.xls">bad</a>')
    def test_xlsx_reader(self):
        import pandas as pd
        frame=pd.DataFrame([{'コード':str(i),'銘柄名':'銘柄','市場・商品区分':'プライム（内国株式）','33業種区分':'情報・通信業'} for i in range(1000,4000)])
        buf=io.BytesIO();frame.to_excel(buf,index=False)
        self.assertEqual(len(jp.parse_master(buf.getvalue())),3000)
    def test_small_master_rejected(self):
        import pandas as pd
        frame=pd.DataFrame([{'コード':'1234','銘柄名':'銘柄','市場・商品区分':'プライム（内国株式）','33業種区分':'情報・通信業'}])
        buf=io.BytesIO();frame.to_excel(buf,index=False)
        with self.assertRaises(ValueError): jp.parse_master(buf.getvalue())
    def test_master_404_uses_bounded_cache(self):
        with directory():
            cache={'fetched_at':(dt.datetime.now(mc.JST)-dt.timedelta(days=2)).isoformat(),'stocks':[{}]*3000}
            ss._write_json_atomic(jp.MASTER_CACHE,cache)
            with patch.object(jp.SESSION,'get',side_effect=RuntimeError('HTTP 404')):
                self.assertEqual(len(jp.fetch_jpx_listed_stocks()),3000)
            cache['fetched_at']=(dt.datetime.now(mc.JST)-dt.timedelta(days=45)).isoformat();ss._write_json_atomic(jp.MASTER_CACHE,cache)
            with patch.object(jp.SESSION,'get',side_effect=RuntimeError('HTTP 404')):
                self.assertEqual(jp.fetch_jpx_listed_stocks(),[])
    def test_pts_real_csv(self):
        date,rows=pts.parse_csv((Path(__file__).parent/'fixtures/pts.csv').read_text())
        self.assertEqual(date,'2026-09-09');self.assertEqual(rows[0]['code'],'7475');self.assertEqual(rows[0]['price'],3700)
    def test_mixed_pts_pages_rejected(self):
        response=Mock(text='html');response.raise_for_status=Mock()
        with patch.object(pts.requests,'get',return_value=response),patch.object(pts,'parse_kabutan_live',side_effect=[('2026-09-10','2026-09-10T20:00:00+09:00',[]),('2026-09-09','2026-09-09T20:00:00+09:00',[])]):
            with self.assertRaises(ValueError): pts.fetch_kabutan_live(dt.date(2026,9,10))
    def test_pts_after_midnight_uses_start_date(self):
        response=Mock(text='html');response.raise_for_status=Mock()
        row={'code':'1234','change_pct':5}
        with patch.object(pts.requests,'get',return_value=response),patch.object(pts,'parse_kabutan_live',return_value=('2026-09-11','2026-09-11T01:00:00+09:00',[row])):
            day,_,rows=pts.fetch_kabutan_live(dt.date(2026,9,10))
            self.assertEqual(day,'2026-09-10');self.assertEqual(rows[0]['session_date'],day)
    def test_bulk_timeout_falls_back(self):
        import subprocess
        with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('bulk',280)):
            self.assertEqual(jp.fetch_bulk_with_deadline(),[])

class RenderTests(unittest.TestCase):
    def test_empty_marker_clears_stale_html(self):
        doc='a<!--PRERENDER:rank-->OLD PRICE<!--/PRERENDER:rank-->b'
        self.assertNotIn('OLD PRICE',pr.replace_marker(doc,'rank',''))
    def test_stale_rank_not_ssg(self):
        self.assertEqual(pr.build_rank({'fetch_status':'stale','updated_at':dt.datetime.now(mc.JST).isoformat(),'all_stocks':[{'code':'OLD'}]}),'')
    def test_build_idempotent_markers(self):
        doc='<!--PRERENDER:rank-->old<!--/PRERENDER:rank-->'
        out=pr.replace_marker(doc,'rank','new')
        self.assertEqual(pr.replace_marker(out,'rank','new'),out)
    def test_render_dates_are_jst(self):
        text=ds.status_text({'updated_at':'2026-09-10T16:00:00Z'},36)
        self.assertIn('09/11 01:00 JST',text)

if __name__=='__main__':unittest.main()

class QuoteRepairTests(unittest.TestCase):
    def history(self):
        import pandas as pd
        return pd.DataFrame({'Close':[100,float('nan')]},index=pd.to_datetime(['2026-09-09','2026-09-10']).tz_localize('Asia/Tokyo'))
    def test_same_session_metadata_repairs_nan(self):
        from quote_repair import repair_last_close
        result=repair_last_close(self.history(),{'regularMarketPrice':110,'regularMarketTime':now('2026-09-10T15:30')},now('2026-09-11T00:30'))
        self.assertEqual(result.Close.iloc[-1],110)
    def test_old_metadata_cannot_repair_new_bar(self):
        import math
        from quote_repair import repair_last_close
        result=repair_last_close(self.history(),{'regularMarketPrice':110,'regularMarketTime':now('2026-09-09T15:30')},now('2026-09-11T00:30'))
        self.assertTrue(math.isnan(result.Close.iloc[-1]))
    def test_future_quote_rejected(self):
        import math
        from quote_repair import repair_last_close
        result=repair_last_close(self.history(),{'regularMarketPrice':110,'regularMarketTime':now('2026-09-10T15:30')},now('2026-09-10T10:00'))
        self.assertTrue(math.isnan(result.Close.iloc[-1]))
