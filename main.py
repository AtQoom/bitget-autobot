import os, time, hmac, hashlib, base64, json, re
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

def get_price():
    url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
    try:
        r = requests.get(url).json()
        return float(r["data"][0]["lastPr"])
    except:
        return 1.0

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
        if r and r.get("code") == "00000" and isinstance(r.get("data"), list) and len(r["data"]) > 0:
            return r["data"][0]
        else:
            print("❗ get_position() 응답 없음 또는 오류:", r)
            return {}
    except Exception as e:
        print("❗ get_position() 예외:", e)
        return {}

def get_position_size():
    data = get_position()
    try:
        return float(data.get("total", 0))
    except:
        return 0

def get_position_direction():
    data = get_position()
    try:
        side = data.get("holdSide", None)
        if side not in ["long", "short"]:
            print("❗ holdSide 값 없음 또는 비정상:", side)
            return None
        return side
    except Exception as e:
        print("❗ holdSide 조회 오류:", e)
        return None

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

def place_entry(signal, equity, strength):
    direction = "buy" if "LONG" in signal else "sell"
    leverage = 4
    price = get_price()
    base_risk = 0.24
    steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
    portion = 1 / steps
    raw_size = (equity * base_risk * leverage * strength * portion) / price
    max_size = (equity * 0.9 * portion) / price
    size = min(raw_size, max_size)
    size = floor(size * 10) / 10
    if size < 0.1 or size * price < 5:
        print("❌ 진입 실패: 수량 부족")
        return {"error": "too small"}
    return send_order(direction, size)

def place_exit(signal, strength):
    pos = get_position_size()
    if pos <= 0:
        print(f"⛔ 포지션 없음. 스킵: {signal}")
        return {"skip": True}

    direction = "sell" if "LONG" in signal else "buy"
    pos_dir = get_position_direction()

    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio
    size = pos

    if "TP1" in signal or "TP2" in signal or "SL_SLOW" in signal:
        if pos_dir == "long" and direction == "sell":
            if "TP1" in signal:
                size = floor(pos * tp1_ratio * 10) / 10
            elif "TP2" in signal:
                size = floor(pos * tp2_ratio * 10) / 10
            elif "SL_SLOW" in signal:
                size = floor(pos * 0.5 * 10) / 10
            return send_order("sell", size)
        elif pos_dir == "short" and direction == "buy":
            if "TP1" in signal:
                size = floor(pos * tp1_ratio * 10) / 10
            elif "TP2" in signal:
                size = floor(pos * tp2_ratio * 10) / 10
            elif "SL_SLOW" in signal:
                size = floor(pos * 0.5 * 10) / 10
            return send_order("buy", size)

    print(f"⛔ 포지션 방향 불일치 또는 신호 없음. 스킵: {signal}")
    return {"skip": True}

def finalize_remaining(signal):
    direction = "sell" if "LONG" in signal else "buy"
    current_dir = get_position_direction()
    expected_dir = "long" if direction == "sell" else "short"
    if current_dir != expected_dir:
        print(f"⛔ 최종청산 방향 불일치 ({current_dir}). 스킵: {signal}")
        return {"skip": True}
    size = get_position_size()
    if 0 < size < 0.1:
        print("⚠️ 잔여 포지션 전량 청산:", size)
        return send_order(direction, floor(size * 10) / 10)
    return {"status": "done"}

@app.route('/', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))
        print("📦 수신:", data)
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

@app.route('/ping', methods=['GET'])
def ping():
    return "pong", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
