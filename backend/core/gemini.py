"""Gemini LLM client for Google AI.

Uses the simpler google-generativeai package with API key authentication.
This is an alternative to Vertex AI when you don't have full GCP setup.
"""

import base64
import time
from dataclasses import dataclass
from typing import Any

from core.logging import get_logger

logger = get_logger("core.gemini")


@dataclass
class GeminiResponse:
    """Response from Gemini API."""
    content: str
    model: str
    usage: dict[str, int] | None = None


class GeminiClient:
    """Async client for Google Gemini API.
    
    Uses API key authentication (simpler than Vertex AI service accounts).
    Get your API key from: https://aistudio.google.com/
    """
    
    def __init__(self, api_key: str | None = None, model: str | None = None):
        """Initialize Gemini client.
        
        Args:
            api_key: Gemini API key (uses config if not provided)
            model: Model name (default: gemini-1.5-pro)
        
        Note: google-generativeai requires a Google AI API key (starts with 'AIza'),
        NOT a Vertex AI express mode key (starts with 'AQ.').
        Get your key at: https://aistudio.google.com/apikey
        """
        from config import get_settings
        settings = get_settings()
        
        # Try Google AI API key first (the one that works with google-generativeai)
        # Then try Google Cloud API key (may not work with this library)
        self.api_key = api_key or settings.google_api_key or settings.google_cloud_api_key
        self.model_name = model or settings.gemini_model
        
        if not self.api_key:
            raise ValueError("No Google API key found. Set GOOGLE_API_KEY in .env")
        
        # Warn if using Vertex AI express mode key (won't work)
        if self.api_key.startswith("AQ."):
            logger.warning(
                "GEMINI | Detected Vertex AI express mode key (AQ.*). "
                "This library requires a Google AI API key (AIza*). "
                "Get one at: https://aistudio.google.com/apikey"
            )
        
        self._model = None
        self._configured = self.api_key.startswith("AIza") if self.api_key else False
        logger.info(f"GEMINI | Initialized | model={self.model_name} | configured={self._configured}")
    
    @property
    def is_configured(self) -> bool:
        """Check if Gemini is properly configured.
        
        Returns True only if we have a valid Google AI API key (AIza*).
        Vertex AI express mode keys (AQ.*) don't work with this library.
        """
        return self._configured
    
    def _get_model(self):
        """Lazy-load the generative model."""
        if self._model is None:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
        return self._model
    
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> GeminiResponse:
        """Generate a response from Gemini.
        
        Args:
            prompt: User prompt
            system_prompt: System instructions
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            
        Returns:
            GeminiResponse with content
        """
        import asyncio
        
        start_time = time.time()
        logger.debug(f"GEMINI | Generating response | prompt_length={len(prompt)}")
        
        model = self._get_model()
        
        # Combine system prompt with user prompt if provided
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        # Run in thread pool since google-generativeai is sync
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                full_prompt,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                }
            )
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        content = response.text if response.text else ""
        
        logger.info(f"GEMINI | Response generated | length={len(content)} | time={duration_ms}ms")
        
        return GeminiResponse(
            content=content,
            model=self.model_name,
            usage=None,  # google-generativeai doesn't provide token counts easily
        )
    
    async def generate_with_image(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        max_tokens: int = 4096,
    ) -> GeminiResponse:
        """Generate response with image input.
        
        Args:
            prompt: User prompt describing what to analyze
            image_bytes: Image as bytes
            mime_type: Image MIME type
            max_tokens: Maximum tokens in response
            
        Returns:
            GeminiResponse with content
        """
        import asyncio
        
        start_time = time.time()
        logger.debug(f"GEMINI | Vision request | image_size={len(image_bytes)} bytes")
        
        model = self._get_model()
        
        # Prepare image for Gemini
        image_part = {
            "mime_type": mime_type,
            "data": image_bytes,
        }
        
        # Run in thread pool
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                [prompt, image_part],
                generation_config={
                    "max_output_tokens": max_tokens,
                }
            )
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        content = response.text if response.text else ""
        
        logger.info(f"GEMINI | Vision response | length={len(content)} | time={duration_ms}ms")
        
        return GeminiResponse(
            content=content,
            model=self.model_name,
        )


class GeminiEmbedder:
    """Generate embeddings using Google's embedding model.
    
    Uses API key authentication (same as GeminiClient).
    """
    
    EMBEDDING_DIM = 768  # text-embedding-004 dimension
    
    def __init__(self, api_key: str | None = None):
        """Initialize embedder.
        
        Args:
            api_key: Google API key (uses config if not provided)
            
        Note: Requires Google AI API key (AIza*), not Vertex AI key (AQ.*).
        """
        from config import get_settings
        settings = get_settings()
        
        # Try Google AI API key first, then Google Cloud API key
        self.api_key = api_key or settings.google_api_key or settings.google_cloud_api_key
        
        if not self.api_key:
            raise ValueError("No Google API key found. Set GOOGLE_API_KEY in .env")
        
        # Only valid if it's a Google AI API key
        self._configured = self.api_key.startswith("AIza") if self.api_key else False
        
        if self.api_key and self.api_key.startswith("AQ."):
            logger.warning("GEMINI | Embedder: Vertex AI key detected, won't work with google-generativeai")
        
        logger.info(f"GEMINI | Embedder initialized | configured={self._configured}")
    
    @property
    def is_configured(self) -> bool:
        """Check if embedder is properly configured."""
        return self._configured
    
    def _configure(self):
        """Configure the API once."""
        if not self._configured:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._configured = True
    
    async def embed_documents(
        self,
        texts: list[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        """Embed multiple documents.
        
        Args:
            texts: List of texts to embed
            task_type: Task type (RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY, etc.)
            
        Returns:
            List of embedding vectors
        """
        import asyncio
        import google.generativeai as genai
        
        if not texts:
            return []
        
        self._configure()
        
        logger.info(f"GEMINI | Embedding {len(texts)} documents...")
        
        # Embed in batches (API limit is usually 100)
        batch_size = 100
        all_embeddings = []
        
        loop = asyncio.get_event_loop()
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            
            # Embed batch
            embeddings = await loop.run_in_executor(
                None,
                lambda b=batch: [
                    genai.embed_content(
                        model="models/text-embedding-004",
                        content=text,
                        task_type=task_type,
                    )["embedding"]
                    for text in b
                ]
            )
            
            all_embeddings.extend(embeddings)
        
        logger.info(f"GEMINI | Embedded {len(all_embeddings)} documents | dim={self.EMBEDDING_DIM}")
        return all_embeddings
    
    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query.
        
        Args:
            text: Query text to embed
            
        Returns:
            Embedding vector
        """
        import asyncio
        import google.generativeai as genai
        
        self._configure()
        
        logger.debug(f"GEMINI | Embedding query | length={len(text)} chars")
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: genai.embed_content(
                model="models/text-embedding-004",
                content=text,
                task_type="RETRIEVAL_QUERY",
            )
        )
        
        return result["embedding"]

