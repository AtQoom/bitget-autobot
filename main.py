import os
from flask import Flask, request
import requests

app = Flask(__name__)

BITGET_API_KEY = os.getenv("API_KEY")
BITGET_API_SECRET = os.getenv("API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("API_PASSPHRASE")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BITGET_BASE_URL = "https://api.bitget.com"
SYMBOL = "SOLUSDTUMCBL"

def send_telegram_message(message):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }
        try:
            requests.post(url, json=payload)
        except Exception as e:
            print(f"텔레그램 오류: {e}")

def place_order(direction):
    side = "open_long" if direction == "LONG" else "open_short"
    url = f"{BITGET_BASE_URL}/api/mix/v1/order/place-order"
    headers = {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": "",  # 실제 구현 시 signature 생성 필요
        "ACCESS-TIMESTAMP": "",  # 실제 구현 시 timestamp 포함 필요
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    # 테스트 환경에서는 아래와 같은 간단한 payload로 동작 확인
    payload = {
        "symbol": SYMBOL,
        "marginCoin": "USDT",
        "side": "buy" if direction == "LONG" else "sell",
        "orderType": "market",
        "size": 1,  # 트레이딩뷰에서 비중 반영된 경우 실전에서는 수정 필요
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        send_telegram_message(f"📥 Bitget 주문 실행됨: {direction}")
        return response.json()
    except Exception as e:
        send_telegram_message(f"❌ 주문 실패: {e}")
        return {"error": str(e)}

@app.route("/", methods=["GET"])
def home():
    return "Bitget AutoBot 작동 중!"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.data.decode("utf-8")
    if "ENTRY|LONG|AUTO" in data:
        place_order("LONG")
    elif "ENTRY|SHORT|AUTO" in data:
        place_order("SHORT")
    else:
        send_telegram_message(f"⚠️ 알 수 없는 웹훅 메시지 수신됨: {data}")
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
