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

# === 서명 생성 ===
def sign_message(timestamp, method, request_path, body=""):
    message = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")

# === 잔고 조회 ===
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
        data = res.json()
        if data.get("code") == "00000" and data.get("data"):
            return float(data["data"].get("accountEquity", 0))
        return None
    except Exception as e:
        print("잔고 조회 오류:", e)
        return None

# === 포지션 수량 조회 ===
def get_position_size():
    try:
        method = "GET"
        path = "/api/v2/mix/position/single-position?symbol=SOLUSDT&marginCoin=USDT"
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
        data = res.json()
        if data.get("code") == "00000" and data.get("data"):
            return float(data["data"].get("total", 0))
        return 0
    except Exception as e:
        print("포지션 조회 오류:", e)
        return 0

# === 시세 조회 ===
def get_market_price():
    try:
        url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
        res = requests.get(url)
        data = res.json()
        if data.get("code") == "00000" and data.get("data") and isinstance(data["data"], list):
            return float(data["data"][0]["lastPr"])
        return 1.0
    except:
        return 1.0

# === 주문 실행 ===
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
    res = requests.post(url, headers=headers, data=body)
    print(f"📬 주문 응답 ({side} {size}):", res.status_code, res.text)
    return res.json()

# === 진입 주문 ===
def place_entry_order(signal, equity, strength):
    direction = "buy" if "LONG" in signal else "sell"
    leverage = 4
    price = get_market_price()
    base_risk = 0.24

    # STEP 추출
    match = re.search(r"STEP (\d+)", signal)
    step = int(match.group(1)) if match else 1

    # 분할 수 계산
    steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
    portion = 1 / steps

    raw_size = (equity * base_risk * leverage * strength * portion) / price
    max_size = (equity * 0.9 * portion) / price
    size = min(raw_size, max_size)
    size = floor(size * 10) / 10

    print(f"🧮 계산 로그 | equity={equity}, price={price}, strength={strength}, portion={portion}, size(before round)={raw_size}, final size={size}")

    if size < 0.1 or size * price < 5:
        print(f"❌ STEP {step} 주문 수량({size}) 또는 금액이 최소 기준에 미달")
        return {"error": "Below minimum size or value"}

    return send_order(direction, size)

# === 청산 주문 ===
def place_exit_order(signal, strength):
    direction = "sell" if "LONG" in signal else "buy"
    position_size = get_position_size()
    if position_size <= 0:
        print(f"⛔ 현재 포지션 없음. 청산 스킵: {signal}")
        return {"skipped": True}

    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio
    size = position_size

    if "TP1" in signal:
        size = floor(position_size * tp1_ratio * 10) / 10
    elif "TP2" in signal:
        size = floor(position_size * tp2_ratio * 10) / 10
    elif "SL_SLOW" in signal:
        size = floor(position_size * 0.5 * 10) / 10

    return send_order(direction, size)

# === 웹훅 처리 ===
@app.route('/', methods=['POST'])
def webhook():
    try:
        # Content-Type 체크 제거하고 강제로 JSON 파싱
        data = request.get_json(force=True)
        print("📦 웹훅 수신:", data)

        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))

        if not signal:
            return "Missing signal", 400

        if "ENTRY" in signal:
            equity = get_equity()
            if equity is None:
                return "Balance error", 500
            result = place_entry_order(signal, equity, strength)
        elif "EXIT" in signal:
            result = place_exit_order(signal, strength)
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
