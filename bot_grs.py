# bot_grs.py
# --------------------------------------------
# Назначение: простой и надёжный Telegram-бот.
# - Принимает апдейты через Webhook (Flask)
# - Генерирует ответ через OpenAI (официальный SDK v1)
# - Отправляет ответ пользователю через Telegram Bot API
# - Ключи/секреты читаем из окружения (локально — .env)
# --------------------------------------------

import os
import logging
from typing import Any, Dict, Iterable, Optional

import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv  # локально подтянет .env, на Railway не мешает
from openai import OpenAI

# ========== 1) Конфигурация и окружение ==========

# Локально: .env должен лежать в корне проекта и НЕ быть в гите (.gitignore).
# На Railway: .env не нужен — всё задаём в Variables UI.
load_dotenv()  # безопасно: если .env нет — просто ничего не сделает

def need(name: str) -> str:
    """
    Достаёт обязательную переменную из окружения.
    Если переменной нет — падаем с понятной ошибкой.
    """
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            f"Локально — положи в .env, на Railway — добавь в Variables."
        )
    return val

# Обязательные переменные:
TELEGRAM_TOKEN = need("TELEGRAM_TOKEN")      # токен бота
OPENAI_API_KEY = need("OPENAI_API_KEY")      # ключ OpenAI

# Необязательная (но рекомендуемая) переменная:
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # секрет проверки заголовка вебхука

# Инициализация OpenAI SDK v1 (официальный клиент)
client = OpenAI(api_key=OPENAI_API_KEY)

# Базовый URL Telegram Bot API для отправки сообщений
TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Telegram ограничение на длину текста: 4096 символов
TG_LIMIT = 4096

# Базовое логирование (без вывода секретов!)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grs-tg-bot")

# Flask-приложение (веб-сервер для вебхука)
app = Flask(__name__)


# ========== 2) Вспомогательные функции для Telegram ==========

def tg_send_action(chat_id: int, action: str = "typing") -> None:
    """
    Показать в чате индикатор "бот печатает".
    Это необязательно, но улучшает UX.
    """
    try:
        requests.post(
            f"{TG_API}/sendChatAction",
            json={"chat_id": chat_id, "action": action},
            timeout=10,
        )
    except Exception as e:
            # Не критично, просто логируем
            log.warning(f"sendChatAction failed: {e}")

def split_for_telegram(text: str, limit: int = TG_LIMIT) -> Iterable[str]:
    """
    Делит длинный текст на безопасные куски <= 4096 символов.
    Старается резать по переносу/пробелу, но при необходимости режет жёстко.
    """
    if len(text) <= limit:
        yield text
        return

    start = 0
    n = len(text)
    while start < n:
        end = min(start + limit, n)
        cut = text.rfind("\n", start, end)
        if cut == -1:
            cut = text.rfind(" ", start, end)
        if cut == -1 or cut <= start:
            cut = end
        chunk = text[start:cut].rstrip()
        if chunk:
            yield chunk
        start = cut

def tg_send_text(chat_id: int, text: str, parse_mode: Optional[str] = None) -> None:
    """
    Отправляет текст в один или несколько сообщений, учитывая лимит Telegram.
    """
    for part in split_for_telegram(text):
        payload = {"chat_id": chat_id, "text": part}
        if parse_mode:
            payload["parse_mode"] = parse_mode  # например, "MarkdownV2" или "HTML"
        r = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=20)
        # Если Telegram вернул ошибку — логируем тело ответа для диагностики
        if r.status_code >= 400:
            log.error(f"sendMessage error {r.status_code}: {r.text}")


# ========== 3) Вызов OpenAI (Chat Completions) ==========

def ask_openai(user_text: str) -> str:
    """
    Отправляет запрос в OpenAI и возвращает ответ модели.
    Минимальная конфигурация, можно дополнять системным промптом и др. параметрами.
    """
    messages = [
        {"role": "system", "content": "Ты дружелюбный и лаконичный помощник. Отвечай по-русски."},
        {"role": "user", "content": user_text.strip()},
    ]

    # Параметры подбирай по задаче (модель, температура и т.д.)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()


# ========== 4) Разбор входящего апдейта (JSON от Telegram) ==========

