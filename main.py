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

def get_equity():
    path = "/api/v2/mix/account/account?symbol=SOLUSDT&marginCoin=USDT&productType=USDT-FUTURES"
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
        return float(r["data"]["accountEquity"]) if r["code"] == "00000" else None
    except:
        return None

def get_position_size():
    path = "/api/v2/mix/position/single-position?symbol=SOLUSDT&marginCoin=USDT"
    url = BASE_URL + path
    try:
        ts = str(int(time.time() * 1000))
        sign = sign_message(ts, "GET", path)
        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": API_PASSPHRASE
        }
        r = requests.get(url, headers=headers).json()
        return float(r["data"]["total"]) if r["code"] == "00000" else 0
    except:
        return 0

def get_price():
    url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
    try:
        r = requests.get(url).json()
        return float(r["data"][0]["lastPr"])
    except:
        return 1.0

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
        "productType": "USDT-FUTURES"
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
    print(f"📤 주문 요청 ({side} {size}):", res.status_code, res.text)
    return res.json()

def place_entry(signal, equity, strength):
    direction = "buy" if "LONG" in signal else "sell"
    leverage = 4
    price = get_price()
    base_risk = 0.24
    strength = max(1.0, min(strength, 2.0))

    # 단계 및 비중 계산
    if strength >= 2.0:
        steps = 1
        portion = 0.5
    elif strength >= 1.6:
        steps = 2
        portion = 0.3
    else:
        steps = 3
        portion = 0.2

    raw_size = (equity * base_risk * leverage * strength * portion) / price
    max_size = (equity * 0.9 * portion) / price
    size = min(raw_size, max_size)
    size = floor(size * 10) / 10

    if size < 0.1 or size * price < 5:
        print("❌ 진입 실패: 수량 부족")
        return {"error": "too small"}

    return send_order(direction, size)

def place_exit(signal, strength):
    direction = "sell" if "LONG" in signal else "buy"
    pos = get_position_size()
    if pos <= 0:
        print(f"⛔ 포지션 없음 → 강제 청산 시도: {signal}")
        return finalize_remaining(signal)

    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.65)
    tp2_ratio = 1.0 - tp1_ratio
    size = pos
    if "TP1" in signal:
        size = floor(pos * tp1_ratio * 10) / 10
    elif "TP2" in signal:
        size = floor(pos * tp2_ratio * 10) / 10
    elif "SL_SLOW" in signal:
        size = floor(pos * 0.5 * 10) / 10

    return send_order(direction, size)

def finalize_remaining(signal):
    direction = "sell" if "LONG" in signal else "buy"
    size = get_position_size()
    if 0 < size < 0.11:
        print("⚠️ 잔여 포지션 청산:", size)
        return send_order(direction, floor(size * 10) / 10)
    return {"status": "done"}

@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))
        print("📦 웹훅 수신:", data)

        if "ENTRY" in signal:
            eq = get_equity()
            if not eq:
                return "잔고 조회 실패", 500
            res = place_entry(signal, eq, strength)
        elif "EXIT" in signal:
            res = place_exit(signal, strength)
            finalize_remaining(signal)
        else:
            return "Unknown signal", 400

        return jsonify({"status": "ok", "result": res})
    except Exception as e:
        print("❌ 오류:", e)
        return "Error", 500

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
