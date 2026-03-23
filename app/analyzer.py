import os
import json
import requests
import asyncio
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted  # 追加: API制限検知用
from dotenv import load_dotenv
from crawl4ai import AsyncWebCrawler
from datetime import datetime, timedelta, timezone

# --- 初期設定 ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

if not GEMINI_API_KEY or not GNEWS_API_KEY:
    raise ValueError("APIキーが設定されていません。.envファイルを確認してください。")

genai.configure(api_key=GEMINI_API_KEY)

# 追加: ループ処理用のモデルリスト（必要に応じてモデル名は変更してください）
FALLBACK_MODELS = [
    "gemini-3-flash-preview",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]


def generate_with_fallback(prompt, generation_config=None):
    """追加: モデルをループしてAPI制限時に別モデルに切り替える関数"""
    for model_name in FALLBACK_MODELS:
        try:
            model = genai.GenerativeModel(model_name)
            if generation_config:
                return model.generate_content(
                    prompt, generation_config=generation_config
                )
            else:
                return model.generate_content(prompt)
        except ResourceExhausted:
            print(f"⚠️ [{model_name}] は使用制限に達しました。別のモデルを試します。")
            continue
        except Exception as e:
            print(f"⚠️ [{model_name}] 実行中にエラーが発生しました: {e}")
            continue

    raise RuntimeError(
        "❌ 利用可能なすべてのモデルで使用制限、またはエラーが発生しました。"
    )


def get_recent_news_gnews():  # 記事のリスト取得(titleとdescriptionとurlの辞書のリストを返す)
    """Step 1: GNews APIからNVIDIAに関する最新ニュースを取得"""
    print("🔄 [Step 1] GNews APIから最新のニュースを取得中...")
    url = "https://gnews.io/api/v4/search"

    now = datetime.now(timezone.utc)  # 現在のUTC時間を取得

    twenty_four_hours_ago = now - timedelta(hours=24)  # 24時間前を計算

    # ISO形式の文字列に変換（末尾の +00:00 を Z に置換）
    formatted_time = twenty_four_hours_ago.isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )

    # GNews APIのパラメータ設定
    params = {
        "q": "NVIDIA OR NVDA",
        "from": formatted_time,  # 24時間以内
        "lang": "en",  # 英語
        "max": 100,  # 一度に取得する最大件数
        "sortby": "publishedAt",  # 最新順
        "apikey": GNEWS_API_KEY,
    }

    response = requests.get(url, params=params)  # ニュース取得(json形式)
    response.raise_for_status()  # 通信が失敗していたら、そこでプログラムを強制終了

    articles = response.json().get(
        "articles", []
    )  # json形式を辞書形式にして、記事のリストを取得
    if not articles:
        raise Exception("ニュースが見つかりませんでした。")

    print(f"✅ {len(articles)}件のニュースを取得しました。")
    return articles


def filter_important_news(articles):  # 評価4以上のニュースのリストを返す
    """Step 2: Geminiに重要度を5段階評価させ、4以上のものを抽出"""
    print("\n🧠 [Step 2] Geminiによるノイズフィルタリング（重要度評価）を実行中...")

    news_list_text = ""
    for idx, article in enumerate(
        articles
    ):  # news_list_textに全部のニュースタイトルと概要ひとまとめ
        title = article.get("title", "")
        description = article.get("description", "")
        news_list_text += f"[{idx}] タイトル: {title}\n概要: {description}\n\n"

    prompt = f"""
    あなたは金融アナリストです。以下のNVIDIAに関するニュース一覧を読み、それぞれの「NVIDIAの株価への影響の重要度」を1〜5の5段階で評価してください。
    （5: 決定的で重大な影響、4: 強い影響、3: 中程度、2: 軽微、1: 影響なし・ノイズ）
    
    必ず以下のJSONフォーマットのみを出力してください。
    [
        {{"index": 0, "score": 3}},
        {{"index": 1, "score": 5}}
    ]
    
    ニュース一覧:
    {news_list_text}
    """

    # generate_with_fallback を使用してループ処理
    response = generate_with_fallback(
        prompt,
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json"
        ),
    )

    try:
        scores = json.loads(response.text)  # json形式を辞書形式に変換
    except json.JSONDecodeError:
        print("❌ AIのJSON解析に失敗しました。生の出力:", response.text)
        return []

    important_articles = []
    for item in scores:  # スコアが4以上のニュースをimportant_articles(リスト)に追加
        if item.get("score", 0) >= 4:
            idx = item["index"]
            important_articles.append(articles[idx])
            print(f"⭐ 重要度 {item['score']}: {articles[idx]['title']}")

    print(f"⚠️ 重要度4以上のニュースは{len(important_articles)}件でした。")

    return important_articles


def precise_financial_analysis(
    text, is_fallback=False
):  # 記事の全文を入力してスコアと分析をjsonで出力
    """Step 4: Geminiによる精密な財務分析とスコア出力"""
    print("🧠 [Step 4] Geminiによる精密分析を実行中...\n")

    if is_fallback:
        condition_note = "【注意】この記事は全文の取得に失敗したため、ニュースAPIの概要（description）のみを提供しています。限られた情報から可能な限り推測して分析してください。"
    else:
        condition_note = "提供されたニュースの全文を基に分析してください。"

    prompt = f"""
    あなたは世界トップクラスのクオンツアナリストです。
    以下の情報から、NVIDIAの株価に対する精密な分析を行ってください。
    
    {condition_note}
    
    【ルール】
    1. 表面的な事象だけでなく、競合他社、サプライチェーン、マクロ経済への波及効果も考慮すること。
    2. 短期スコア（1日〜2週間）と長期スコア（半年〜2年）を -1.0 〜 +1.0 の数値で出すこと。
    3.もし入力された情報に実質的なニュース本文が含まれていないと判断した場合は、スコアは両方0にして、reasoningには、「【エラー】本文が取得できていません」とだけ記載してください。

    {text}
    
    必ず以下のJSONフォーマットのみを出力してください。
    {{
        "short_term_score": 数値(-1.0 to 1.0),
        "long_term_score": 数値(-1.0 to 1.0),
        "reasoning": "論理的で詳細な解説を300文字程度で"
    }}
    """

    # generate_with_fallback を使用してループ処理
    response = generate_with_fallback(
        prompt,
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json"
        ),
    )
    return response.text


