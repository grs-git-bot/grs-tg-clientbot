import os
import logging
from flask import Flask, request
from openai import OpenAI
import requests

# ---------------------------------------------------------
# 🔑 Логирование
# ---------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grs-tg-bot")

# ---------------------------------------------------------
# 🔑 Вспомогательная функция для переменных окружения
# ---------------------------------------------------------
def need(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value

# ---------------------------------------------------------
# 🔑 Ключи и токены
# ---------------------------------------------------------
TELEGRAM_TOKEN = need("TELEGRAM_TOKEN")
OPENAI_API_KEY = need("OPENAI_API_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# ---------------------------------------------------------
# 🔑 Клиенты
# ---------------------------------------------------------
client = OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)

# ---------------------------------------------------------
# 📤 Отправка сообщений в Telegram
# ---------------------------------------------------------
def send_message(chat_id: int, text: str):
    """
    Отправляет сообщение пользователю.
    Если сообщение > 4096 символов, делим на части.
    """
    MAX_LEN = 4096
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # делим длинный текст на куски
    chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]

    for chunk in chunks:
        payload = {"chat_id": chat_id, "text": chunk}
        r = requests.post(url, json=payload)
        if not r.ok:
            log.error(f"Ошибка отправки: {r.text}")
        else:
            log.info(f"Отправлено сообщение длиной {len(chunk)} символов")

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

    # ⚠️ фильтр — отвечаем только в приватных чатах
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
            max_completion_tokens=2000,   # ✅ увеличенный лимит
            temperature=0.7               # ✅ живость ответов
        )

        log.info(f"OpenAI raw response: {response}")

        reply_text = None
        if response.choices:
            choice = response.choices[0]
            if choice.message:
                reply_text = getattr(choice.message, "content", None)

        if not reply_text or reply_text.strip() == "":
            log.error(f"Пустой ответ от OpenAI: {response}")
            reply_text = "Извините, ответ пустой. Попробуйте ещё раз."

    except Exception as e:
        log.error(f"Ошибка OpenAI: {e}")
        reply_text = "Извините, что-то пошло не так."

    # отправляем ответ (с разбиением, если длинный)
    send_message(chat_id, reply_text)
    return "OK", 200

# ---------------------------------------------------------
# 🚀 Локальный запуск
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
