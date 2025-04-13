from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests
import json
import os

# ====== 환경변수 불러오기 (Fly.io secrets에서 설정됨) ======
API_KEY = os.environ.get("BITGET_API_KEY")
API_SECRET = os.environ.get("BITGET_API_SECRET")
API_PASSPHRASE = os.environ.get("BITGET_API_PASSPHRASE")

BASE_URL = "https://api.bitget.com"
SYMBOL = "SOLUSDT_UMCBL"

app = Flask(__name__)

# ====== 중복 신호 방지 ======
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

# ====== 현재 가격 조회 ======
def get_current_price(symbol):
    try:
        url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}"
        res = requests.get(url, timeout=5).json()
        return float(res["data"]["last"])
    except Exception as e:
        print(f"❌ 가격 조회 실패: {e}")
        return None

# ====== 잔고 조회 (예외 처리 추가) ======
def get_balance():
    path = "/api/mix/v1/account/accounts"
    url = BASE_URL + path + "?productType=umcbl"
    headers = get_auth_headers(API_KEY, API_SECRET, API_PASSPHRASE, "GET", path)
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status()
        data = res.json()
        if not data or "data" not in data or data["data"] is None:
            print("❌ 잔고 응답 이상:", data)
            return 0
        for item in data["data"]:
            if item["marginCoin"] == "USDT":
                return float(item["available"])
    except Exception as e:
        print("❌ 잔고 조회 오류:", e)
    return 0

# ====== 수량 계산 ======
def calculate_fixed_qty(step_index):
    fixed_qty = [0.6, 0.2, 0.1, 0.1]
    base_size = 5
    return round(base_size * fixed_qty[step_index], 3)

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

    step_map = {"STEP 1": 0, "STEP 2": 1, "STEP 3": 2, "STEP 4": 3}
    step_index = next((step_map[k] for k in step_map if k in signal), None)
    if step_index is None:
        return jsonify({"error": "Invalid step info"}), 400

    now = time.time()
    if order_id == last_signal_id and now - last_signal_time < signal_cooldown:
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
        return jsonify({"error": "Invalid side"}), 400

    price = get_current_price(SYMBOL)
    if not price:
        return jsonify({"error": "Price fetch failed"}), 500

    qty = calculate_fixed_qty(step_index)
    balance = get_balance()
    print(f"📊 현재 잔고: {balance} USDT / 주문 수량: {qty}")

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

    try:
        res = requests.post(url, headers=headers, data=body_json, timeout=10)
        print(f"✅ 주문 결과: {res.status_code} - {res.text}")
        return jsonify(res.json())
    except Exception as e:
        print("❌ 주문 요청 실패:", e)
        return jsonify({"error": "Order request failed"}), 500

@app.route("/")
def home():
    return "✅ Bitget 자동매매 서버 작동 중입니다!"

# ====== 실행 ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
