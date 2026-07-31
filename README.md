# econ-radar

無料公開データから世界のマクロ経済動向を継続クロールし、統計処理で異常検知、LLM に理論フレームワーク付きで解釈させ、Discord に投稿するボット。

## 設計方針

- **定量**: プログラム (z-score, EWMA, 派生メトリクス式評価) で再現可能に処理
- **定性**: 軽量な古典手法 (キーワード分類) + LLM (Claude) で理論解釈
- **サプライズ駆動**: 閾値超過イベントで LLM 発火 (常時 LLM を回さない → コスト抑制)
- **政策の事後検証**: 発表時に自動で仮説を立て、期日到達で機械判定 + LLM 考察
- **完全無料運用**: GitHub Actions cron + Public リポで実行時間無制限

### なぜ FinBERT / spaCy を入れないか

初期案では sentiment 用に FinBERT、NER 用に spaCy を予定していたが、
torch + モデルダウンロードで CI 依存が 2GB を超えるため見送り。
代替として:
- **政策検知はキーワード分類器で解決** (`src/nlp/policy_classifier.py`)
- 精度が必要な NLP は **LLM に投げて構造化出力** させる方が
  依存軽量かつ精度も高いので、Phase 3 で LLM ベース分類パイプラインを検討

## 実装状況

### データソース
- FRED (米金利・CPI・雇用・Fed BS): 実装済み
- CFTC COT (投機筋ポジション 6通貨): Socrata API 経由で実装済み
- yfinance (為替・株価指数 EOD): 実装済み
- GDELT 2.0 (GKG テーマ + 英語フィルタ): 実装済み
- Fed / ECB / BOJ RSS: 実装済み
- 主要メディア RSS (Reuters, BBC, 日経, FT): 実装済み

### Discord チャンネル
- `#raw-feed` — 生の取得ログ (LLM なし)
- `#markets` — 為替・金利・株価の日次変化とサプライズ
- `#policy` — 政策発表と即日レポート (キーワード分類で発火)
- `#macro-structural` — 構造データの週次〜月次変化
- `#surprise` — 閾値超過の緊急アラート
- `#retrospective` — 政策の事後検証

### やらないこと (Phase 3 以降)
- 中銀の詳細ポーリング (中国人民銀・スイス中銀等)
- 保険/年金保有詳細 (GPIF, Fed Flow of Funds)
- 貿易フロー詳細 (UN Comtrade)
- Wikipedia 編集履歴監視
- Discord スラッシュコマンド応答
- LLM ベースの sentiment / entity 抽出 (FinBERT / spaCy の代替)

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

環境変数 (ローカルは `.env`、CI は GitHub Secrets):

```
FRED_API_KEY=...
ANTHROPIC_API_KEY=...
DISCORD_WEBHOOK_RAW=...
DISCORD_WEBHOOK_MARKETS=...
DISCORD_WEBHOOK_POLICY=...
DISCORD_WEBHOOK_MACRO=...
DISCORD_WEBHOOK_SURPRISE=...
DISCORD_WEBHOOK_RETRO=...
```

## 実行

```bash
# ローカル手動実行 (各ジョブ)
python -m src.main ingest-frequent
python -m src.main ingest-daily
python -m src.main ingest-weekly
python -m src.main retrospective
```

CI は `.github/workflows/*.yml` の cron で自動実行。

## ディレクトリ

```
econ-radar/
├── config/                  ユーザーが編集する設定
├── state/state.db           SQLite (repo コミット、冪等)
├── src/
│   ├── ingest/              ソース別 fetcher
│   ├── compute/             統計処理
│   ├── nlp/                 古典 NLP
│   ├── llm/                 LLM 解釈・仮説生成・検証
│   ├── discord_client/      Discord webhook 投稿
│   └── main.py              CLI エントリ
└── .github/workflows/       cron ジョブ
```
