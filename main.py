from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests
import json
import os

app = Flask(__name__)

# ====== 환경변수 (Fly.io secrets에서 설정됨) ======
API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_SECRET")
BASE_URL = "https://api.bybit.com"
SYMBOL = "SOLUSDT.P"
LEVERAGE = 3
SLIPPAGE = 0.0035  # 0.35%

# ====== 중복 신호 방지 ======
last_signal_id = None
last_signal_time = 0
signal_cooldown = 3  # 초

# ====== 비율 기반 수량 ======
weight_map = {
    "Long 1": 0.70,
    "Long 2": 0.10,
    "Long 3": 0.10,
    "Long 4": 0.10,
    "Short 1": 0.30,
    "Short 2": 0.40,
    "Short 3": 0.20,
    "Short 4": 0.10
}

# ====== 잔고 기반 계산 (잔고 조회) ======
def get_wallet_balance():
    try:
        timestamp = str(int(time.time() * 1000))
        params = {
            "apiKey": API_KEY,
            "timestamp": timestamp,
            "accountType": "UNIFIED"
        }
        sign = generate_signature(API_SECRET, params)
        params["sign"] = sign
        headers = {"Content-Type": "application/json"}

        response = requests.get(f"{BASE_URL}/v5/account/wallet-balance", params=params, headers=headers, timeout=10)
        data = response.json()
        usdt_balance = 0
        for coin in data.get("result", {}).get("list", [])[0].get("coin", []):
            if coin["coin"] == "USDT":
                usdt_balance = float(coin["availableToTrade"])
                break
        return usdt_balance
    except Exception as e:
        print("❌ 잔고 조회 실패:", e)
        return 0

# ====== 현재가 조회 ======
def get_current_price():
    try:
        response = requests.get(f"{BASE_URL}/v5/market/tickers?category=linear&symbol={SYMBOL}", timeout=5)
        data = response.json()
        return float(data["result"]["list"][0]["lastPrice"])
    except Exception as e:
        print("❌ 현재가 조회 실패:", e)
        return None

# ====== 서명 생성 ======
def generate_signature(secret, params):
    sorted_params = sorted(params.items())
    query = "&".join([f"{k}={v}" for k, v in sorted_params])
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

# ====== 시장가 주문 요청 ======
def place_market_order(side, symbol, qty):
    url = f"{BASE_URL}/v5/order/create"
    timestamp = str(int(time.time() * 1000))

    params = {
        "apiKey": API_KEY,
        "symbol": symbol,
        "side": side.upper(),
        "orderType": "Market",
        "qty": str(qty),
        "timestamp": timestamp,
        "timeInForce": "GoodTillCancel"
    }
    params["sign"] = generate_signature(API_SECRET, params)
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=params, headers=headers, timeout=10)
    return response

# ====== 수량 계산 (슬리피지 반영) ======
def calculate_qty(order_id, balance, price):
    weight = weight_map.get(order_id, 0)
    usdt_amount = balance * weight * LEVERAGE
    adjusted_qty = usdt_amount / (price * (1 + SLIPPAGE))
    return round(adjusted_qty, 3)

# ====== 웹훅 처리 ======
@app.route("/webhook", methods=["POST"])
def webhook():
    global last_signal_id, last_signal_time

    try:
        data = request.get_json(force=True)
    except Exception as e:
        print("❌ JSON 파싱 실패:", e)
        return jsonify({"error": "Invalid JSON"}), 400

    print("🚀 웹훅 신호 수신됨:", data)

    signal = data.get("signal", "").upper()
    order_id = data.get("order_id")
    order_action = data.get("order_action", "").lower()

    now = time.time()
    if order_id == last_signal_id and now - last_signal_time < signal_cooldown:
        return jsonify({"status": "duplicate skipped"}), 200

    last_signal_id = order_id
    last_signal_time = now

    if not order_action or not order_id:
        return jsonify({"error": "Invalid webhook data"}), 400

    side = "buy" if order_action == "buy" else "sell"
    balance = get_wallet_balance()
    if balance == 0:
        return jsonify({"error": "Insufficient balance or failed to fetch"}), 500

    price = get_current_price()
    if not price:
        return jsonify({"error": "Price fetch failed"}), 500

    qty = calculate_qty(order_id, balance, price)
    print(f"📊 주문 수량: {qty} (잔고: {balance} USDT, 현재가: {price})")

    try:
        response = place_market_order(side, SYMBOL, qty)
        print(f"✅ 주문 응답: {response.status_code} - {response.text}")
        return jsonify(response.json())
    except Exception as e:
        print("❌ 주문 실패:", e)
        return jsonify({"error": "Order request failed"}), 500

@app.route("/")
def home():
    return "✅ Bybit 자동매매 서버 작동 중입니다!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
