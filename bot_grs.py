import os
import logging
from flask import Flask, request
from openai import OpenAI
import requests

# ---------------------------------------------------------
# 🔑 Настройка логирования
# ---------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grs-tg-bot")

# ---------------------------------------------------------
# 🔑 Вспомогательная функция: проверка переменных окружения
# ---------------------------------------------------------
def need(name: str) -> str:
    """Берёт переменную окружения или падает с ошибкой"""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            f"Локально — укажи её в .env, на Railway — в Variables."
        )
    return value

# ---------------------------------------------------------
# 🔑 Чтение ключей
# ---------------------------------------------------------
TELEGRAM_TOKEN = need("TELEGRAM_TOKEN")
OPENAI_API_KEY = need("OPENAI_API_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# ---------------------------------------------------------
# 🔑 Инициализация клиентов
# ---------------------------------------------------------
client = OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)

# ---------------------------------------------------------
# 📤 Отправка сообщений в Telegram
# ---------------------------------------------------------
def send_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    r = requests.post(url, json=payload)
    if not r.ok:
        log.error(f"Ошибка отправки: {r.text}")
    return r.json()

# ---------------------------------------------------------
# 📥 Обработчик вебхука
# ---------------------------------------------------------
@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = request.get_json(force=True)
    if not update:
        return "OK"

    message = update.get("message")
    if not message:
        return "OK"

    chat_id = message["chat"]["id"]
    chat_type = message["chat"]["type"]

    # отвечаем только в приватных чатах
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
            max_completion_tokens=500
        )

        # 🔎 Логируем весь ответ OpenAI (для отладки)
        log.info(f"OpenAI raw response: {response}")

        reply_text = None
        if response.choices:
            choice = response.choices[0]

            # вариант 1: message как dict
            if hasattr(choice, "message") and choice.message:
                if isinstance(choice.message, dict):
                    reply_text = choice.message.get("content")
                else:
                    reply_text = getattr(choice.message, "content", None)

            # вариант 2: text напрямую
            if not reply_text and hasattr(choice, "text"):
                reply_text = choice.text

        if not reply_text:
            log.error(f"Не удалось достать текст из ответа OpenAI: {response}")
            reply_text = "Извините, я не смог сгенерировать ответ."

    except Exception as e:
        log.error(f"Ошибка OpenAI: {e}")
        reply_text = "Извините, что-то пошло не так."

    send_message(chat_id, reply_text)
    return "OK", 200

# ---------------------------------------------------------
# 🚀 Локальный запуск
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
