from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    print("🚀 신호 수신됨:", data)
    
    # TODO: 여기에 Bitget API 주문 실행 로직을 넣으세요
    return {"status": "ok"}, 200

@app.route("/", methods=["GET"])
def home():
    return "✅ 서버 정상 작동 중입니다!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
