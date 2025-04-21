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

def get_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    sign = sign_message(ts, method, path, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def get_equity():
    path = "/api/v2/mix/account/account?symbol=SOLUSDT&marginCoin=USDT&productType=USDT-FUTURES"
    r = requests.get(BASE_URL + path, headers=get_headers("GET", path)).json()
    return float(r["data"]["accountEquity"]) if r["code"] == "00000" else None

def get_price():
    url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
    r = requests.get(url).json()
    return float(r["data"][0]["lastPr"])

def get_position():
    path = "/api/v2/mix/position/single-position?symbol=SOLUSDT&marginCoin=USDT&productType=USDT-FUTURES"
    r = requests.get(BASE_URL + path, headers=get_headers("GET", path)).json()
    return r["data"][0] if r.get("code") == "00000" and isinstance(r.get("data"), list) else {}

def get_position_size():
    return float(get_position().get("total", 0))

def get_position_direction():
    return get_position().get("holdSide")

def send_order(side, size):
    path = "/api/v2/mix/order/place-order"
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
    r = requests.post(BASE_URL + path, headers=get_headers("POST", path, body), data=body)
    print("📤 주문:", side, size, r.status_code, r.text)
    return r.json()

@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        signal = data.get("signal", "")
        strength = float(data.get("strength", 1.0))
        print("📥 웹훅 수신:", signal, strength)

        if "ENTRY" in signal:
            equity = get_equity()
            price = get_price()
            leverage = 4
            risk_pct = 0.24
            steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
            portion = 1 / steps
            raw_size = (equity * risk_pct * leverage * strength * portion) / price
            max_size = (equity * 0.9 * portion) / price
            size = floor(min(raw_size, max_size) * 10) / 10
            if size < 0.1:
                print("⛔ 진입 실패: 수량 부족")
                return jsonify({"error": "too small"}), 200
            side = "buy" if "LONG" in signal else "sell"
            return jsonify(send_order(side, size))

        elif "EXIT" in signal:
            pos_dir = get_position_direction()
            pos_size = get_position_size()
            if pos_size <= 0 or not pos_dir:
                return jsonify({"skip": True})

            # SL_SLOW은 50% 청산
            if "SL_SLOW" in signal:
                side = "sell" if pos_dir == "long" else "buy"
                qty = floor(pos_size * 0.5 * 10) / 10
                if qty >= 0.1:
                    return jsonify(send_order(side, qty))
                else:
                    return jsonify({"skip": True})

            # TP1 / TP2 비중 계산
            tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
            tp2_ratio = 1.0 - tp1_ratio
            side = "sell" if pos_dir == "long" else "buy"
            ratio = tp1_ratio if "TP1" in signal else tp2_ratio
            qty = floor(pos_size * ratio * 10) / 10
            if qty >= 0.1:
                return jsonify(send_order(side, qty))
            else:
                return jsonify({"skip": True})

        return jsonify({"status": "ignored"})
    except Exception as e:
        print("❌ 예외 발생:", e)
        return "error", 500

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
