import os
from dotenv import load_dotenv

load_dotenv()

CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

AGENT_LOOP_INTERVAL_MINUTES: int = int(os.getenv("AGENT_LOOP_INTERVAL_MINUTES", "2"))

HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

COLLECTION_DIARY = "diary_entries"
COLLECTION_CHAT = "chat_logs"
MEMORY_TOP_K = 5
