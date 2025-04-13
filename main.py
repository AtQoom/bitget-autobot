# main.py
from flask import Flask, request, jsonify
import os
import requests
import hmac
import hashlib
import time
import json

app = Flask(__name__)

# 환경 변수 로딩
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api.bitget.com"

symbol = "SOLUSDTUMCBL"
marginMode = "isolated"
tradeSide = {
    "LONG": "open_long",
    "SHORT": "open_short"
}
closeSide = {
    "LONG": "close_long",
    "SHORT": "close_short"
}

step_risk = {
    "1": 0.05,
    "2": 0.10,
    "3": 0.20,
    "4": 0.25
}

def send_telegram_message(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, data=data)
    except Exception as e:
        print("텔레그램 전송 오류:", e)

def get_server_time():
    return str(int(time.time() * 1000))

def sign_request(timestamp, method, request_path, body=""):
    message = timestamp + method + request_path + body
    return hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

def place_order(direction, step):
    size = step_risk.get(step, 0.05)  # default 5%
    side = tradeSide.get(direction)
    if side is None:
        return

    price = ""  # 시장가 주문
    quantity = 1  # 수량을 유동적으로 변경 가능
    timestamp = get_server_time()
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": quantity,
        "timeInForceValue": "normal"
    }
    body_json = json.dumps(body)
    path = "/api/v1/mix/order/placeOrder"
    sign = sign_request(timestamp, "POST", path, body_json)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    url = BASE_URL + path
    res = requests.post(url, headers=headers, data=body_json)
    send_telegram_message(f"[{direction} {step}] 주문 응답: {res.text}")

def close_position(direction, reason):
    side = closeSide.get(direction)
    if side is None:
        return

    timestamp = get_server_time()
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": 0,  # 전체 포지션 종료
        "timeInForceValue": "normal"
    }
    body_json = json.dumps(body)
    path = "/api/v1/mix/order/closePosition"
    sign = sign_request(timestamp, "POST", path, body_json)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    url = BASE_URL + path
    res = requests.post(url, headers=headers, data=body_json)
    send_telegram_message(f"[{direction} {reason}] 청산 응답: {res.text}")

@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.json
        signal = data.get("signal", "")

        if signal.startswith("ENTRY LONG STEP"):
            step = signal.split()[-1]
            place_order("LONG", step)

        elif signal.startswith("ENTRY SHORT STEP"):
            step = signal.split()[-1]
            place_order("SHORT", step)

        elif signal == "EXIT LONG TP1" or signal == "EXIT LONG TP2":
            close_position("LONG", signal.split()[-1])

        elif signal == "EXIT SHORT TP1" or signal == "EXIT SHORT TP2":
            close_position("SHORT", signal.split()[-1])

        elif signal == "EXIT LONG SL1" or signal == "EXIT LONG SL_HARD":
            close_position("LONG", signal.split()[-1])

        elif signal == "EXIT SHORT SL1" or signal == "EXIT SHORT SL_HARD":
            close_position("SHORT", signal.split()[-1])

        return jsonify({"success": True})
    except Exception as e:
        send_telegram_message(f"[에러] {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
