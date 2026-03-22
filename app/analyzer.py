import os
import json
import requests
import asyncio
import google.generativeai as genai
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
model = genai.GenerativeModel("gemini-3-flash-preview")


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

    response = model.generate_content(
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
):  # 記事の全文を入力してスコアと分析をtextで出力
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
    
    {text}
    
    【出力形式】
    ・短期スコア: [数値]
    ・長期スコア: [数値]
    ・分析の根拠: [論理的で詳細な解説を300文字程度で]
    """

    response = model.generate_content(prompt)
    return response.text


async def main():
    try:
        # Step 1
        articles = (
            get_recent_news_gnews()
        )  # 記事のリストを返す(titleとdescriptionとurlの辞書のリストを返す)

        # Step 2
        target_articles = filter_important_news(
            articles
        )  # 評価4以上の記事のリストを返す
        if not target_articles:
            return

        # Step 3 & 4: Crawl4AIの起動と処理ループ
        print("\n🌐 [Step 3] Crawl4AIを起動し、全文取得を開始します...")

        async with AsyncWebCrawler(verbose=False) as crawler:
            for idx, article in enumerate(target_articles):
                url = article.get("url")
                title = article.get("title")
                description = article.get("description")

                print(f"{idx+1}件目処理開始")
                print("-" * 50)
                print(f"📄 対象: {title}")
                print(f"🔗 URL: {url}")

                full_text = None
                try:
                    result = await crawler.arun(url=url)

                    if (
                        result.success
                        and result.markdown
                        and len(result.markdown.strip()) > 100
                    ):
                        full_text = result.markdown[:10000]
                        print(f"✅ {idx}件目全文取得成功")
                    else:
                        print(
                            "⚠️ 全文取得失敗（アクセスブロック、またはテキスト抽出エラー）"
                        )
                except Exception as e:
                    print(f"❌ クローリング実行エラー: {e}")

                if full_text:
                    analysis_text = f"【ニュース全文】\n{full_text}"
                    is_fallback = False
                else:
                    print(
                        "🔄 [代替処理] Step 1の概要（description）を使用してStep 4へ進みます。"
                    )
                    analysis_text = (
                        f"【ニュース 概要】\nタイトル: {title}\n概要: {description}"
                    )
                    is_fallback = True

                # Step 4: 分析実行
                analysis_result = precise_financial_analysis(
                    analysis_text, is_fallback
                )  # 記事の全文を入力してスコアと分析を出力
                print("📊 【最終精密分析結果】")
                print(analysis_result)

    except Exception as e:
        print(f"\n🚨 致命的なエラーが発生しました: {e}")


if __name__ == "__main__":
    asyncio.run(main())
