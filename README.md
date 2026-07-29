# 📊 投資の砦

日本株のストップ高・急騰銘柄・決算速報・テーマ株・日経225ヒートマップを表示する定期更新型の投資ダッシュボード。海外市場は、日本株への影響を把握するための先物・為替・重要ニュースに絞って掲載する。

🔗 **ライブサイト**: https://dashboard.stock-overflow24.com/

## 機能

| 機能 | 説明 |
|------|------|
| 🇯🇵 日本株急騰ランキング | JPX公式の東証上場銘柄を母集団に、東証P/S/G横断の値上がり率上位30銘柄を表示 |
| 🕯 6か月日足 | 急騰ランキング30銘柄をローソク足と出来高のミニチャートで表示 |
| ◆ 日本株決算 | 日本株の決算速報と当日の決算予定を表示 |
| 📰 市場ニュース | 国内株式10件＋海外市場5件を目安に、日本株へ影響する重要動向を表示 |
| ▦ 日本株ヒートマップ | 日経225銘柄を時価総額と騰落率で可視化 |
| ⏱ 自動更新 | GitHub Actions で**約15分おきに**データ更新（cron遅延あり） |
| 🩺 鮮度監視 | 件数・更新時刻・部分取得失敗を `data/health.json` に記録し、画面上にも表示 |
| 📱 レスポンシブ | モバイル・タブレット対応 |

## 更新スケジュール

```
*/15 * * * *  (約15分おき。GitHub Actions cron は仕様上ベストエフォートで遅延することがあります)
```

## ファイル構成

```
stock-dashboard/
├── index.html                        # メインダッシュボード
├── data/
│   ├── japan_stocks.json             # 日本株ランキング・6か月日足（自動更新）
│   ├── earnings_flash.json           # 日本株決算速報（自動更新）
│   └── market_news.json              # 国内・海外市場ニュース（自動更新）
├── scripts/
│   ├── fetch_japan_stocks.py         # JPX上場銘柄 × Yahoo Finance日足
│   ├── fetch_market_news.py          # 国内・海外市場ニュース
│   └── requirements.txt             # Python 依存パッケージ
└── .github/workflows/
    └── update_stocks.yml             # GitHub Actions ワークフロー
```

## ローカル実行

```bash
cd scripts
pip install -r requirements.txt
python fetch_japan_stocks.py
python fetch_market_news.py
```

## データソース

- **日本株母集団**: [JPX 上場銘柄一覧](https://www.jpx.co.jp/markets/statistics-equities/misc/01.html)
- **株価・日足**: Yahoo Finance（yfinance）
- **国内ニュース**: 株探、みんかぶ、Yahoo!ファイナンス、Googleニュース
- **海外市場ニュース**: Googleニュース公開RSS

## ライセンス

MIT
