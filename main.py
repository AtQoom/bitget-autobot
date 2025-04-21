# Bitget 자동매매 서버 - TP/SL 서버 계산용
# 2025-04-21 기준

import os, time, hmac, hashlib, base64, json
import requests
from flask import Flask, request, jsonify
from math import floor

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
API_PASSPHRASE = os.environ.get("API_PASSPHRASE")
BASE_URL = "https://api.bitget.com"

def sign_message(timestamp, method, request_path, body=""):
    msg = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def get_price():
    url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
    try:
        r = requests.get(url).json()
        return float(r["data"][0]["lastPr"])
    except:
        return 0

def get_position():
    path = "/api/v2/mix/position/single-position?symbol=SOLUSDT&marginCoin=USDT&productType=USDT-FUTURES"
    url = BASE_URL + path
    ts = str(int(time.time() * 1000))
    sign = sign_message(ts, "GET", path)
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": API_PASSPHRASE
    }
    try:
        r = requests.get(url, headers=headers).json()
        if r["code"] == "00000" and isinstance(r["data"], list) and len(r["data"]) > 0:
            return r["data"][0]
    except:
        pass
    return {}

def send_order(side, size):
    path = "/api/v2/mix/order/place-order"
    ts = str(int(time.time() * 1000))
    data = {
        "symbol": "SOLUSDT",
        "marginCoin": "USDT",
        "orderType": "market",
        "side": side,
        "size": str(size),
        "price": "",
        "marginMode": "isolated",
        "productType": "USDT-FUTURES",
        "positionType": "single"
    }
    body = json.dumps(data, separators=(',', ':'))
    sign = sign_message(ts, "POST", path, body)
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }
    res = requests.post(BASE_URL + path, headers=headers, data=body)
    print(f"📤 주문 ({side} {size}):", res.status_code, res.text)
    return res.json()

def execute_exit(signal, strength):
    pos = get_position()
    if not pos or float(pos.get("total", 0)) == 0:
        print("❌ 포지션 없음. 스킵")
        return {"skip": True}
    
    size = float(pos["total"])
    side = pos["holdSide"]
    direction = "sell" if side == "long" else "buy"
    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio
    qty = 0

    if "TP1" in signal:
        qty = floor(size * tp1_ratio * 10) / 10
    elif "TP2" in signal:
        qty = floor(size * tp2_ratio * 10) / 10
    elif "SL_SLOW" in signal:
        qty = floor(size * 0.5 * 10) / 10
    elif "SL_HARD" in signal:
        qty = floor(size * 10) / 10
    
    if qty >= 0.1:
        return send_order(direction, qty)
    return {"skip": "too small"}

@app.route('/', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))
        print("📦 알림 수신:", signal, strength)

        if "EXIT" in signal:
            res = execute_exit(signal, strength)
            return jsonify(res)

        # ENTRY는 여전히 alert 기반 수신 (자동매매 진입 방식 유지)
        return jsonify({"status": "ignored"})

    except Exception as e:
        print("❌ 오류:", e)
        return "Error", 500

@app.route('/ping', methods=['GET'])
def ping():
    return "pong", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
