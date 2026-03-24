import json
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# FastAPIアプリケーションの初期化
app = FastAPI(
    title="NVIDIA AI Financial Analyst API",
    description="GitHub Actionsで毎日自動分析されたNVIDIAのニュースと株価予測スコアを提供するAPIです。",
    version="1.0.0",
)

# CORS設定（将来的にWebフロントエンドなど別のドメインからAPIを叩けるようにする）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_FILE = "data/predictions.json"


def load_predictions():
    """蓄積されたJSONデータを読み込む関数"""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []


@app.get("/")
def read_root():
    """APIのルート。動作確認用"""
    return {
        "message": "NVIDIA AI Financial Analyst API が正常に稼働しています。",
        "hint": "ブラウザで /docs にアクセスすると、APIの仕様書（Swagger UI）が見られます。",
    }


@app.get("/api/predictions/latest")
def get_latest_predictions(limit: int = 5):
    """最新の予測結果をいくつか取得するエンドポイント"""
    data = load_predictions()
    if not data:
        raise HTTPException(
            status_code=404, detail="まだ予測データが蓄積されていません。"
        )

    # データは古い順に追加されているため、逆順（最新順）にして返す
    reversed_data = data[::-1]
    return {"latest_predictions": reversed_data[:limit]}


@app.get("/api/predictions/all")
def get_all_predictions():
    """すべての予測結果を取得するエンドポイント"""
    data = load_predictions()
    return {"total_count": len(data), "predictions": data[::-1]}
