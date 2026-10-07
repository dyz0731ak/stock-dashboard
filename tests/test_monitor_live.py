import datetime as dt
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import monitor_live as ml

NOW = dt.datetime(2026, 10, 7, 13, 0, tzinfo=dt.timezone.utc)


def health(checked_minutes_ago, datasets):
    checked = (NOW - dt.timedelta(minutes=checked_minutes_ago)).astimezone(dt.timezone(dt.timedelta(hours=9)))
    return {'checked_at': checked.isoformat(), 'datasets': datasets}


class MonitorLiveTest(unittest.TestCase):
    def test_healthy_site_has_no_problems(self):
        rows = [{'name': 'A', 'status': 'ok', 'critical': True, 'age_hours': 0.1},
                {'name': 'B', 'status': 'warning', 'critical': False, 'age_hours': 0.2}]
        self.assertEqual(ml.find_problems(health(20, rows), NOW), [])

    def test_stalled_deploy_is_detected(self):
        problems = ml.find_problems(health(28 * 60, []), NOW)
        self.assertEqual(len(problems), 1)
        self.assertIn('更新されていません', problems[0])

    def test_critical_error_and_long_stale_warning(self):
        rows = [{'name': 'A', 'status': 'error', 'critical': True, 'age_hours': 1},
                {'name': 'B', 'status': 'warning', 'critical': False, 'age_hours': 645.4},
                {'name': 'C', 'status': 'warning', 'critical': False, 'age_hours': 30}]
        problems = ml.find_problems(health(10, rows), NOW)
        self.assertEqual(len(problems), 2)
        self.assertTrue(problems[0].startswith('重大: A'))
        self.assertTrue(problems[1].startswith('長期取得失敗: B'))


if __name__ == '__main__':
    unittest.main()
