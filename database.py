import aiosqlite
import os
import conversation_memory

DB_PATH = "argus_vault.db"

async def init_db():
    """Initializes the persistent memory schema."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Table 1: Permanent semantic facts explicitly told to Argus
        await db.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_key TEXT UNIQUE,
                fact_value TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Table 2: Complete historical dialogue logs for context building
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    print("[Database] Semantic Vault Initialized and Secured.")

async def save_fact(key: str, value: str):
    """Stores or updates a specific piece of permanent knowledge."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO long_term_memories (fact_key, fact_value)
            VALUES (?, ?)
            ON CONFLICT(fact_key) DO UPDATE SET fact_value = excluded.fact_value
        """, (key.lower().strip(), value.strip()))
        await db.commit()
    print(f"[Database] Permanently memorized: {key} -> {value}")

async def recall_fact(key: str):
    """Retrieves a piece of permanent knowledge if it matches keywords."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT fact_value FROM long_term_memories WHERE fact_key LIKE ?", 
            (f"%{key.lower().strip()}%",)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def log_dialogue(role: str, content: str):
    """Logs every sentence exchanged during a live call to the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversation_logs (role, content) VALUES (?, ?)",
            (role, content)
        )
        await db.commit()
    # Also feed it into the semantic (FAISS) long-term memory so Argus
    # can recall past conversations, not just explicit "remember that" facts.
    conversation_memory.index_turn(role, content)