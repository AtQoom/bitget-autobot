from flask import Flask, request
import hmac, hashlib, time, json
import requests
import os

app = Flask(__name__)

# 환경변수 또는 직접 입력 (보안을 위해 환경변수 추천)
API_KEY = os.environ.get("bg_ff130b41cb44a15b7f8e9f0870bcd37e", "여기에_API_KEY")
API_SECRET = os.environ.get("90029771e071d6a374b0ed4b1aba13511e098111a5f229c8d11cfc92a991a659", "여기에_API_SECRET")
API_PASSPHRASE = os.environ.get("qoooooom", "여기에_API_PASSPHRASE")

BASE_URL = "https://api.bitget.com"

# 최근 주문 추적용 (중복 방지)
last_signal = {"id": None, "timestamp": 0}


def sign(secret, timestamp, method, request_path, body=''):
    pre_hash = f"{timestamp}{method.upper()}{request_path}{body}"
    return hmac.new(secret.encode(), pre_hash.encode(), hashlib.sha256).hexdigest()


@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    print("🚀 신호 수신됨:", data)

    # 중복 방지: order_id와 최근 시간 비교
    order_id = data.get("order_id")
    now = time.time()
    if order_id == last_signal["id"] and (now - last_signal["timestamp"] < 60):
        print("⚠️ 중복된 신호 무시됨.")
        return {"status": "duplicate"}, 200

    # 중복으로 처리되지 않으면 기록
    last_signal["id"] = order_id
    last_signal["timestamp"] = now

    signal = data.get("signal", "").upper()
    symbol = data.get("symbol", "SOLUSDT")
    size = float(data.get("order_contracts", 0.1))
    product_type = "umcbl"  # 무기한 USDT 계약
    margin_coin = "USDT"
    side = "buy" if "LONG" in signal else "sell"

    # 분할매수 수량 설정 (예: 20% / 20% / 30% / 30%)
    steps = [0.2, 0.2, 0.3, 0.3]

    for i, step in enumerate(steps, 1):
        step_size = round(size * step, 3)

        body_dict = {
            "symbol": symbol,
            "marginCoin": margin_coin,
            "orderType": "market",
            "side": side,
            "size": str(step_size),
            "productType": product_type
        }

        endpoint = "/api/mix/v1/order/placeOrder"
        url = BASE_URL + endpoint
        body = json.dumps(body_dict)
        timestamp = str(int(time.time() * 1000))
        signature = sign(API_SECRET, timestamp, "POST", endpoint, body)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": API_PASSPHRASE,
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, data=body)
        print(f"📦 STEP {i} 응답:", response.status_code, response.text)
        time.sleep(0.5)  # Bitget 제한을 고려한 딜레이

    return {"status": "ok"}, 200


@app.route("/")
def home():
    return "✅ 서버 정상 작동 중입니다!"
