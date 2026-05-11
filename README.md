# 📊 Stock Dashboard

日本株のストップ高・米国株の上昇率上位銘柄・セクター分析を表示するリアルタイムダッシュボード。

🔗 **ライブサイト**: https://dyz0731ak.github.io/stock-dashboard/

## 機能

| 機能 | 説明 |
|------|------|
| 🇯🇵 日本株ストップ高 | [株探(kabutan.jp)](https://kabutan.jp) からリアルタイムスクレイピング |
| 🇺🇸 米国株 上昇率上位 | Yahoo Finance から当日の上昇率上位銘柄を取得 |
| 📈 セクター分析 | 業種・セクター別の集計・グラフ表示 |
| ⏱ 自動更新 | GitHub Actions で**15分おきに**データ自動更新 |
| 📱 レスポンシブ | モバイル・タブレット対応 |

## 更新スケジュール

```
0,15,30,45 * * * *  (毎時 0分・15分・30分・45分)
```

## ファイル構成

```
stock-dashboard/
├── index.html                        # メインダッシュボード
├── data/
│   ├── japan_stocks.json             # 日本株データ（自動更新）
│   └── us_stocks.json                # 米国株データ（自動更新）
├── scripts/
│   ├── fetch_japan_stocks.py         # kabutan.jp スクレイパー
│   ├── fetch_us_stocks.py            # Yahoo Finance フェッチャー
│   └── requirements.txt             # Python 依存パッケージ
└── .github/workflows/
    └── update_stocks.yml             # GitHub Actions ワークフロー
```

## ローカル実行

```bash
cd scripts
pip install -r requirements.txt
python fetch_japan_stocks.py
python fetch_us_stocks.py
```

## データソース

- **日本株**: [株探(kabutan.jp)](https://kabutan.jp/warning/?mode=39) — ストップ高一覧
- **米国株**: [Yahoo Finance](https://finance.yahoo.com/screeners/predefined/day_gainers) — 当日上昇率上位

## ライセンス

MIT