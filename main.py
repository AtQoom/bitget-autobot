@app.route("/webhook", methods=["POST"])
def webhook():
    ...
    print("🔔 신호 수신: ", data)

    balance = get_wallet_balance()
    print("🪙 잔고 확인: ", balance)

    price = get_current_price()
    print("📉 현재가: ", price)

    qty = calculate_qty(order_id, balance, price)
    print("📦 주문 수량 계산 완료: ", qty)
