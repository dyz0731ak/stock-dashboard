import sys
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fetch_company_profiles import parse_profile, collect_one, needs_refresh, safe_url


class CompanyProfileTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        self.html = '''<title>テスト【4052】株価</title>
        <div><div>概要</div><div>車向けの画像認識ソフトを開発。運転支援システムに提供。</div></div>
        <div><div>会社サイト</div><div><a href="https://example.com/">公式</a></div></div>
        <div><div>関連テーマ</div><div><a href="/themes/AI/">画像認識</a></div></div>'''

    def test_description_is_company_specific_and_short_summary(self):
        p = parse_profile(self.html, '4052')
        self.assertEqual(p['summary'], '車向けの画像認識ソフトを開発')
        self.assertIn('運転支援', p['description'])
        self.assertEqual(p['themes'], ['画像認識'])
        self.assertEqual(p['website'], 'https://example.com/')

    def test_wrong_company_and_missing_overview_rejected(self):
        with self.assertRaisesRegex(ValueError, 'code_mismatch'):
            parse_profile(self.html, '9082')
        with self.assertRaisesRegex(ValueError, 'overview_missing'):
            parse_profile('<title>4052</title><p>サイトメンテナンス</p>', '4052')

    def test_failure_retains_description_and_success_time(self):
        old = {'fetched_at': '2026-09-01T00:00:00+00:00', 'description': '以前確認した企業概要'}
        failed = Mock(side_effect=TimeoutError('upstream timeout'))
        result = collect_one('4052', {'name':'テスト'}, old, self.now, failed)
        self.assertEqual(result['fetched_at'], old['fetched_at'])
        self.assertEqual(result['description'], old['description'])
        self.assertEqual(result['fetch_status'], 'error')
        self.assertIn('TimeoutError', result['fetch_error'])

    def test_weekly_cache_does_not_repeat_requests(self):
        recent = {'fetch_status':'ok', 'last_attempt_at':(self.now-timedelta(days=1)).isoformat()}
        self.assertFalse(needs_refresh(recent, self.now))
        self.assertTrue(needs_refresh({}, self.now))
        recent['last_attempt_at'] = (self.now-timedelta(days=8)).isoformat()
        self.assertTrue(needs_refresh(recent, self.now))

    def test_untrusted_links_rejected(self):
        for url in ('javascript:alert(1)', 'data:text/html,test', '//evil.test', 'https://u:p@example.com'):
            self.assertEqual(safe_url(url), '')


if __name__ == '__main__':
    unittest.main()
