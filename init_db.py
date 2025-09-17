import psycopg2
import os

def init_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_history (
      id BIGSERIAL PRIMARY KEY,
      chat_id BIGINT NOT NULL,
      role VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant')),
      content TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS chat_history_chat_created_idx
      ON chat_history (chat_id, created_at DESC);
    """)

    conn.commit()
    cur.close()
    conn.close()