async def main():
    try:
        # 結果をまとめるためのリストを準備
        daily_results = []
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Step 1
        articles = (
            get_recent_news_gnews()
        )  # 記事のリストを返す(titleとdescriptionとurlの辞書のリストを返す)

        # Step 2
        target_articles = filter_important_news(
            articles
        )  # 評価4以上の記事のリストを返す
        if not target_articles:
            print("本日は分析対象の重要なニュースがありませんでした。")
            return

        # Step 3 & 4
        print("\n🌐 [Step 3] Crawl4AIを起動し、全文取得を開始します...")
        async with AsyncWebCrawler(verbose=False, browser_type="firefox") as crawler:
            for idx, article in enumerate(target_articles):
                url = article.get("url")
                title = article.get("title")
                description = article.get("description")

                print(f"\n--- {idx+1}件目処理開始 ---")
                print(f"📄 対象: {title}")

                full_text = None
                max_retries = 3  # リトライ回数の上限

                for attempt in range(max_retries):
                    try:
                        # 修正: Crawl4AIの強力なパラメータを活用する
                        result = await crawler.arun(
                            url=url,
                            magic=True,  # CloudflareなどのBot検知を回避するステルスモード
                            bypass_cache=True,
                            word_count_threshold=50,  # 短すぎるノイズを事前排除
                            # wait_for="js:() => document.readyState === 'complete'" # 必要に応じて追加: ページの完全読み込みを待つ
                        )

                        # 生のmarkdownではなく、ナビゲーションや広告を除去した fit_markdown を優先使用する
                        target_markdown = (
                            result.fit_markdown
                            if result.fit_markdown
                            else result.markdown
                        )

                        if (
                            result.success
                            and target_markdown
                            and len(target_markdown.strip()) > 300
                        ):
                            full_text = target_markdown[:10000]
                            print(
                                f"✅ 全文取得成功 (試行 {attempt + 1}/{max_retries}回目)"
                            )
                            break  # 成功したらリトライループを抜ける
                        else:
                            print(
                                f"⚠️ 全文取得失敗 または文字数不足 (試行 {attempt + 1}/{max_retries}回目)"
                            )

                    except Exception as e:
                        print(
                            f"❌ クローリング実行エラー (試行 {attempt + 1}/{max_retries}回目): {e}"
                        )

                    # 失敗した場合、最後の試行でなければ数秒待機してリトライ
                    if attempt < max_retries - 1:
                        await asyncio.sleep(3)

                # 結果の判定とStep4へ
                if full_text:
                    analysis_text = f"【ニュース全文】\n{full_text}"
                    is_fallback = False
                else:
                    analysis_text = (
                        f"【ニュース 概要】\nタイトル: {title}\n概要: {description}"
                    )
                    is_fallback = True

                # Step 4: 分析実行
                raw_response = precise_financial_analysis(
                    analysis_text, is_fallback
                )  # スコアと分析をjsonで出力

                if "【エラー】" in raw_response and not is_fallback:
                    print(
                        "⚠️ AIが本文なしと判定しました。概要のみで再分析を実行します。"
                    )
                    is_fallback = True
                    analysis_text = (
                        f"【ニュース 概要】\nタイトル: {title}\n概要: {description}"
                    )
                    raw_response = precise_financial_analysis(
                        analysis_text, is_fallback
                    )

                try:
                    analysis_result = json.loads(raw_response)
                except json.JSONDecodeError:
                    print("❌ 財務分析のJSON解析に失敗しました。")
                    analysis_result = {
                        "short_term_score": 0,
                        "long_term_score": 0,
                        "reasoning": "JSON解析エラー",
                    }

                print("📊 【最終精密分析結果】")
                print(analysis_result)

                # --- 修正箇所: 結果をリストに追加 ---
                daily_results.append(
                    {
                        "date": today_str,
                        "title": title,
                        "url": url,
                        "analysis": analysis_result,
                        "is_fallback": is_fallback,
                    }
                )

        # --- 追加箇所: JSONファイルへの保存処理 ---
        save_results_to_json(daily_results)

    except Exception as e:
        print(f"\n🚨 致命的なエラーが発生しました: {e}")


# --- 追加箇所: JSON保存用関数 ---
def save_results_to_json(new_results, filepath="data/predictions.json"):
    """分析結果をJSONファイルに追記保存する"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)  # dataフォルダがなければ作る

    all_data = []
    # 既存のデータがあれば読み込む
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                all_data = json.load(f)
        except json.JSONDecodeError:
            print("⚠️ 既存のJSONファイルが壊れているため、新規作成します。")

    # 新しいデータを追加
    all_data.extend(new_results)

    # 保存
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)
    print(f"\n💾 分析結果を {filepath} に保存しました！")


if __name__ == "__main__":
    asyncio.run(main())
