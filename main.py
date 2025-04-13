from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests
import json
import os

# ====== 환경변수 직접 설정 ======
API_KEY = os.environ.get("BITGET_API_KEY")
API_SECRET = os.environ.get("BITGET_API_SECRET")
API_PASSPHRASE = os.environ.get("BITGET_API_PASSPHRASE")

BASE_URL = "https://api.bitget.com"
SYMBOL = "SOLUSDT_UMCBL"  # 비트겟 선물 심볼

app = Flask(__name__)

# ====== 중복 방지 ======
last_signal_id = None
last_signal_time = 0
signal_cooldown = 3  # 초 단위 쿨다운

# ====== 인증 헤더 생성 ======
def get_auth_headers(api_key, api_secret, api_passphrase, method, path, body=''):
    if not all([api_key, api_secret, api_passphrase]):
        raise ValueError("❌ Bitget API 키 또는 패스프레이즈가 누락되었습니다. 환경변수 설정을 확인하세요.")

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

# ====== 주문 수량 계산 ======
def calculate_fixed_qty(step_index, price):
    fixed_qty = [0.6, 0.2, 0.1, 0.1]  # 수량 비율 고정
    base_size = 5  # 기본 주문 수량 기준값
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
        print("❌ STEP 정보 없음")
        return jsonify({"error": "invalid step info"}), 400

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

    qty = calculate_fixed_qty(step_index, price)

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

    try:
        headers = get_auth_headers(API_KEY, API_SECRET, API_PASSPHRASE, "POST", path, body_json)
        print("💡 요청 보낼 URL:", url)
        print("💡 요청 바디:", body_json)
        print("💡 요청 헤더:", headers)

        res = requests.post(url, headers=headers, data=body_json)
        print(f"✅ 주문 결과: {res.status_code} - {res.text}")

        try:
            result = res.json()
        except Exception as e:
            print("❌ 응답 JSON 파싱 실패:", e)
            return jsonify({"error": "invalid response from Bitget"}), 502

        return jsonify(result)

    except Exception as e:
        print("❌ Bitget 주문 요청 중 에러:", e)
        return jsonify({"error": "bitget request failed"}), 502

@app.route("/")
def home():
    return "✅ 서버 정상 작동 중입니다!"

# ====== 앱 실행 ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
