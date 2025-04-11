from flask import Flask, request

app = Flask(__name__)

@app.route('/', methods=['POST'])
def webhook():
    data = request.get_json()
    print("신호 수신:", data)
    # TODO: Bitget API 호출 로직 추가
    return {'status': 'ok'}, 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

@app.route("/")
def home():
    return "서버가 정상 작동 중입니다!"
