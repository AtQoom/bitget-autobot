from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests
import json
import os

app = Flask(__name__)

# ====== 환경변수 불러오기 ======
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ====== 환경변수 확인 로그 ======
print("✅ API_KEY:", "있음" if API_KEY else "없음")
print("✅ API_SECRET:", "있음" if API_SECRET else "없음")
print("✅ TELEGRAM_TOKEN:", "있음" if TELEGRAM_TOKEN else "없음")
print("✅ TELEGRAM_CHAT_ID:", "있음" if TELEGRAM_CHAT_ID else "없음")

# ====== 환경변수 누락 검사 ======
if not API_KEY or not API_SECRET:
    raise EnvironmentError("❌ BYBIT_API_KEY 또는 BYBIT_SECRET이 설정되지 않았습니다.")

# ====== 설정 ======
BASE_URL = "https://api.bybit.com"
SYMBOL = "SOLUSDT.P"
LEVERAGE = 3
SLIPPAGE = 0.0035  # 0.35%

executed_signals = set()  # 중복 방지
weight_map = {
    "Long 1": 0.70, "Long 2": 0.10, "Long 3": 0.10, "Long 4": 0.10,
    "Short 1": 0.30, "Short 2": 0.40, "Short 3": 0.20, "Short 4": 0.10
}

# ====== 텔레그램 알림 ======
def send_telegram(message):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        try:
            requests.post(url, data=payload, timeout=5)
        except Exception as e:
            print("⚠️ 텔레그램 전송 실패:", e)

# ====== 서명 생성 ======
def generate_signature(secret, params):
    sorted_params = sorted(params.items())
    query = "&".join([f"{k}={v}" for k, v in sorted_params])
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

# ====== 잔고 조회 ======
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
        return usdt_balance
    except Exception as e:
        print("❌ 잔고 조회 실패:", e)
        send_telegram(f"❌ 잔고 조회 실패: {e}")
        return 0

# ====== 현재가 조회 ======
def get_current_price():
    try:
        response = requests.get(f"{BASE_URL}/v5/market/tickers?category=linear&symbol={SYMBOL}", timeout=5)
        data = response.json()
        return float(data["result"]["list"][0]["lastPrice"])
    except Exception as e:
        print("❌ 현재가 조회 실패:", e)
        send_telegram(f"❌ 현재가 조회 실패: {e}")
        return None

# ====== 시장가 주문 ======
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
    sign = generate_signature(API_SECRET, params)
    params["sign"] = sign
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=params, headers=headers, timeout=10)
    return response

# ====== 수량 계산 ======
def calculate_qty(order_id, balance, price):
    weight = weight_map.get(order_id, 0)
    usdt_amount = balance * weight * LEVERAGE
    adjusted_qty = usdt_amount / (price * (1 + SLIPPAGE))
    return round(adjusted_qty, 3)

# ====== 웹훅 수신 ======
@app.route("/webhook", methods=["POST"])
def webhook():
    global executed_signals

    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": f"❌ JSON 파싱 실패: {e}"}), 400

    print("🚀 웹훅 신호 수신됨:", data)

    signal = data.get("signal", "").upper()
    order_id = data.get("order_id")
    order_action = data.get("order_action", "").lower()

    if not order_action or not order_id:
        return jsonify({"error": "❌ order_id 또는 order_action 누락됨"}), 400

    now = time.time()
    signal_key = f"{order_id}_{int(now)}"
    if signal_key in executed_signals:
        return jsonify({"status": "🟡 중복 신호 무시됨"}), 200
    executed_signals.add(signal_key)

    side = "buy" if order_action == "buy" else "sell"
    balance = get_wallet_balance()
    if balance == 0:
        return jsonify({"error": "❌ 잔고 부족"}), 500

    price = get_current_price()
    if not price:
        return jsonify({"error": "❌ 현재가 조회 실패"}), 500

    qty = calculate_qty(order_id, balance, price)
    print(f"📊 주문 수량 계산됨: {qty} (잔고: {balance}, 가격: {price})")

    try:
        response = place_market_order(side, SYMBOL, qty)
        send_telegram(f"✅ 주문 완료: {side.upper()} {qty} {SYMBOL}\n📉 가격: {price:.2f} | 💰 금액: {qty * price:.2f}")
        return jsonify(response.json())
    except Exception as e:
        send_telegram(f"❌ 주문 실패: {e}")
        return jsonify({"error": f"❌ 주문 실패: {e}"}), 500

# ====== 상태 확인용 ======
@app.route("/")
def home():
    return "✅ Bybit 자동매매 서버가 실행 중입니다."

@app.route("/ping")
def ping():
    return jsonify({"status": "alive", "timestamp": time.time()})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
