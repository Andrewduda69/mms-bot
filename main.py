from flask import Flask, request
import requests

app = Flask(__name__)

BOT_TOKEN = "8409956991:AAHtQm-3YY09DLjIGoTSqudtMd_wgq_d2FM"
CHAT_ID = "-5299312717"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    message = data.get("message", "Sygnał MMS!")
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": message})
    return "OK", 200

@app.route("/")
def index():
    return "MMS Bot działa!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
