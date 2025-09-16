import os
import logging
from flask import Flask, request
from dotenv import load_dotenv
from openai import OpenAI   # новый официальный SDK
import requests

# Загружаем переменные окружения (.env локально, Variables на Railway)
load_dotenv()

# Логирование
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grs-tg-bot")

def need(name: str) -> str:
    """Достаёт переменную окружения или падает с ошибкой, если её нет"""
    val = os.getenv(name)
    if not val:
        log.error(f"ENV MISSING: {name}. Проверь Variables у сервиса web и сделай Redeploy.")
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            f"Локально — положи в .env, на Railway — добавь в Variables."
        )
    return val

# Переменные окружения
TELEGRAM_TOKEN = need("TELEGRAM_TOKEN")
OPENAI_API_KEY = need("OPENAI_API_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Инициализация OpenAI SDK (новый клиент)
client = OpenAI(api_key=OPENAI_API_KEY)

# Flask-приложение
app = Flask(__name__)

# Отправка сообщения в Telegram
def send_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    resp = requests.post(url, json=payload)
    if resp.status_code != 200:
        log.error(f"Ошибка отправки: {resp.text}")

# Корень — для проверки доступности
@app.route("/", methods=["GET"])
def root():
    return "OK", 200

# Webhook
@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    # Проверка секрета
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        log.warning("Неверный секрет вебхука")
        return "Forbidden", 403

    update = request.get_json(force=True)
    message = update.get("message")
    if not message:
        return "OK"

    chat_id = message["chat"]["id"]
    chat_type = message["chat"]["type"]  # private, group, channel, supergroup

    # 🔑 Фильтр: отвечаем только в личных чатах
    if chat_type != "private":
        log.info(f"Ignored update from chat_type={chat_type}, id={chat_id}")
        return "OK"

    user_text = message.get("text", "")
    if not user_text:
        return "OK"

    log.info(f"User {chat_id} wrote: {user_text}")

   try:
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": user_text}],
        max_completion_tokens=1000
    )

    # безопасно достаём текст ответа
    if response.choices and response.choices[0].message:
        reply_text = response.choices[0].message.content or "Извините, я не смог сгенерировать ответ."
    else:
        reply_text = "Извините, я не смог сгенерировать ответ."

except Exception as e:
    log.error(f"Ошибка OpenAI: {e}")
    reply_text = "Извините, что-то пошло не так."

    send_message(chat_id, reply_text)
    return "OK", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
