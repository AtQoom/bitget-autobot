import os, time, hmac, hashlib, base64, json
import requests
from flask import Flask, request, jsonify
from math import floor

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
API_PASSPHRASE = os.environ.get("API_PASSPHRASE")
BASE_URL = "https://api.bitget.com"

ENTRY_PRICE = {}

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
        return None

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
        if r["code"] == "00000" and r["data"]:
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
    return requests.post(BASE_URL + path, headers=headers, data=body).json()

def exit_by_target(direction, strength):
    pos = get_position()
    if not pos or float(pos.get("total", 0)) < 0.1:
        return {"skip": True}
    
    side = pos["holdSide"]
    entry_price = float(pos["openPrice"])
    size = float(pos["total"])
    
    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio
    tp1_qty = floor(size * tp1_ratio * 10) / 10
    tp2_qty = floor(size * tp2_ratio * 10) / 10
    sl_qty = floor(size * 0.5 * 10) / 10

    price = get_price()
    if not price:
        return {"error": "no price"}

    tp1 = entry_price * (1.0095 if side == "long" else 0.9905)
    tp2 = entry_price * (1.0225 if side == "long" else 0.9775)
    sl_slow = entry_price * (0.994 if side == "long" else 1.006)
    sl_hard = entry_price * (0.991 if side == "long" else 1.009)

    result = {}
    if side == "long":
        if price >= tp2:
            result = send_order("sell", tp2_qty)
        elif price >= tp1:
            result = send_order("sell", tp1_qty)
        elif price <= sl_slow:
            result = send_order("sell", sl_qty)
        elif price <= sl_hard:
            result = send_order("sell", size)
    elif side == "short":
        if price <= tp2:
            result = send_order("buy", tp2_qty)
        elif price <= tp1:
            result = send_order("buy", tp1_qty)
        elif price >= sl_slow:
            result = send_order("buy", sl_qty)
        elif price >= sl_hard:
            result = send_order("buy", size)
    return result

@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        signal = data.get("signal", "")
        strength = float(data.get("strength", 1.0))
        print("📦 Signal received:", signal, "| Strength:", strength)

        if "ENTRY" in signal:
            return jsonify({"status": "entry ignored (for now)"})
        elif "EXIT" in signal:
            result = exit_by_target(signal, strength)
            return jsonify(result)
        return "unknown", 400
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
