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
        return float(r["data"]["total"]) if r["code"] == "00000" else 0.0
    except:
        return 0.0

def get_price():
    url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
    try:
        r = requests.get(url).json()
        return float(r["data"][0]["lastPr"])
    except:
        return 1.0

def send_order(side, size, reduce_only=False):
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
        "reduceOnly": reduce_only,
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
    print(f"📤 주문 ({side} {size}) {'[청산]' if reduce_only else '[진입]'} →", res.status_code, res.text)
    return res.json()

def place_entry(signal, equity, strength):
    direction = "buy" if "LONG" in signal else "sell"
    leverage = 4
    base_risk = 0.12
    steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
    portion = 1 / steps
    price = get_price()
    raw_size = (equity * base_risk * leverage * strength * portion) / price
    size = round(min(raw_size, equity * 0.9 / price), 1)

    if size < 0.1:
        print("❌ 진입 실패: 수량 부족", size)
        return {"error": "too small"}

    return send_order(direction, size, reduce_only=False)

def place_exit(signal, strength):
    direction = "sell" if "LONG" in signal else "buy"
    pos = get_position_size()
    if pos <= 0:
        print(f"⛔ 포지션 없음. {signal}")
        return finalize_remaining(signal)

    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio
    if "TP1" in signal:
        size = round(pos * tp1_ratio, 1)
    elif "TP2" in signal:
        size = round(pos * tp2_ratio, 1)
    elif "SL_SLOW" in signal:
        size = round(pos * 0.5, 1)
    else:
        size = round(pos, 1)

    if size < 0.1:
        print("⚠️ 수량 너무 작음, 전량 청산 시도")
        return finalize_remaining(signal)

    return send_order(direction, size, reduce_only=True)

def finalize_remaining(signal):
    direction = "sell" if "LONG" in signal else "buy"
    size = get_position_size()
    if size <= 0:
        print("❗ 포지션 없음")
        return {"status": "no position"}
    size = round(size, 1)
    return send_order(direction, size, reduce_only=True)

@app.route('/', methods=['POST'])
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
            return "❓ Unknown signal", 400

        return jsonify({"status": "ok", "result": res})
    except Exception as e:
        print("❌ 처리 오류:", e)
        return "Error", 500

@app.route('/ping', methods=['GET'])
def ping():
    return "pong", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
