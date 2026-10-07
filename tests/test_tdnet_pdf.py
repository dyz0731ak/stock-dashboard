from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tdnet_earnings as td

# 2026-10-07 に「未対応の原資料形式」で落ちていた実際の2社の表（pdfplumber の抽出結果）
REVISION_WITH_SEN = """（単位：百万円）
親会社株主に帰属する １株当たり
売上高 営業利益 経常利益
当期純利益 当期純利益
前回発表予想（Ａ） 241,000 7,700 7,650 4,800 277円20銭
今回修正予想（Ｂ） 238,000 6,000 6,050 3,500 201円34銭
増減額（Ｂ－Ａ） △3,000 △1,700 △1,600 △1,300
（ご参考）前期実績
233,833 7,441 7,414 5,339 307円34銭"""

ACTUAL_VS_FORECAST = """（2026年３月１日～2026年８月31日） （百万円）
売上高 営業利益 経常利益 帰属する
百万円 百万円 百万円 百万円 円 銭
前回公表数値（A）
2,872 130 128 87 2.00
今回実績（B） 2,605 159 155 120 2.76
増減額（B-A） △266 28 26 33
（ご参考）前期第２四半期実績 2,368 159 158 126 2.90
なお、通期の連結業績予想につきましては、前回公表数値を据え置いております。
以 上"""

ROW = dict(title='t', document_url='x', time='15:00', published_date='2026-10-07')


class TdnetPdfTest(unittest.TestCase):
    def test_revision_with_eps_in_yen_and_sen(self):
        rows = td.parse_pdf_comparisons(REVISION_WITH_SEN, '通期連結業績予想の修正に関するお知らせ')
        net = next(r for r in rows if r['label'] == '純利益')
        self.assertEqual((net['previous'], net['current']), (4800e6, 3500e6))
        self.assertEqual(net['basis'], '前回会社予想比')
        self.assertEqual(td.select_impact(ROW, rows, [])['impact_label'], '下方修正 -27.1%')

    def test_actual_vs_forecast_with_values_on_next_line(self):
        rows = td.parse_pdf_comparisons(ACTUAL_VS_FORECAST, '業績予想と実績との差異に関するお知らせ')
        net = next(r for r in rows if r['label'] == '純利益')
        self.assertEqual((net['previous'], net['current']), (87e6, 120e6))
        self.assertEqual(net['basis'], '会社予想との差異')
        self.assertEqual(td.select_impact(ROW, rows, [])['impact_label'], '予想超過 +37.9%')

    def test_unknown_column_layout_is_rejected(self):
        text = '前回発表予想（Ａ） 241,000 7,700\n今回修正予想（Ｂ） 238,000 6,000'
        self.assertEqual(td.parse_pdf_comparisons(text, '業績予想の修正'), [])


if __name__ == '__main__':
    unittest.main()
