import os, time, hmac, hashlib, base64, json, requests, re
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
    try:
        path = "/api/v2/mix/account/account?symbol=SOLUSDT&productType=USDT-FUTURES&marginCoin=USDT"
        timestamp = str(int(time.time() * 1000))
        sign = sign_message(timestamp, "GET", path)
        res = requests.get(BASE_URL + path, headers={
            "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp, "ACCESS-PASSPHRASE": API_PASSPHRASE
        }).json()
        return float(res["data"]["accountEquity"]) if res.get("code") == "00000" else None
    except Exception as e:
        print("잔고 조회 오류:", e)
        return None

def get_position_size():
    try:
        path = "/api/v2/mix/position/single-position?symbol=SOLUSDT&marginCoin=USDT"
        timestamp = str(int(time.time() * 1000))
        sign = sign_message(timestamp, "GET", path)
        res = requests.get(BASE_URL + path, headers={
            "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp, "ACCESS-PASSPHRASE": API_PASSPHRASE
        }).json()
        return float(res["data"]["total"]) if res.get("code") == "00000" else 0
    except Exception as e:
        print("포지션 조회 오류:", e)
        return 0

def get_market_price():
    try:
        res = requests.get(BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES").json()
        return float(res["data"][0]["lastPr"]) if res.get("code") == "00000" else 1.0
    except:
        return 1.0

def send_order(side, size):
    try:
        timestamp = str(int(time.time() * 1000))
        path = "/api/v2/mix/order/place-order"
        body_data = {
            "symbol": "SOLUSDT", "marginCoin": "USDT", "side": side,
            "orderType": "market", "size": str(size), "price": "",
            "marginMode": "isolated", "productType": "USDT-FUTURES"
        }
        body = json.dumps(body_data, separators=(',', ':'))
        sign = sign_message(timestamp, "POST", path, body)
        headers = {
            "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp, "ACCESS-PASSPHRASE": API_PASSPHRASE,
            "Content-Type": "application/json"
        }
        res = requests.post(BASE_URL + path, headers=headers, data=body)
        print(f"📬 주문 응답 ({side} {size}):", res.status_code, res.text)
        return res.json()
    except Exception as e:
        print("❌ 주문 오류:", e)
        return {"error": str(e)}

def place_entry_order(signal, equity, strength):
    direction = "buy" if "LONG" in signal else "sell"
    leverage = 4
    price = get_market_price()
    base_risk = 0.24
    step = int(re.search(r"STEP (\d+)", signal).group(1)) if "STEP" in signal else 1
    steps = 1 if strength >= 2.0 else 3 if strength >= 1.6 else 5
    portion = 1 / steps
    raw_size = (equity * base_risk * leverage * strength * portion) / price
    max_size = (equity * 0.9 * portion) / price
    size = min(raw_size, max_size)
    size = floor(size * 10) / 10
    print(f"🧮 진입 계산: equity={equity}, price={price}, strength={strength}, portion={portion}, size={size}")
    if size < 0.1 or size * price < 5:
        print(f"❌ STEP {step} 주문 수량({size}) 또는 금액이 최소 기준에 미달")
        return {"error": "Below minimum size or value"}
    return send_order(direction, size)

def place_exit_order(signal, strength):
    direction = "sell" if "LONG" in signal else "buy"
    position_size = get_position_size()
    if position_size <= 0:
        print(f"⛔ 현재 포지션 없음. 스킵 가능성 ↑: {signal}")
        return {"skipped": True}

    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio
    portion = 1.0
    label = "FULL"

    if "TP1" in signal:
        portion = tp1_ratio
        label = "TP1"
    elif "TP2" in signal:
        portion = tp2_ratio
        label = "TP2"
    elif "SL_SLOW" in signal:
        portion = 0.5
        label = "SL_SLOW"
    elif "SL_HARD" in signal:
        portion = 1.0
        label = "SL_HARD"

    size = floor(position_size * portion * 10) / 10
    print(f"📤 청산 요청: {signal} | 현재 포지션: {position_size} → {label} 비율: {portion} → 수량: {size}")
    if size < 0.1 or size * get_market_price() < 5:
        print(f"⚠️ 청산 수량({size}) 부족으로 미체결 가능성")
        return {"skipped": True}
    return send_order(direction, size)

@app.route('/', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        print("📦 웹훅 수신:", data)
        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))
        if not signal:
            return "Missing signal", 400
        if "ENTRY" in signal:
            equity = get_equity()
            if equity is None:
                return "Balance error", 500
            result = place_entry_order(signal, equity, strength)
        elif "EXIT" in signal:
            result = place_exit_order(signal, strength)
        else:
            return "Unknown signal", 400
        return jsonify({"status": "order_sent", "result": result})
    except Exception as e:
        print("❌ 웹훅 처리 오류:", str(e))
        return "Internal error", 500

@app.route('/ping', methods=['GET'])
def ping():
    return "pong", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