def extract_text_and_chat(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Унифицированно достаём chat_id и текст из разных типов апдейтов.
    Поддерживаем message/edited_message/channel_post и подписи к медиа.
    Возвращаем {"chat_id": int, "text": str} либо None.
    """
    # 1) Обычное сообщение из лички/группы
    msg = update.get("message")
    if msg:
        chat_id = msg["chat"]["id"]
        text = msg.get("text") or msg.get("caption")
        if text:
            return {"chat_id": chat_id, "text": text}

    # 2) Отредактированное сообщение (иногда полезно тоже обрабатывать)
    msg = update.get("edited_message")
    if msg:
        chat_id = msg["chat"]["id"]
        text = msg.get("text") or msg.get("caption")
        if text:
            return {"chat_id": chat_id, "text": text}

    # 3) Пост в канале (если бот добавлен в канал)
    msg = update.get("channel_post")
    if msg:
        chat_id = msg["chat"]["id"]
        text = msg.get("text") or msg.get("caption")
        if text:
            return {"chat_id": chat_id, "text": text}

    return None


# ========== 5) HTTP-маршруты (Flask) ==========

@app.route("/", methods=["GET"])
def root():
    """
    Простой корневой маршрут — помогает проверить доступность сервера.
    """
    return "OK", 200

@app.route("/healthz", methods=["GET"])
def healthz():
    """
    Health-check (можно подключить внешние мониторинги).
    """
    return jsonify(status="ok"), 200

@app.route("/webhook/<token>", methods=["POST"])
def telegram_webhook(token: str):
    """
    Основной маршрут вебхука Telegram.
    Последовательно делаем:
    1) Проверяем, что URL содержит верный токен (минимальная защита от мусора)
    2) (Опционально) проверяем секрет в заголовке X-Telegram-Bot-Api-Secret-Token
    3) Разбираем JSON-апдейт
    4) Если есть текст — спрашиваем OpenAI и отвечаем пользователю
    5) Возвращаем 200 OK (это важно для Telegram)
    """
    # 1) Проверка токена в пути
    if token != TELEGRAM_TOKEN:
        return "Not found", 404

    # 2) Проверка секрета заголовка (если задан)
    if WEBHOOK_SECRET:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_secret != WEBHOOK_SECRET:
            log.warning("Invalid webhook secret header")
            return "Forbidden", 403

    # 3) Читаем JSON
    try:
        update = request.get_json(force=True, silent=False)
    except Exception as e:
        log.error(f"Bad JSON: {e}")
        return "Bad Request", 400

    # 4) Достаём текст и чат
    extracted = extract_text_and_chat(update)
    if not extracted:
        # Например: стикер без подписи, join/leave события и т.п. — просто подтверждаем
        return "No content", 200

    chat_id = extracted["chat_id"]
    text = extracted["text"].strip()

    # Простейший хэндлинг команд — чтобы бот не молчал на /start и /help
    if text.startswith("/start"):
        tg_send_text(chat_id, "Привет! Я онлайн. Напиши мне сообщение — отвечу с помощью OpenAI.")
        return "OK", 200
    if text.startswith("/help"):
        tg_send_text(chat_id, "Я принимаю любой текст и отвечаю на него. Команды: /start, /help.")
        return "OK", 200

    # 5) UX — покажем, что бот "печатает"
    tg_send_action(chat_id, "typing")

    # 6) Вызов OpenAI и ответ пользователю
    try:
        answer = ask_openai(text) or "Извини, не смог сформировать ответ."
        tg_send_text(chat_id, answer)
    except Exception as e:
        log.exception(f"OpenAI/Telegram error: {e}")
        tg_send_text(chat_id, "Упс, возникла техническая ошибка. Попробуй ещё раз позже.")

    return "OK", 200


# ========== 6) Точка входа (локальный запуск / Railway) ==========

if __name__ == "__main__":
    # Railway передаёт порт через переменную PORT. Локально можно оставить 8080.
    port = int(os.getenv("PORT", "8080"))
    # 0.0.0.0 — обязательно, чтобы внешний прокси (Railway) мог достучаться
    app.run(host="0.0.0.0", port=port)
