import os, time, hmac, hashlib, base64, json
import requests
from flask import Flask, request, jsonify
from math import floor, ceil

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
API_PASSPHRASE = os.environ.get("API_PASSPHRASE")
BASE_URL = "https://api.bitget.com"

symbol = "SOLUSDT"
marginCoin = "USDT"
productType = "USDT-FUTURES"

def sign_message(timestamp, method, request_path, body=""):
    msg = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def get_headers(method, path, body=""):
    timestamp = str(int(time.time() * 1000))
    sign = sign_message(timestamp, method, path, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def get_equity():
    path = f"/api/v2/mix/account/account?symbol={symbol}&marginCoin={marginCoin}&productType={productType}"
    url = BASE_URL + path
    try:
        res = requests.get(url, headers=get_headers("GET", path)).json()
        return float(res["data"]["accountEquity"]) if res["code"] == "00000" else None
    except:
        return None

def get_price():
    url = f"{BASE_URL}/api/v2/mix/market/ticker?symbol={symbol}&productType={productType}"
    try:
        res = requests.get(url).json()
        return float(res["data"][0]["lastPr"])
    except:
        return 1.0

def get_position_size():
    path = f"/api/v2/mix/position/single-position?symbol={symbol}&marginCoin={marginCoin}"
    url = BASE_URL + path
    try:
        res = requests.get(url, headers=get_headers("GET", path)).json()
        return float(res["data"]["total"]) if res["code"] == "00000" else 0
    except:
        return 0

def send_order(side, size):
    path = "/api/v2/mix/order/place-order"
    url = BASE_URL + path
    body_dict = {
        "symbol": symbol,
        "marginCoin": marginCoin,
        "orderType": "market",
        "side": side,
        "size": str(size),
        "price": "",
        "marginMode": "isolated",
        "productType": productType
    }
    body = json.dumps(body_dict, separators=(',', ':'))
    headers = get_headers("POST", path, body)
    res = requests.post(url, headers=headers, data=body)
    print(f"📤 주문 ({side} {size}):", res.status_code, res.text)
    return res.json()

def place_entry(signal, equity, strength):
    direction = "buy" if "LONG" in signal else "sell"
    leverage = 4
    base_risk = 0.24
    price = get_price()

    steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
    total_qty = (equity * base_risk * leverage * strength) / price
    step_qty = round(total_qty / steps, 1)

    if step_qty < 0.1 or step_qty * price < 5:
        print(f"❌ 진입 실패: step 수량 {step_qty} SOL 부족")
        return {"error": "too small"}

    return send_order(direction, step_qty)

def place_exit(signal, strength):
    direction = "sell" if "LONG" in signal else "buy"
    pos = get_position_size()
    if pos <= 0:
        print(f"⛔ 포지션 없음. 스킵: {signal}")
        return {"skip": True}

    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.65)
    tp2_ratio = 1.0 - tp1_ratio

    if "TP1" in signal:
        size = round(pos * tp1_ratio, 1)
    elif "TP2" in signal:
        size = round(pos * tp2_ratio, 1)
    elif "SL_SLOW" in signal:
        size = round(pos * 0.5, 1)
    elif "SL_HARD" in signal:
        size = round(pos, 1)
    else:
        size = round(pos, 1)

    if size < 0.1:
        print(f"⚠️ 청산 수량 {size} SOL 너무 적음 → 스킵")
        return {"skip": True}

    return send_order(direction, size)

def finalize_remaining(signal):
    direction = "sell" if "LONG" in signal else "buy"
    pos = get_position_size()
    if 0 < pos < 0.1:
        size = round(pos, 1)
        print(f"⚠️ 잔여 포지션 강제 청산: {size} SOL")
        return send_order(direction, size)
    return {"status": "no_remain"}

@app.route('/', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))
        print(f"📦 수신: {signal} | strength={strength}")

        equity = get_equity()
        if equity is None:
            return "잔고 조회 실패", 500

        if "ENTRY" in signal:
            res = place_entry(signal, equity, strength)

        elif "EXIT" in signal:
            res = place_exit(signal, strength)
            finalize_remaining(signal)

        else:
            return "Unknown signal", 400

        return jsonify({"status": "ok", "result": res})

    except Exception as e:
        print("❌ 오류:", e)
        return "Error", 500

@app.route('/ping', methods=['GET'])
def ping():
    return "pong", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
