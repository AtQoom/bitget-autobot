from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests
import json
import os
from dotenv import load_dotenv

# ====== 환경변수 로드 ======
load_dotenv()

API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
BASE_URL = "https://api.bitget.com"
SYMBOL = "SOLUSDT_UMCBL"

app = Flask(__name__)

# ====== 중복 방지 ======
last_signal_id = None
last_signal_time = 0
signal_cooldown = 3  # 초

# ====== 인증 헤더 생성 ======
def get_auth_headers(api_key, api_secret, api_passphrase, method, path, body=''):
    timestamp = str(int(time.time() * 1000))
    prehash = f"{timestamp}{method.upper()}{path}{body}"
    sign = hmac.new(api_secret.encode(), prehash.encode(), hashlib.sha256).hexdigest()
    return {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": api_passphrase,
        "Content-Type": "application/json"
    }

# ====== 실시간 가격 조회 ======
def get_current_price(symbol):
    try:
        url = f"{BASE_URL}/api/mix/v1/market/ticker?symbol={symbol}"
        res = requests.get(url, timeout=5).json()
        return float(res["data"]["last"])
    except Exception as e:
        print("❌ 가격 조회 실패:", e)
        return None

# ====== 잔고 조회 (강화된 버전) ======
def get_balance():
    path = "/api/mix/v1/account/accounts?productType=UMCBL"
    url = BASE_URL + path
    headers = get_auth_headers(API_KEY, API_SECRET, API_PASSPHRASE, "GET", path)

    try:
        response = requests.get(url, headers=headers, timeout=10)
        print("📡 잔고 응답:", response.status_code, response.text)
        data = response.json()
    except Exception as e:
        print("❌ 잔고 조회 중 오류:", e)
        return 0

    if not data or "data" not in data or data["data"] is None:
        print("❌ 잔고 데이터가 유효하지 않음:", data)
        return 0

    for item in data["data"]:
        if item["marginCoin"] == "USDT":
            return float(item["available"])
    return 0

# ====== 수량 계산 ======
def calculate_order_qty(balance, price, leverage=3, risk_pct=0.09):
    return round((balance * risk_pct * leverage) / price, 2)

# ====== 웹훅 엔드포인트 ======
@app.route("/webhook", methods=["POST"])
def webhook():
    global last_signal_id, last_signal_time
    data = request.json
    print("🚀 웹훅 수신:", data)

    signal = data.get("signal", "").upper()
    order_id = data.get("order_id")
    order_action = data.get("order_action", "").lower()

    step_map = {"STEP 1": 0, "STEP 2": 1, "STEP 3": 2, "STEP 4": 3}
    step_index = next((v for k, v in step_map.items() if k in signal), None)
    if step_index is None:
        print("❌ STEP 정보가 없음")
        return jsonify({"error": "invalid step"}), 400

    now = time.time()
    if order_id == last_signal_id and now - last_signal_time < signal_cooldown:
        print("⚠️ 중복 신호 무시됨")
        return jsonify({"status": "duplicate skipped"}), 200

    last_signal_id = order_id
    last_signal_time = now

    action_type = "entry" if "ENTRY" in signal else "exit"
    side_map = {
        ("buy", "entry"): "open_long",
        ("sell", "entry"): "open_short",
        ("buy", "exit"): "close_long",
        ("sell", "exit"): "close_short"
    }
    side = side_map.get((order_action, action_type))
    if not side:
        print("❌ 잘못된 side 설정")
        return jsonify({"error": "invalid side"}), 400

    price = get_current_price(SYMBOL)
    if not price:
        return jsonify({"error": "price fetch failed"}), 500

    balance = get_balance()
    if balance <= 0:
        return jsonify({"error": "invalid balance"}), 500

    qty_total = calculate_order_qty(balance, price)

    # ✅ 비율
    ratios_entry = [0.6, 0.2, 0.1, 0.1]
    ratios_exit = [0.22, 0.20, 0.28, 0.30]
    ratio = ratios_entry[step_index] if action_type == "entry" else ratios_exit[step_index]
    qty = round(qty_total * ratio, 3)

    body = {
        "symbol": SYMBOL,
        "marginCoin": "USDT",
        "size": str(qty),
        "side": side,
        "orderType": "market",
        "timeInForceValue": "normal"
    }
    path = "/api/mix/v1/order/placeOrder"
    url = BASE_URL + path
    body_json = json.dumps(body)
    headers = get_auth_headers(API_KEY, API_SECRET, API_PASSPHRASE, "POST", path, body_json)
    res = requests.post(url, headers=headers, data=body_json)

    print("📦 주문 응답:", res.status_code, res.text)
    return jsonify(res.json())

@app.route("/")
def home():
    return "✅ 서버가 정상적으로 작동 중입니다."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
