# econ-radar

無料公開データから世界のマクロ経済動向を継続クロールし、統計処理で異常検知、LLM に理論フレームワーク付きで解釈させて Discord に投稿する Bot。

## アーキテクチャ

```
[Ingest]                     [Storage]        [Compute]             [Interpret]         [Deliver]
FRED / yfinance / COT   ─┐
GDELT                    ├─► SQLite ───► 統計 (z-score,   ─► 閾値超過?  ─► LLM 解釈  ─► Discord
政策/中銀/ニュース RSS   ─┤   state.db    EWMA, 派生式)   ─► 政策検知?    仮説生成/     6 チャンネル
                         ┘                                              事後判定
```

## 現在地

Phase 1 (骨組み) と Phase 2 (実装深化) は完了。GitHub Secrets 設定と Discord チャンネル発行を経て運用開始できる状態。

## コーディング上の不変則 (Invariants)

作業する際は以下を必ず守る:

1. **タイムゾーン**: 保存する datetime は tz-aware にする。SQLite は `PARSE_DECLTYPES` + 明示的 adapter (Python 3.12+ で default が deprecated)
2. **冪等性**: 同じジョブを何度実行しても副作用が同じ (`INSERT ... ON CONFLICT DO NOTHING/UPDATE`、events テーブルは id が unique)
3. **LLM 発火は3トリガのみ**: サプライズ検知 / 政策発表 / 事後検証。それ以外の頻繁イベントは古典手法で捌く (コスト制御)
4. **仮説スキーマは Pydantic で強制**: LLM が自由記述で「〜と思われる」を吐けないように metric_id と transmission_channel は yaml から選択のみ (`llm/hypothesize.py` で validation)
5. **秘密情報は環境変数のみ**: FRED_API_KEY, ANTHROPIC_API_KEY, DISCORD_WEBHOOK_* は GitHub Secrets 経由。コード内にリテラルで書かない
6. **派生メトリクスの式評価は whitelist AST**: Name/BinOp(+-*/)/Constant/UnaryOp(-) のみ許可。`__import__` 等は ValueError で拒否 (`compute/derived.py::_walk`)
7. **状態の永続化は state.db を git にコミット**: 各ワークフローの末尾で自動 commit + push。concurrency group `state-writer` で並列書き込みを防ぐ
8. **ジョブは failing-safely**: 個別のソース fetch 失敗はログして次へ、全体は落とさない (`main.py::_log_error`)

## ディレクトリ

```
econ-radar/
├── .github/workflows/    cron ジョブ (frequent 15分 / daily / weekly / retrospective)
├── config/               ユーザーが編集する yaml
│   ├── sources.yaml         データソース定義
│   ├── metrics.yaml         追跡メトリクス (LLM 選択肢)
│   ├── theory_channels.yaml 伝達経路カタログ
│   └── discord.yaml         channel → env_var 対応
├── state/state.db        SQLite (repo にコミット)
├── src/
│   ├── ingest/           ソース別 fetcher (RSS, FRED, yfinance, COT, GDELT)
│   ├── compute/          z-score, サプライズ検知, 派生メトリクス式評価
│   ├── nlp/              policy_classifier (キーワード分類)
│   ├── llm/              interpret / hypothesize / retrospective (Anthropic API)
│   ├── discord_client/   webhook 投稿
│   ├── db.py             SQLite 接続 + スキーマ
│   ├── models.py         Pydantic
│   ├── config_loader.py  yaml → Pydantic
│   └── main.py           4 ジョブ CLI エントリ
└── requirements.txt
```

## データフロー詳細

**ingest-frequent (15分毎)**:
- RSS + GDELT を fetch
- events テーブルに新規のみ insert
- 全部 `#raw-feed` に投稿
- `policy_classifier.is_policy_relevant()` を通過したら `_handle_policy_event()` → LLM 仮説生成 → `#policy` 投稿 + policy_events に保存

**ingest-daily**:
- Pass 1: 全 non-derived メトリクス fetch (FRED / yfinance)
- Pass 2: derived メトリクス (spreads) を式評価で再計算
- Pass 3: 全メトリクスで surprise 検知 → 閾値超過なら LLM 解釈 → `#surprise` + `#markets` or `#macro-structural`

**ingest-weekly (金曜 23:00 UTC)**:
- CFTC TFF Socrata API から Leveraged Money net position を fetch (6通貨)
- surprise 検知 → 閾値超過なら投稿

**retrospective (毎日 01:00 UTC)**:
- policy_events の中で verified_at が NULL かつ horizon_months 経過したものを検索
- 各 hypothesis について: baseline (発表時直近) と observed (最新) を比較
- 機械判定 (holds / partial / rejected) + LLM が理由考察
- `#retrospective` に投稿

## 設計判断のログ

- **リアルタイム tick データは使わない** (2026-07-31 決定): マクロ用途で日次〜週次で十分。有料 WebSocket は要らない。カレンダー先読み + 発表直後 intensified polling の設計は Phase 3 で。
- **FinBERT / spaCy は導入見送り**: torch + モデルで CI 依存が 2GB 超。代替として (a) 政策検知はキーワード分類、(b) 精度が必要な NLP は LLM で構造化出力させる方針。
- **政策仮説は完全自動生成 + 完全自動検証**: ユーザーが手で仮説を書く運用は続かない。LLM に叩き台を生成させる代わりに、Pydantic + yaml 参照で厳格スキーマを強制することで「空虚な仮説」を防ぐ。
- **type "cot_csv" → "cot"**: 元は f_disagg.txt を想定していたが、Socrata JSON に切り替えたため rename。

## Phase 3 の候補

- LLM ベースの sentiment / entity 抽出 (FinBERT / spaCy の軽量代替)
- 中央銀行の詳細追加 (中国人民銀・スイス中銀・BOE)
- 家計・機関投資家保有 (GPIF 四半期、Fed Flow of Funds Z.1)
- 貿易フロー (UN Comtrade)
- Wikipedia 政策関連ページの編集履歴監視 (発表前先行指標)
- Discord スラッシュコマンドで問い合わせ ("最新の JPY サプライズは?" 等)
- 発表カレンダー先読み (FOMC/BOJ 会合日で intensified polling)
- 政策の類似事例 RAG (過去の似た政策で実際何が起きたか)
