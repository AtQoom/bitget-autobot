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

def get_position_size(direction="LONG", retry=1):
    path = "/api/v2/mix/position/single-position?symbol=SOLUSDT&marginCoin=USDT"
    url = BASE_URL + path
    for _ in range(retry + 1):
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
            if r["code"] == "00000":
                data = r["data"]
                long_pos = float(data.get("long", {}).get("available", 0))
                short_pos = float(data.get("short", {}).get("available", 0))
                return long_pos if direction == "LONG" else short_pos
        except:
            pass
        time.sleep(0.5)
    return 0

def get_price():
    url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
    try:
        r = requests.get(url).json()
        return float(r["data"]["lastPr"])
    except:
        return 1.0

def get_max_position_size():
    url = BASE_URL + "/api/contract/v1/public/contracts"
    try:
        r = requests.get(url).json()
        for item in r.get("data", []):
            if item.get("symbol") == "SOLUSDT":
                return float(item.get("maxOpenAmount", 0))
    except:
        pass
    return None

def send_order(side, size, reduce_only=False, hold_side=None, trade_side=None):
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
        "tradeSide": trade_side,
        "holdSide": hold_side,
        "reduceOnly": "YES" if reduce_only else "NO"
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
    print("🔍 주문 요청 데이터:", data)
    res = requests.post(BASE_URL + path, headers=headers, data=body)
    print(f"📤 주문 ({side} {size}) {'[청산]' if reduce_only else '[진입]'} →", res.status_code, res.text)
    return res.json()

def place_entry(signal, equity, strength):
    is_long = "LONG" in signal
    direction = "buy" if is_long else "sell"
    leverage = 4
    price = get_price()
    base_risk = 0.24
    steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
    portion = 1 / steps
    raw_size = (equity * base_risk * leverage * strength * portion) / price
    max_size = (equity * 0.9 * portion) / price

    max_tier_size = get_max_position_size()
    if max_tier_size:
        max_size = min(max_size, max_tier_size)

    size = min(raw_size, max_size)
    size = round(max(size, 0.1), 1)

    if size * price < 5:
        print("❌ 진입 실패: 수량 부족", size)
        return {"error": "too small"}

    hold = "long" if is_long else "short"
    return send_order(direction, size, reduce_only=False, hold_side=hold, trade_side="open")

def place_exit(signal, strength):
    is_long = "LONG" in signal
    direction = "sell" if is_long else "buy"
    pos = get_position_size("LONG" if is_long else "SHORT", retry=1)
    if pos <= 0:
        print(f"⛔ 포지션 없음. {signal} → finalize_remaining()")
        return finalize_remaining(signal)

    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio
    size = pos
    if "TP1" in signal:
        size = round(pos * tp1_ratio, 1)
    elif "TP2" in signal:
        size = round(pos * tp2_ratio, 1)
    elif "SL_SLOW" in signal:
        size = round(pos * 0.5, 1)

    if size < 0.1:
        print("⚠️ 수량 너무 작음, finalize_remaining 대체 실행")
        return finalize_remaining(signal)

    hold = "long" if is_long else "short"
    return send_order(direction, size, reduce_only=True, hold_side=hold, trade_side="close")

def finalize_remaining(signal):
    is_long = "LONG" in signal
    direction = "sell" if is_long else "buy"
    size = get_position_size("LONG" if is_long else "SHORT", retry=1)
    if size is None:
        print("❗ 포지션 수량 조회 실패")
        return {"error": "no position info"}
    if 0 < size < 0.11:
        size = round(size, 1)
        print("🔄 잔여 포지션 전량 청산:", size)
        hold = "long" if is_long else "short"
        return send_order(direction, size, reduce_only=True, hold_side=hold, trade_side="close")
    return {"status": "done"}

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
