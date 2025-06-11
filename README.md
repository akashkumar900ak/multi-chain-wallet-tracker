# Multi-Chain Wallet Tracker Bot

This is a Flask-based crypto wallet tracker that supports **Ethereum**, **Polygon**, and **BNB Chain**.

### 🌐 Features
- Track wallet addresses across multiple blockchains
- Real-time transaction alerts via Telegram
- Dashboard to add/view/remove tracked wallets
- Built with Flask, Web3.py, and TailwindCSS

### 🚀 Setup & Run

1. Clone the repo:
```bash
git clone https://github.com/yourusername/multi-chain-wallet-tracker.git
cd multi-chain-wallet-tracker
```

2. Install requirements:
```bash
pip install -r requirements.txt
```

3. Set environment variables:
```bash
export TELEGRAM_BOT_TOKEN=your-telegram-token
export TELEGRAM_CHAT_ID=your-chat-id
export ALCHEMY_API_KEY=your-alchemy-key
export PORT=5000
```

4. Run the app:
```bash
python wallet_tracker_multichain.py
```

### 🌍 Deploy on Render
- Connect to GitHub
- Set the start command: `python wallet_tracker_multichain.py`
- Use Web Service environment

---

**Developed with ❤️ by Akash**