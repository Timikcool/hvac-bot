"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "HVAC AI Assistant"
    debug: bool = False
    environment: str = "development"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hvac_assistant"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 4096

    # OpenAI (embeddings + vision fallback)
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_vision_model: str = "gpt-4o"
    
    # Google Cloud Platform / Vertex AI
    gcp_project_id: str = ""
    gcp_location: str = "us-central1"
    gcp_credentials_path: str = ""  # Path to service account JSON (optional)
    
    # Google Cloud API Key (for Vertex AI - simpler than service account)
    # Get from: Cloud Console → APIs & Services → Credentials → Create API Key
    # Or use "express mode" in Vertex AI console
    google_cloud_api_key: str = ""
    
    # Google AI API Key (for Gemini via AI Studio - alternative to Vertex)
    # Get from: https://aistudio.google.com/
    google_api_key: str = ""
    
    # Gemini model
    gemini_model: str = "gemini-1.5-pro"
    
    def configure_gcp_credentials(self) -> None:
        """Configure GCP credentials from API key or service account."""
        import os
        
        # Option 1: Google Cloud API Key (for Vertex AI)
        if self.google_cloud_api_key:
            os.environ["GOOGLE_CLOUD_API_KEY"] = self.google_cloud_api_key
            os.environ["GOOGLE_API_KEY"] = self.google_cloud_api_key  # Some libs use this
        
        # Option 2: Google AI API Key (for AI Studio / Gemini)
        elif self.google_api_key:
            os.environ["GOOGLE_API_KEY"] = self.google_api_key
        
        # Option 3: Service account JSON file
        if self.gcp_credentials_path and os.path.exists(self.gcp_credentials_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.gcp_credentials_path
    
    # Document AI
    document_ai_processor_id: str = ""
    document_ai_gcs_bucket: str = ""  # GCS bucket for batch processing large documents
    document_ai_max_online_pages: int = 15  # Max pages for online processing (API limit)
    
    # Vertex AI Embeddings
    vertex_embedding_model: str = "text-embedding-004"
    
    # Vertex AI Vector Search
    vertex_index_endpoint_id: str = ""
    vertex_deployed_index_id: str = ""
    
    # Vertex AI RAG Engine
    vertex_rag_corpus: str = ""
    
    # Provider selection (openai, vertex, auto)
    embedding_provider: str = "auto"  # auto = try vertex, fallback to openai
    vector_store_provider: str = "qdrant"  # qdrant or vertex
    rag_provider: str = "custom"  # custom or vertex

    # Qdrant (vector store)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "hvac_manuals"

    # RAG settings
    rag_top_k: int = 10
    rag_min_score: float = 0.5
    chunk_size: int = 1500
    chunk_overlap: int = 200

    # Storage
    data_dir: str = "./data"
    manual_storage_path: str = "./data/manuals"
    upload_max_size_mb: int = 50
    
    # Logging
    log_dir: str = "./logs"
    log_max_size_mb: int = 10
    log_backup_count: int = 10

    # Security
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    api_key_header: str = "X-API-Key"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
