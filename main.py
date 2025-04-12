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
signal_cooldown = 3  # 초 단위 쿨다운

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
        url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}"
        res = requests.get(url, timeout=5).json()
        return float(res["data"]["last"])
    except Exception as e:
        print(f"❌ 가격 조회 오류: {e}")
        return None

# ====== 잔고 조회 ======
def get_balance():
    path = "/api/mix/v1/account/accounts?productType=UMCBL"
    url = BASE_URL + path
    headers = get_auth_headers(API_KEY, API_SECRET, API_PASSPHRASE, "GET", path)
    response = requests.get(url, headers=headers)
    data = response.json()
    if not data or data.get("data") is None:
        print("❌ 잔고 조회 실패 또는 응답 없음")
        return 0
    for item in data['data']:
        if item['marginCoin'] == 'USDT':
            return float(item['available'])
    return 0

# ====== 주문 수량 계산 ======
def calculate_order_qty(balance, price, leverage=3, risk_pct=0.09):
    return round((balance * risk_pct * leverage) / price, 2)

# ====== 웹훅 엔드포인트 ======
@app.route("/webhook", methods=["POST"])
def webhook():
    global last_signal_id, last_signal_time

    # 415 오류 방지: JSON or Form 둘 다 허용
    data = request.get_json(silent=True)
    if not data:
        data = request.form.to_dict()

    print("🚀 웹훅 신호 수신됨:", data)

    signal = data.get("signal", "").upper()
    order_id = data.get("order_id")
    order_action = data.get("order_action", "").lower()
    step_map = {"STEP 1": 0, "STEP 2": 1, "STEP 3": 2, "STEP 4": 3}
    step_index = next((step_map[k] for k in step_map if k in signal), None)

    if step_index is None:
        print("❌ STEP 정보 없음")
        return jsonify({"error": "invalid step info"}), 400

    # 중복 방지
    now = time.time()
    if order_id == last_signal_id and now - last_signal_time < signal_cooldown:
        print("⏱️ 중복 신호 무시됨")
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
        print("❌ 유효하지 않은 side 설정")
        return jsonify({"error": "invalid side"}), 400

    price = get_current_price(SYMBOL)
    if not price:
        return jsonify({"error": "price fetch failed"}), 500

    balance = get_balance()
    qty_total = calculate_order_qty(balance, price)

    # ✅ 마지막 전략과 동일한 분할 비율
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

    print(f"✅ 주문 결과: {res.status_code} - {res.text}")
    return jsonify(res.json())

@app.route("/")
def home():
    return "✅ 서버 정상 작동 중입니다!"

# ====== 실행 ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
