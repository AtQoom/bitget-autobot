# Bybit Autobot (SOLUSDT.P 3M)

This project is a fully automated trading bot for Bybit SOLUSDT Perpetual,  
based on TradingView webhook alerts and Flask backend.

## Features
- 4-step split entry based on signal (Long/Short)
- Market orders using Bybit API (v5)
- Dynamic position sizing based on wallet balance
- Real-time price and slippage-adjusted quantity
- 3-second duplicate signal filter

## How to Deploy
1. Set your API keys in Fly.io:
   fly secrets set BYBIT_API_KEY="xxx" BYBIT_SECRET="yyy"

2. Deploy:
   fly deploy
