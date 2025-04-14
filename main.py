from flask import Flask, request, jsonify
import os
import requests
import hmac
import hashlib
import time
import json

app = Flask(__name__)

# 🔐 환경변수
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api.bitget.com"
symbol = "SOLUSDTUMCBL"
marginMode = "isolated"

tradeSide = {
    "LONG": "open_long",
    "SHORT": "open_short"
}
closeSide = {
    "LONG": "close_long",
    "SHORT": "close_short"
}

step_risk = {
    "1": 0.05,
    "2": 0.10,
    "3": 0.20,
    "4": 0.25
}

# ✅ 텔레그램 메시지
def send_telegram_message(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        res = requests.post(url, data=data)
        print("[텔레그램 응답]", res.status_code, res.text)
    except Exception as e:
        print("텔레그램 전송 오류:", e)

# ✅ 시간
def get_server_time():
    return str(int(time.time() * 1000))

# ✅ 서명 생성
def sign_request(timestamp, method, request_path, body=""):
    message = timestamp + method + request_path + body
    return hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

# ✅ 주문
def place_order(direction, step):
    size = step_risk.get(step)
    side = tradeSide.get(direction)
    if size is None or side is None:
        print("[에러] 유효하지 않은 진입 정보:", direction, step)
        return

    timestamp = get_server_time()
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": 1,
        "timeInForceValue": "normal"
    }
    body_json = json.dumps(body)
    path = "/api/v1/mix/order/placeOrder"
    sign = sign_request(timestamp, "POST", path, body_json)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    url = BASE_URL + path
    res = requests.post(url, headers=headers, data=body_json)

    # ✅ 여기 추가!
    print(f"[Bitget 응답] 상태코드: {res.status_code}")
    print(f"[Bitget 응답 본문] {res.text}")

    # 알림 (나중에 수정해도 됨)
    send_telegram_message(f"[진입] {direction} {step}단계 주문 응답: {res.text}")


# ✅ 청산
def close_position(direction, reason):
    side = closeSide.get(direction)
    if side is None:
        print("[에러] 유효하지 않은 청산 방향:", direction)
        return

    timestamp = get_server_time()
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": 0,
        "timeInForceValue": "normal"
    }
    body_json = json.dumps(body)
    path = "/api/v1/mix/order/closePosition"
    sign = sign_request(timestamp, "POST", path, body_json)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    url = BASE_URL + path
    res = requests.post(url, headers=headers, data=body_json)
    send_telegram_message(f"[청산] {direction} {reason} 청산 응답: {res.text}")

# ✅ 웹훅 처리
@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        print("🚀 웹훅 신호 수신됨:", data)

        signal = data.get("signal", "").strip()
        parts = signal.split()

        if len(parts) < 3:
            print("❌ 잘못된 신호 형식:", signal)
            return jsonify({"error": "Invalid signal format"}), 400

        action, direction, sub = parts[0], parts[1], parts[2]

        if action == "ENTRY" and sub == "STEP" and len(parts) == 4:
            step = parts[3]
            place_order(direction, step)

        elif action == "EXIT" and sub in ["TP1", "TP2", "SL_SLOW", "SL_HARD"]:
            close_position(direction, sub)

        else:
            print("❌ 처리되지 않은 신호:", signal)
            return jsonify({"error": "Unhandled signal"}), 400

        return jsonify({"success": True})

    except Exception as e:
        print("❌ 예외 발생:", e)
        send_telegram_message(f"[서버 오류] {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

# ✅ 실행
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
