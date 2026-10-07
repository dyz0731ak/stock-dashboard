import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from index_memberships import load_memberships, memberships, normalize_code, filter_rows, validate, parse_topix_selection
from prerender import build_rank
from unittest.mock import patch


class IndexMembershipTests(unittest.TestCase):
    def setUp(self):
        self.data = load_memberships()

    def test_official_snapshot_counts_and_relationships(self):
        if self.data['version'] != '2026-10-07':
            self.skipTest('Historical release assertions only')
        groups = {key: {code for code, tags in self.data['securities'].items() if key in tags} for key in self.data['groups']}
        self.assertEqual({key: len(rows) for key, rows in groups.items()}, dict(topix=1669, topix_new=35, transition=683, nikkei225=225))
        self.assertTrue(groups['transition'] <= groups['topix'])
        self.assertTrue(groups['topix_new'] <= groups['topix'])
        self.assertFalse(groups['transition'] & groups['topix_new'])
        self.assertIn('590A', groups['transition'])
        self.assertIn('593A', groups['topix_new'])
        self.assertIn('285A', groups['nikkei225'])

    def test_code_only_and_multiple_memberships(self):
        self.assertEqual(normalize_code(' 141a.t '), '141A')
        self.assertEqual(normalize_code('141A0'), '')
        self.assertEqual(memberships(self.data, '1301'), ['topix', 'transition'])
        self.assertEqual(memberships(self.data, 'TOPIX'), [])
        self.assertIn('nikkei225', memberships(self.data, 7203))

    def test_intersection_preserves_order_objects_and_existing_scope(self):
        rows = [dict(code='1301', rank=4), dict(code='0000', name='極洋', rank=5), dict(code='590A', rank=19)]
        result = filter_rows(rows, 'transition', self.data)
        self.assertEqual([s['rank'] for s in result], [4, 19])
        self.assertIs(result[0], rows[0])
        self.assertEqual(len(rows), 3)
        self.assertEqual(filter_rows(rows, 'nikkei225', self.data), [])

    def test_reject_truncated_data(self):
        data = copy.deepcopy(self.data)
        del data['securities']['1301']
        with self.assertRaises(ValueError):
            validate(data)

    def test_parser_fails_closed_on_missing_duplicate_rows(self):
        text = '（１）新規追加銘柄\n1 141A 新規 グロース\n（２）移行措置銘柄\n1 1301 既存 プライム\n（３）構成銘柄\n1 1301 既存 プライム\n2 141A 新規 グロース\n'
        counts = dict(topix_new=1, transition=1, topix=2)
        self.assertEqual(parse_topix_selection(text, counts)['transition'], ['1301'])
        for broken in [text.replace('2 141A', '2 1301'), text.replace('1 1301 既存 プライム\n', '', 1)]:
            with self.assertRaises(ValueError):
                parse_topix_selection(broken, counts)

    def test_prerender_market_then_index_and_unknown(self):
        data = dict(all_stocks=[dict(code='1301', name='極洋', market='東証P', change_pct=5), dict(code='0000', name='不明', change_pct=2)])
        with patch('prerender.is_fresh', return_value=True):
            html = build_rank(data)
        self.assertIn('<th>市場</th><th class="index-col">指数</th>', html)
        self.assertIn('data-index-filter="transition"', html)
        self.assertIn('対象指数なし', html)

    def test_prerender_bad_index_data_does_not_break_ranking(self):
        data = dict(all_stocks=[dict(code='1301', name='極洋', change_pct=5)])
        with patch('prerender.is_fresh', return_value=True), patch('prerender.load_memberships', side_effect=ValueError('bad data')):
            html = build_rank(data)
        self.assertIn('極洋', html)
        self.assertIn('確認中', html)
