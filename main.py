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

# ====== 분할 주문 전송 ======
def send_split_order(side, price, signal_type):
    balance = get_balance()
    qty_total = calculate_order_qty(balance, price)

    # 비율 설정
    if signal_type == "entry":
        portions = [0.7, 0.1, 0.1, 0.1]  # 매수 진입
    elif signal_type == "exit":
        portions = [0.5, 0.2, 0.2, 0.1]  # 매도 청산
    else:
        return [{"error": "Invalid signal_type"}]

    responses = []

    for i, portion in enumerate(portions):
        qty = round(qty_total * portion, 2)
        body = {
            "symbol": SYMBOL,
            "marginCoin": "USDT",
            "size": str(qty),
            "side": side,
            "orderType": "market",
            "timeInForceValue": "normal",
            "price": ""
        }
        path = "/api/mix/v1/order/placeOrder"
        url = BASE_URL + path
        body_json = json.dumps(body)
        headers = get_auth_headers(API_KEY, API_SECRET, API_PASSPHRASE, "POST", path, body_json)
        res = requests.post(url, headers=headers, data=body_json)
        print(f"📦 STEP {i+1} 주문 결과: {res.status_code} - {res.text}")
        responses.append(res.json())
        time.sleep(0.2)

    return responses

# ====== 웹훅 처리 ======
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("🚀 웹훅 신호 수신됨:", data)

    signal = data.get("signal", "").upper()
    price = float(data.get("price", 0)) if "price" in data else 0

    if "ENTRY LONG" in signal:
        print("➡️ 롱 진입 요청 감지됨")
        res = send_split_order("open_long", price, "entry")

    elif "ENTRY SHORT" in signal:
        print("➡️ 숏 진입 요청 감지됨")
        res = send_split_order("open_short", price, "entry")

    elif "EXIT LONG" in signal:
        print("⬅️ 롱 청산 요청 감지됨")
        res = send_split_order("close_long", price, "exit")

    elif "EXIT SHORT" in signal:
        print("⬅️ 숏 청산 요청 감지됨")
        res = send_split_order("close_short", price, "exit")

    else:
        print("❌ 유효하지 않은 시그널:", signal)
        return jsonify({"error": "invalid signal"}), 400

    print("📦 주문 응답:", res)
    return jsonify(res)

@app.route("/")
def home():
    return "✅ 서버 정상 작동 중입니다!"

# ====== 필수: Flask 앱 실행 ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
