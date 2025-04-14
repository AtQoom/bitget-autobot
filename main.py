from flask import Flask, request, jsonify
import os
import requests
import hmac
import hashlib
import time
import json

app = Flask(__name__)

# 환경변수
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")

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

# 현재 환경변수 확인하기
print("✅ 환경변수 상태")
print("API_KEY:", API_KEY)
print("API_SECRET:", API_SECRET)
print("API_PASSPHRASE:", API_PASSPHRASE)

# 시간 처리기

def get_server_time():
    return str(int(time.time() * 1000))

# 서명 생성하기

def sign_request(timestamp, method, request_path, body=""):
    message = timestamp + method + request_path + body
    return hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

# 주문 실행하기

def place_order(direction, step):
    try:
        print(f"📥 주문 진입 요청: direction={direction}, step={step}")

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

        print(f"[Bitget 응답] 상태코드: {res.status_code}")
        print(f"[Bitget 응답 본문] {res.text}")

    except Exception as e:
        print("❌ 주문 중 예외 발생:", e)


# 청산 실행하기

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
    print(f"[청산 응답] {direction} {reason}: {res.text}")

# 웹하크 처리

@app.route("/", methods=["POST"])
def webhook():
    print("🚨 웹하크 함수 진입")
    try:
        data = request.get_json(force=True)
        print("🚀 웹하크 시간 수신 (RAW):", data)

        signal = data.get("signal", "")
        print("🧩 받은 signal:", signal)

        parts = signal.strip().split()
        print("🧩 분해된 parts:", parts)

        if len(parts) < 3:
            print("❌ 잘못된 시험 형식:", signal)
            return jsonify({"error": "Invalid signal format"}), 400

        action, direction, sub = parts[0], parts[1], parts[2]

        if action == "ENTRY" and sub == "STEP" and len(parts) == 4:
            step = parts[3]
            print("✅ 주문 실행:", direction, step)
            place_order(direction, step)

        elif action == "EXIT" and sub in ["TP1", "TP2", "SL_SLOW", "SL_HARD"]:
            print("✅ 청산 실행:", direction, sub)
            close_position(direction, sub)

        else:
            print("❌ 처리되지 않은 시간:", signal)
            return jsonify({"error": "Unhandled signal"}), 400

        return jsonify({"success": True})

    except Exception as e:
        print("❌ 예외 발생:", e)
        return jsonify({"success": False, "error": str(e)}), 500

# 실행문
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
