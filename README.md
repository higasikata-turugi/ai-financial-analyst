# NVIDIA AI Financial Analyst

このプロジェクトは、NVIDIA（NVDA）に関する最新ニュースを自動で取得・分析し、株価への影響を予測してAPIとして提供するシステムです。GitHub Actionsを利用して毎日自動実行され、分析結果をJSONファイルとして蓄積します。

## 概要

1. **ニュース収集**: GNews APIを用いて過去24時間のNVIDIA関連ニュースを取得。
2. **ノイズフィルタリング**: Gemini APIを利用してニュースの重要度を5段階で評価し、重要度4以上の記事を抽出。
3. **全文取得**: Crawl4AIを使用して、対象記事の本文をスクレイピング。
4. **財務分析**: Gemini API（クオンツアナリストのプロンプト）を用いて、短期（1日〜2週間）および長期（半年〜2年）の株価影響スコア（-1.0〜+1.0）と論理的な理由を算出。
5. **データ蓄積**: 分析結果を `data/predictions.json` に保存。
6. **API配信**: FastAPIを用いて蓄積されたデータをエンドポイント経由で提供。

## ディレクトリ構成

```text
.
├── .github/
│   └── workflows/
│       └── daily_analysis.yml  # GitHub Actionsの自動実行ワークフロー
├── app/
│   ├── analyzer.py             # ニュース取得〜AI分析〜JSON保存を行うメインスクリプト
│   └── main.py                 # 分析結果を配信するFastAPIサーバー
├── data/
│   └── predictions.json        # AIの分析結果が蓄積されるファイル（自動生成）
├── .env                        # APIキーを設定する環境変数ファイル（要作成）
└── README.md                   # 本ドキュメント
```

## 各コンポーネントの機能

### `app/analyzer.py` (分析エンジン)
スクレイピングとLLMを組み合わせたデータパイプラインです。Gemini APIの制限（ResourceExhausted）を回避するため、複数のモデル（`gemini-3-flash-preview`, `gemini-1.5-flash`, `gemini-1.5-pro`）をフォールバックとして巡回する仕組みを備えています。本文の取得に失敗した場合は、ニュースの概要（description）から推測して分析を続行します。

### `app/main.py` (APIサーバー)
蓄積された `data/predictions.json` を読み込み、外部からアクセス可能なREST APIを提供します。CORSが有効化されており、将来的にWebフロントエンドなどからの呼び出しにも対応可能です。

### `.github/workflows/daily_analysis.yml` (自動化)
毎日日本時間の朝8時（UTC 23:00）に `analyzer.py` を実行するGitHub Actionsワークフローです。実行後に新しい分析結果が追加された場合、自動でリポジトリにコミット・プッシュしてデータを更新します。手動での実行（workflow_dispatch）にも対応しています。

## 環境構築と実行方法

### 前提条件

* Python 3.11以上
* [Google Gemini API Key](https://aistudio.google.com/app/apikey)
* [GNews API Key](https://gnews.io/)
* パッケージマネージャー `uv` を使用します。

### 1. ローカル環境のセットアップ

必要なライブラリとCrawl4AI用のブラウザ（Playwright）をインストールします。

```bash
uv pip install fastapi uvicorn google-generativeai requests crawl4ai python-dotenv
uv run python -m playwright install chromium
```

### 2. 環境変数の設定

プロジェクトのルートディレクトリに `.env` ファイルを作成し、取得したAPIキーを記述してください。

```ini
GEMINI_API_KEY=your_gemini_api_key_here
GNEWS_API_KEY=your_gnews_api_key_here
```

### 3. 分析スクリプトの実行（手動）

ニュースの取得と分析を手動で実行し、`data/predictions.json` を生成します。

```bash
uv run app/analyzer.py
```

### 4. APIサーバーの起動

FastAPIサーバーを起動し、分析結果を確認します。

```bash
uv run uvicorn app.main:app --reload
```

起動後、以下のURLにアクセスして動作を確認できます。
* ルート: `http://127.0.0.1:8000/`
* Swagger UI (仕様書): `http://127.0.0.1:8000/docs`

## APIエンドポイント仕様

| メソッド | エンドポイント | 説明 | パラメータ |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | APIの稼働状態を確認するルートエンドポイント | なし |
| `GET` | `/api/predictions/latest` | 最新の予測結果を取得（デフォルト5件） | `limit` (int): 取得件数 (任意) |
| `GET` | `/api/predictions/all` | 蓄積された全ての予測結果を新しい順に取得 | なし |

## GitHub Actionsでの運用について

このリポジトリをGitHubにプッシュした後、リポジトリの **Settings > Secrets and variables > Actions** にて、以下のRepository secretsを設定してください。

* `GEMINI_API_KEY`
* `GNEWS_API_KEY`

設定後、GitHub Actionsが設定されたスケジュールに従って自動的に分析とJSONの更新を行います。Actionsタブから手動でワークフローをトリガーすることも可能です。