import logging
import time
import uuid
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from backend.config import (
    COLLECTION_CHAT,
    COLLECTION_DIARY,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MEMORY_TOP_K,
    QDRANT_API_KEY,
    QDRANT_URL,
)

logger = logging.getLogger(__name__)

_client: Optional[QdrantClient] = None
_embedder: Optional[SentenceTransformer] = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _client


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def init_collections() -> None:
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    for name in [COLLECTION_DIARY, COLLECTION_CHAT]:
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {name}")
        else:
            logger.info(f"Qdrant collection already exists: {name}")


def store_memory(
    character_id: str,
    text: str,
    collection: str,
    extra_payload: Optional[dict] = None,
) -> None:
    client = get_client()
    vector = get_embedder().encode(text).tolist()
    payload = {
        "character_id": character_id,
        "text": text,
        "timestamp": time.time(),
    }
    if extra_payload:
        payload.update(extra_payload)
    client.upsert(
        collection_name=collection,
        points=[PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload)],
    )


def retrieve_memories(
    character_id: str,
    query: str,
    collection: str,
    top_k: int = MEMORY_TOP_K,
) -> List[str]:
    client = get_client()
    vector = get_embedder().encode(query).tolist()
    results = client.search(
        collection_name=collection,
        query_vector=vector,
        query_filter=Filter(
            must=[FieldCondition(key="character_id", match=MatchValue(value=character_id))]
        ),
        limit=top_k,
    )
    return [r.payload["text"] for r in results]
