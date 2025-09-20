import psycopg2
import os
from psycopg2.extras import RealDictCursor
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("grs-init")

DATABASE_URL = os.getenv("DATABASE_URL")

def init_db():
    if not DATABASE_URL:
        raise RuntimeError("❌ DATABASE_URL не задан")

    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()

        # Таблица истории
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                role VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','system')),
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # Индекс для быстрых выборок
        cur.execute("""
            CREATE INDEX IF NOT EXISTS chat_history_chat_created_idx
            ON chat_history (chat_id, created_at DESC);
        """)

        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Таблица chat_history создана или уже существовала.")

    except Exception as e:
        logger.error(f"Ошибка при инициализации базы: {e}")

if __name__ == "__main__":
    init_db()
