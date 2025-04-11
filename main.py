from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests
import json

app = Flask(__name__)

# ====== 사용자 설정 ======
API_KEY = "YOUR_BITGET_API_KEY"
API_SECRET = "YOUR_BITGET_API_SECRET"
API_PASSPHRASE = "YOUR_API_PASSPHRASE"
BASE_URL = "https://api.bitget.com"
SYMBOL = "SOLUSDT_UMCBL"  # 비트겟 선물 심볼

# ====== 복리 수량 계산 함수 ======
def calculate_order_qty(balance, price, leverage=3, risk_pct=0.1):
    qty = (balance * risk_pct * leverage) / price
    return round(qty, 2)

# ====== 실시간 가격 조회 ======
def get_current_price(symbol):
    try:
        url = f"https://api.bitget.com/api/mix/v1/market/ticker?symbol={symbol}"
        res = requests.get(url, timeout=5).json()
        return float(res["data"]["last"])
    except Exception as e:
        print(f"❌ 가격 조회 오류: {e}")
        return None

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

# ====== 잔고 조회 ======
def get_balance():
    path = "/api/mix/v1/account/accounts?productType=UMCBL"
    url = BASE_URL + path
    headers = get_auth_headers(API_KEY, API_SECRET, API_PASSPHRASE, "GET", path)
    response = requests.get(url, headers=headers)
    data = response.json()
    for item in data['data']:
        if item['marginCoin'] == 'USDT':
            return float(item['available'])
    return 0

# ====== 단일 주문 실행 ======
def place_order(side, qty):
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
    return res.json()

# ====== 웹훅 처리 ======
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("🚀 웹훅 신호 수신됨:", data)

    signal = data.get("signal", "").upper()
    price = get_current_price(SYMBOL)

    if not price:
        print("❌ 실시간 가격 조회 실패")
        return jsonify({"error": "price fetch failed"}), 400

    balance = get_balance()
    qty = calculate_order_qty(balance, price)

    order_action = data.get("order_action", "").lower()
    action_type = "entry" if "ENTRY" in signal else "exit"
    side_map = {
        ("buy", "entry"): "open_long",
        ("sell", "entry"): "open_short",
        ("buy", "exit"): "close_long",
        ("sell", "exit"): "close_short"
    }
    side = side_map.get((order_action, action_type))

    if not side:
        print("❌ 올바르지 않은 side 설정")
        return jsonify({"error": "invalid side"}), 400

    res = place_order(side, qty)
    return jsonify(res)

@app.route("/")
def home():
    return "✅ 서버 정상 작동 중입니다!"

# ====== Flask 앱 실행 ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
