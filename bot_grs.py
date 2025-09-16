import os
import logging
import json
import requests
from flask import Flask, request
from openai import OpenAI

# ----------------------------------------
# 🔹 Логирование
# ----------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grs-tg-bot")

# ----------------------------------------
# 🔹 Переменные окружения
# ----------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
PORT = int(os.getenv("PORT", 8080))

if not TELEGRAM_TOKEN:
    raise RuntimeError("Не задан TELEGRAM_TOKEN")
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("Не задан OPENAI_API_KEY")
if not TAVILY_API_KEY:
    log.warning("⚠️ Не задан TAVILY_API_KEY — поиск не будет работать")

# ----------------------------------------
# 🔹 Flask
# ----------------------------------------
app = Flask(__name__)

# ----------------------------------------
# 📤 Отправка сообщений в Telegram
# ----------------------------------------
def send_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    r = requests.post(url, json=payload)
    if not r.ok:
        log.error(f"Ошибка Telegram API: {r.text}")

# ----------------------------------------
# 🔎 Функция поиска через Tavily
# ----------------------------------------
def web_search(query: str) -> str:
    url = "https://api.tavily.com/search"
    headers = {"Authorization": f"Bearer {TAVILY_API_KEY}"}
    payload = {"query": query, "num_results": 3}
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        log.error(f"Ошибка Tavily API: {resp.text}")
        return "Ошибка при поиске"
    data = resp.json()
    results = [item["content"] for item in data.get("results", [])]
    return "\n".join(results) if results else "Нет результатов"

# ----------------------------------------
# 📥 Webhook
# ----------------------------------------
@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = request.json
    message = update.get("message")
    if not message:
        return "ok"

    chat_id = message["chat"]["id"]
    chat_type = message["chat"]["type"]
    user_text = message.get("text", "")

    if chat_type != "private":
        return "ok"
    if not user_text.strip():
        return "ok"

    log.info(f"User {chat_id} wrote: {user_text}")

    system_prompt = (
        "Ты — эксперт-консультант компании Global Relocation Solutions (GRS). "
        "Твоя специализация — миграционное право и программы ВНЖ/гражданства. "
        "Отвечай профессионально и по делу, как юрист-практик. "
        "Если требуется актуальная информация, используй встроенный поиск."
    )

    try:
        # Первый запрос
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Поиск свежей информации в интернете",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"}
                            },
                            "required": ["query"],
                        },
                    }
                }
            ],
            tool_choice="auto",
            max_completion_tokens=800,
        )

        choice = response.choices[0]

        # Если модель решила вызвать web_search
        if choice.message.tool_calls:
            for tool_call in choice.message.tool_calls:
                if tool_call.function.name == "web_search":
                    args = json.loads(tool_call.function.arguments)
                    query = args.get("query")
                    search_result = web_search(query)

                    # Второй запрос — модель получает результаты поиска
                    response = client.chat.completions.create(
                        model="gpt-4.1",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_text},
                            choice.message,
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": search_result,
                            },
                        ],
                        max_completion_tokens=1000,
                    )

        reply_text = response.choices[0].message.content.strip()
        if not reply_text:
            reply_text = "Извините, я не нашёл ответа."

    except Exception as e:
        log.error(f"Ошибка OpenAI: {e}")
        reply_text = "Извините, произошла ошибка."

    send_message(chat_id, reply_text)
    return "ok"

# ----------------------------------------
# 🚀 Локальный запуск
# ----------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
