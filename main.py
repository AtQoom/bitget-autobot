import os, time, hmac, hashlib, base64, json
import requests
from flask import Flask, request, jsonify
from math import floor

app = Flask(__name__)

# 환경 변수
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
API_PASSPHRASE = os.environ.get("API_PASSPHRASE")
BASE_URL = "https://api.bitget.com"

# 서명 생성
def sign_message(timestamp, method, request_path, body=""):
    msg = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

# 현재가 조회
def get_price():
    url = BASE_URL + "/api/v2/mix/market/ticker?symbol=SOLUSDT&productType=USDT-FUTURES"
    try:
        r = requests.get(url).json()
        return float(r["data"][0]["lastPr"])
    except:
        return 0

# 포지션 정보
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
        if r["code"] == "00000" and isinstance(r["data"], list) and len(r["data"]) > 0:
            return r["data"][0]
    except:
        pass
    return {}

# 주문 실행
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

# 진입 처리
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

# 청산 처리
def execute_exit(signal, strength):
    pos = get_position()
    if not pos or float(pos.get("total", 0)) == 0:
        print("❌ 포지션 없음. 스킵")
        return {"skip": True}
    
    size = float(pos["total"])
    side = pos["holdSide"]
    direction = "sell" if side == "long" else "buy"
    tp1_ratio = min(max(0.3 + (strength - 1.0) * 0.3, 0.3), 0.6)
    tp2_ratio = 1.0 - tp1_ratio

    if "TP1" in signal:
        qty = floor(size * tp1_ratio * 10) / 10
    elif "TP2" in signal:
        qty = floor(size * tp2_ratio * 10) / 10
    elif "SL_SLOW" in signal:
        qty = floor(size * 0.5 * 10) / 10
    elif "SL_HARD" in signal:
        qty = floor(size * 10) / 10
    else:
        return {"error": "unknown signal"}

    if qty >= 0.1:
        return send_order(direction, qty)
    return {"skip": "too small"}

# 웹훅 수신
@app.route('/', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        signal = data.get("signal")
        strength = float(data.get("strength", 1.0))
        print("📦 수신:", signal, strength)

        if "ENTRY" in signal:
            eq = get_equity()
            if not eq:
                return "잔고 조회 실패", 500
            res = place_entry(signal, eq, strength)

        elif "EXIT" in signal:
            res = execute_exit(signal, strength)

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
