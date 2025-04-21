import os, time, hmac, hashlib, base64, json, threading
import requests
from flask import Flask, request, jsonify
from math import floor

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
API_PASSPHRASE = os.environ.get("API_PASSPHRASE")
BASE_URL = "https://api.bitget.com"

active_position = None  # 현재 진입 정보 저장

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

def tp_sl_loop():
    global active_position
    while True:
        if active_position:
            now = time.time()
            price = get_price()
            entry = active_position
            side = entry["side"]
            entry_price = entry["price"]
            qty = entry["qty"]
            strength = entry["strength"]
            elapsed = now - entry["timestamp"]

            tp1 = entry_price * (1.0095 if side == "long" else 0.9905)
            tp2 = entry_price * (1.0225 if side == "long" else 0.9775)
            sl1 = entry_price * (0.994 if side == "long" else 1.006)
            sl2 = entry_price * (0.991 if side == "long" else 1.009)

            tp1_size = floor(qty * 0.3 * 10) / 10
            tp2_size = floor(qty * 0.7 * 10) / 10
            sl1_size = floor(qty * 0.5 * 10) / 10

            if side == "long":
                if price <= sl1:
                    send_order("sell", sl1_size)
                if price <= sl2:
                    send_order("sell", qty)
                    active_position = None
                if price >= tp1:
                    send_order("sell", tp1_size)
                if price >= tp2:
                    send_order("sell", tp2_size)
                    active_position = None
            else:
                if price >= sl1:
                    send_order("buy", sl1_size)
                if price >= sl2:
                    send_order("buy", qty)
                    active_position = None
                if price <= tp1:
                    send_order("buy", tp1_size)
                if price <= tp2:
                    send_order("buy", tp2_size)
                    active_position = None
        time.sleep(1)

@app.route("/", methods=["POST"])
def webhook():
    global active_position
    try:
        data = request.get_json(force=True)
        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))
        print("📦 웹훅 수신:", data)

        if "ENTRY" in signal:
            if active_position:
                print("🚫 이미 포지션 있음, 무시")
                return jsonify({"status": "ignored"})

            direction = "buy" if "LONG" in signal else "sell"
            side = "long" if "LONG" in signal else "short"
            leverage = 4
            eq = 100  # 필요시 get_equity() 대체 가능
            price = get_price()
            steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
            portion = 1 / steps
            raw_size = (eq * 0.24 * leverage * strength * portion) / price
            qty = floor(raw_size * 10) / 10

            res = send_order(direction, qty)
            active_position = {
                "side": side,
                "price": price,
                "qty": qty,
                "strength": strength,
                "timestamp": time.time()
            }
            return jsonify({"status": "entered", "price": price, "qty": qty})
        else:
            return "신호 무시됨", 200
    except Exception as e:
        print("❌ 오류:", e)
        return "Error", 500

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

# TP/SL 루프 실행
threading.Thread(target=tp_sl_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
