"""FastAPI dependencies for dependency injection."""

import logging
from typing import AsyncGenerator

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from core.llm import LLMClient
from services.analytics.knowledge_gaps import KnowledgeGapTracker
from services.analytics.rag_analytics import RAGAnalytics
from services.rag.embedder import HVACEmbedder
from services.rag.pipeline import RAGPipeline
from services.rag.vector_store import HVACVectorStore
from services.tracking.conversation_tracker import ConversationTracker
from services.vision.nameplate_reader import NameplateReader
from services.vision.problem_analyzer import ProblemAnalyzer

logger = logging.getLogger("dependencies")

# Database engine and session factory
_engine = None
_session_factory = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        logger.info(f"Creating database engine: {settings.database_url.split('@')[-1]}")
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_factory():
    """Get or create session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


# Redis connection
_redis = None


async def get_redis() -> Redis | None:
    """Get Redis connection."""
    global _redis
    if _redis is None:
        settings = get_settings()
        try:
            logger.info(f"Connecting to Redis: {settings.redis_url}")
            _redis = Redis.from_url(settings.redis_url)
            await _redis.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis connection failed (optional): {e}")
            _redis = None  # Redis is optional
    return _redis


# Service dependencies
_llm_client = None


def get_llm_client() -> LLMClient:
    """Get LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        logger.info("Initializing LLM client (Anthropic Claude)")
        _llm_client = LLMClient()
    return _llm_client


_embedder = None


def get_embedder() -> HVACEmbedder:
    """Get embedder singleton."""
    global _embedder
    if _embedder is None:
        logger.info("Initializing HVAC Embedder (Voyage AI)")
        _embedder = HVACEmbedder()
    return _embedder


_vector_store = None


def get_vector_store() -> HVACVectorStore:
    """Get vector store singleton."""
    global _vector_store
    if _vector_store is None:
        logger.info("Initializing Vector Store (Qdrant)")
        _vector_store = HVACVectorStore()
    return _vector_store


async def get_rag_pipeline(
    llm: LLMClient = Depends(get_llm_client),
    vector_store: HVACVectorStore = Depends(get_vector_store),
    embedder: HVACEmbedder = Depends(get_embedder),
) -> RAGPipeline:
    """Get RAG pipeline."""
    logger.debug("Creating RAG pipeline instance")
    return RAGPipeline(
        llm_client=llm,
        vector_store=vector_store,
        embedder=embedder,
    )


async def get_tracker(
    db: AsyncSession = Depends(get_db),
    redis: Redis | None = Depends(get_redis),
) -> ConversationTracker:
    """Get conversation tracker."""
    return ConversationTracker(db_session=db, redis_client=redis)


async def get_nameplate_reader(
    llm: LLMClient = Depends(get_llm_client),
) -> NameplateReader:
    """Get nameplate reader."""
    return NameplateReader(llm_client=llm)


async def get_problem_analyzer(
    llm: LLMClient = Depends(get_llm_client),
) -> ProblemAnalyzer:
    """Get problem analyzer."""
    return ProblemAnalyzer(llm_client=llm)


async def get_analytics(
    db: AsyncSession = Depends(get_db),
) -> RAGAnalytics:
    """Get RAG analytics service."""
    return RAGAnalytics(db_session=db)


async def get_gap_tracker(
    db: AsyncSession = Depends(get_db),
) -> KnowledgeGapTracker:
    """Get knowledge gap tracker."""
    return KnowledgeGapTracker(db_session=db)
