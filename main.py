import os, time, hmac, hashlib, base64, json, requests, re
from flask import Flask, request, jsonify
from math import floor

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
API_PASSPHRASE = os.environ.get("API_PASSPHRASE")
BASE_URL = "https://api.bitget.com"

# === 전역 포지션 정보 저장
position_info = {
    "side": None,
    "entry_price": None,
    "strength": None
}

def sign_message(timestamp, method, request_path, body=""):
    message = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def get_equity():
    try:
        method = "GET"
        query = "symbol=SOLUSDT&productType=USDT-FUTURES&marginCoin=USDT"
        path = f"/api/v2/mix/account/account?{query}"
        timestamp = str(int(time.time() * 1000))
        sign = sign_message(timestamp, method, path)
        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": API_PASSPHRASE
        }
        res = requests.get(BASE_URL + path, headers=headers).json()
        return float(res["data"]["accountEquity"]) if res["code"] == "00000" else None
    except:
        return None

def get_position_size():
    try:
        method = "GET"
        path = "/api/v2/mix/position/single-position?symbol=SOLUSDT&marginCoin=USDT"
        timestamp = str(int(time.time() * 1000))
        sign = sign_message(timestamp, method, path)
        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": API_PASSPHRASE
        }
        res = requests.get(BASE_URL + path, headers=headers).json()
        return float(res["data"]["total"]) if res["code"] == "00000" else 0
    except:
        return 0

def get_market_price():
    try:
        url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
        res = requests.get(url).json()
        return float(res["data"][0]["lastPr"]) if res["code"] == "00000" else 1.0
    except:
        return 1.0

def send_order(side, size):
    timestamp = str(int(time.time() * 1000))
    path = "/api/v2/mix/order/place-order"
    method = "POST"
    body_data = {
        "symbol": "SOLUSDT", "marginCoin": "USDT", "side": side,
        "orderType": "market", "size": str(size), "price": "",
        "marginMode": "isolated", "productType": "USDT-FUTURES"
    }
    body = json.dumps(body_data, separators=(',', ':'))
    sign = sign_message(timestamp, method, path, body)
    headers = {
        "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp, "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }
    res = requests.post(BASE_URL + path, headers=headers, data=body)
    print(f"📬 주문 응답 ({side} {size}):", res.status_code, res.text)
    return res.json()

def place_entry(signal, equity, strength):
    direction = "buy" if "LONG" in signal else "sell"
    leverage = 4
    price = get_market_price()
    base_risk = 0.24
    steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
    portion = 1 / steps
    raw_size = (equity * base_risk * leverage * strength * portion) / price
    max_size = (equity * 0.9 * portion) / price
    size = floor(min(raw_size, max_size) * 10) / 10
    if size < 0.1 or size * price < 5:
        print("❌ 주문 수량 미달:", size)
        return {"error": "size too small"}

    # 포지션 정보 저장
    position_info["side"] = "LONG" if "LONG" in signal else "SHORT"
    position_info["entry_price"] = price
    position_info["strength"] = strength
    print(f"💾 진입가 저장: {position_info}")
    return send_order(direction, size)

def check_exit_conditions():
    entry_price = position_info["entry_price"]
    direction = position_info["side"]
    strength = position_info["strength"]
    size = get_position_size()
    price = get_market_price()

    if entry_price is None or direction is None or size == 0:
        return

    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio
    tp1_price = entry_price * (1 + 0.0095 if direction == "LONG" else 1 - 0.0095)
    tp2_price = entry_price * (1 + 0.0225 if direction == "LONG" else 1 - 0.0225)
    sl_price = entry_price * (1 - 0.006 if direction == "LONG" else 1 + 0.006)

    print(f"🔎 현재가: {price:.4f}, TP1: {tp1_price:.4f}, TP2: {tp2_price:.4f}, SL: {sl_price:.4f}")

    if direction == "LONG":
        if price >= tp2_price:
            return send_order("sell", floor(size * tp2_ratio * 10) / 10)
        elif price >= tp1_price:
            return send_order("sell", floor(size * tp1_ratio * 10) / 10)
        elif price <= sl_price:
            return send_order("sell", floor(size * 0.5 * 10) / 10)
    else:
        if price <= tp2_price:
            return send_order("buy", floor(size * tp2_ratio * 10) / 10)
        elif price <= tp1_price:
            return send_order("buy", floor(size * tp1_ratio * 10) / 10)
        elif price >= sl_price:
            return send_order("buy", floor(size * 0.5 * 10) / 10)

@app.route('/', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        print("📦 웹훅 수신:", data)
        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))

        if "ENTRY" in signal:
            equity = get_equity()
            if equity is None:
                return "잔고 조회 오류", 500
            result = place_entry(signal, equity, strength)
        return jsonify({"status": "received"})
    except Exception as e:
        print("❌ 웹훅 오류:", str(e))
        return "error", 500

@app.route('/monitor', methods=['GET'])
def monitor():
    try:
        check_exit_conditions()
        return jsonify({"status": "checked"})
    except Exception as e:
        return str(e), 500

@app.route('/ping', methods=['GET'])
def ping():
    return "pong", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
