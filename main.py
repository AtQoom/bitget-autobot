import os
import time
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, jsonify
from math import floor
import re

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
API_PASSPHRASE = os.environ.get("API_PASSPHRASE")

BASE_URL = "https://api.bitget.com"

def sign_message(timestamp, method, request_path, body=""):
    message = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")

def get_equity():
    try:
        method = "GET"
        query = "symbol=SOLUSDT&productType=USDT-FUTURES&marginCoin=USDT"
        path = f"/api/v2/mix/account/account?{query}"
        url = BASE_URL + path
        timestamp = str(int(time.time() * 1000))
        sign = sign_message(timestamp, method, path)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": API_PASSPHRASE
        }

        res = requests.get(url, headers=headers)
        print("📥 잔고 API 응답:", res.status_code, res.text)
        data = res.json()
        if data.get("code") == "00000" and data.get("data") and data["data"].get("accountEquity") is not None:
            return float(data["data"]["accountEquity"])
        else:
            print("❌ [잔고 응답 오류] code != 00000 또는 data 없음")
            return None
    except Exception as e:
        print("잔고 조회 오류:", e)
        return None

def get_market_price():
    try:
        url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
        res = requests.get(url)
        data = res.json()
        if data.get("code") == "00000" and data.get("data") and isinstance(data["data"], list):
            return float(data["data"][0]["lastPr"])
        else:
            print("❌ [시세 조회 실패]:", data)
            return 1.0
    except Exception as e:
        print("시세 조회 오류:", e)
        return 1.0

def send_order(side, size):
    timestamp = str(int(time.time() * 1000))
    method = "POST"
    path = "/api/v2/mix/order/place-order"
    body_data = {
        "symbol": "SOLUSDT",
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": str(size),
        "price": "",
        "marginMode": "isolated",
        "productType": "USDT-FUTURES"
    }

    body = json.dumps(body_data, separators=(',', ':'))
    signature = sign_message(timestamp, method, path, body)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    url = BASE_URL + path
    response = requests.post(url, headers=headers, data=body)
    print(f"📬 주문 응답 ({side} {size}):", response.status_code, response.text)
    return response.json()

def place_entry_order(signal, equity, strength=1.0):
    direction = "buy" if "LONG" in signal else "sell"
    leverage = 4
    price = get_market_price()

    base_risk = 0.24  # 안전 범위 유지
    raw_size = (equity * base_risk * leverage * strength) / price
    size = floor(raw_size * 10) / 10

    if size < 0.1 or size * price < 5:
        print(f"❌ 주문 수량({size}) 또는 금액이 최소 기준에 미달")
        return {"error": "Below minimum size or value"}

    return send_order(direction, size)

def place_exit_order(signal):
    direction = "sell" if "LONG" in signal else "buy"
    price = get_market_price()
    size = 1.5
    if "TP1" in signal:
        size *= 0.5
    return send_order(direction, size)

@app.route('/', methods=['POST'])
def webhook():
    print("🟡 [웹훅] 요청 도착 - Content-Type:", request.content_type)
    try:
        data = request.get_json(force=True)
        print("📦 웹훅 수신:", data)

        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))

        if not signal:
            return "Missing signal", 400

        entry_pattern = re.compile(r"ENTRY (LONG|SHORT) STEP 1")
        exit_pattern = re.compile(r"EXIT (LONG|SHORT) (TP1|TP2|SL_SLOW|SL_HARD)")

        if entry_pattern.match(signal):
            equity = get_equity()
            if equity is None:
                return "Balance error", 500
            result = place_entry_order(signal, equity, strength)
        elif exit_pattern.match(signal):
            result = place_exit_order(signal)
        else:
            return "Unknown signal", 400

        return jsonify({"status": "order_sent", "result": result})

    except Exception as e:
        print("❌ 웹훅 처리 오류:", str(e))
        return "Internal error", 500

@app.route('/ping', methods=['GET'])
def ping():
    return "pong", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
