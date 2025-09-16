import os
import logging
from flask import Flask, request
from openai import OpenAI
import requests

# ---------------------------------------------------------
# 🔑 Настройка логирования (чтобы видеть, что делает бот)
# ---------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grs-tg-bot")

# ---------------------------------------------------------
# 🔑 Вспомогательная функция: проверка обязательных переменных
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
# 🔑 Чтение ключей из окружения
# ---------------------------------------------------------
TELEGRAM_TOKEN = need("TELEGRAM_TOKEN")    # токен Telegram-бота
OPENAI_API_KEY = need("OPENAI_API_KEY")    # ключ OpenAI
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # необязательный секрет для вебхука

# ---------------------------------------------------------
# 🔑 Инициализация клиентов
# ---------------------------------------------------------
client = OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)

# ---------------------------------------------------------
# 📤 Отправка сообщений в Telegram
# ---------------------------------------------------------
def send_message(chat_id: int, text: str):
    """Отправляет сообщение пользователю в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    r = requests.post(url, json=payload)
    if not r.ok:
        log.error(f"Ошибка отправки: {r.text}")
    return r.json()

# ---------------------------------------------------------
# 📥 Обработчик вебхука (сюда шлёт Telegram)
# ---------------------------------------------------------
@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    # 1. Получаем обновление
    update = request.get_json(force=True)
    if not update:
        return "OK"

    message = update.get("message")
    if not message:
        return "OK"

    chat_id = message["chat"]["id"]
    chat_type = message["chat"]["type"]  # "private", "group", "supergroup", "channel"

    # 2. Фильтр: отвечаем только в приватных чатах
    if chat_type != "private":
        log.info(f"Ignored update from chat_type={chat_type}, id={chat_id}")
        return "OK"

    user_text = message.get("text", "")
    if not user_text:
        return "OK"

    log.info(f"User {chat_id} wrote: {user_text}")

    # 3. Запрос в OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-5-mini",  # модель
            messages=[{"role": "user", "content": user_text}],
            max_completion_tokens=1500  # ограничение длины ответа
        )

        # 4. Универсальное извлечение текста из ответа
        reply_text = None
        if response.choices:
            choice = response.choices[0]

            # иногда это объект с полем .message
            if hasattr(choice, "message") and choice.message:
                if isinstance(choice.message, dict):
                    reply_text = choice.message.get("content")
                else:
                    reply_text = getattr(choice.message, "content", None)

            # иногда бывает просто text
            elif hasattr(choice, "text"):
                reply_text = choice.text

        # если по каким-то причинам текст пустой → fallback
        if not reply_text:
            reply_text = "Извините, я не смог сгенерировать ответ."

    except Exception as e:
        log.error(f"Ошибка OpenAI: {e}")
        reply_text = "Извините, что-то пошло не так."

    # 5. Отправляем ответ пользователю
    send_message(chat_id, reply_text)
    return "OK", 200

# ---------------------------------------------------------
# 🚀 Точка входа (локальный запуск)
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
