"""Embedding provider abstraction and implementations for memory embeddings."""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from uuid import UUID

import structlog
from openagent.core.config import get_settings

logger = structlog.get_logger("memory.embedding")


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""
    embedding: List[float]
    model: str
    dimensions: int
    tokens_used: int = 0


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the embedding model."""
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Number of dimensions in the embedding."""
        pass

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[EmbeddingResult]:
        """Generate embeddings for a list of texts."""
        pass

    @abstractmethod
    async def embed_single(self, text: str) -> EmbeddingResult:
        """Generate embedding for a single text."""
        pass

    async def health_check(self) -> bool:
        """Check if the provider is healthy."""
        try:
            result = await self.embed_single("health check")
            return len(result.embedding) == self.dimensions
        except Exception:
            return False


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        dimensions: Optional[int] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        import openai
        self.client = openai.AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            timeout=timeout,
            max_retries=max_retries,
        )
        self._model = model
        self._dimensions = dimensions or (1536 if "3-large" in model else 1536 if "3-small" in model else 1536)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: List[str]) -> List[EmbeddingResult]:
        if not texts:
            return []
        
        response = await self.client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=self._dimensions if "3-" in self._model else None,
        )
        
        return [
            EmbeddingResult(
                embedding=data.embedding,
                model=self._model,
                dimensions=self._dimensions,
                tokens_used=response.usage.total_tokens if hasattr(response, 'usage') else 0,
            )
            for data in response.data
        ]

    async def embed_single(self, text: str) -> EmbeddingResult:
        results = await self.embed([text])
        return results[0] if results else EmbeddingResult(
            embedding=[0.0] * self.dimensions,
            model=self._model,
            dimensions=self.dimensions,
        )


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama local embedding provider for self-hosted models."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        dimensions: int = 768,
        timeout: float = 60.0,
    ):
        import aiohttp
        self._model = model
        self._base_url = base_url.rstrip('/')
        self._dimensions = dimensions
        self._timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            import aiohttp
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout)
            )
        return self._session

    async def embed(self, texts: List[str]) -> List[EmbeddingResult]:
        if not texts:
            return []
        
        session = await self._get_session()
        results = []
        
        for text in texts:
            result = await self.embed_single(text)
            results.append(result)
        
        return results

    async def embed_single(self, text: str) -> EmbeddingResult:
        session = await self._get_session()
        
        async with session.post(
            f"{self._base_url}/api/embeddings",
            json={"model": self._model, "prompt": text},
        ) as response:
            if response.status != 200:
                raise Exception(f"Ollama embedding failed: {response.status}")
            
            data = await response.json()
            embedding = data.get("embedding", [])
            
            if len(embedding) != self.dimensions:
                logger.warning(f"Embedding dimension mismatch: expected {self.dimensions}, got {len(embedding)}")
            
            return EmbeddingResult(
                embedding=embedding,
                model=self._model,
                dimensions=len(embedding),
            )

    async def health_check(self) -> bool:
        try:
            result = await self.embed_single("health check")
            return len(result.embedding) > 0
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


class SentenceTransformerProvider(EmbeddingProvider):
    """Local sentence transformer provider using HuggingFace models."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: Optional[str] = None,
        batch_size: int = 32,
    ):
        self._model_name = model_name
        self._device = device or ("cuda" if self._is_cuda_available() else "cpu")
        self._batch_size = batch_size
        self._model = None
        self._dimensions = 384  # Default for MiniLM

    def _is_cuda_available(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name, device=self._device)
            # Get actual dimensions
            test_embedding = self._model.encode(["test"])
            self._dimensions = len(test_embedding[0])

    async def embed(self, texts: List[str]) -> List[EmbeddingResult]:
        if not texts:
            return []
        
        self._load_model()
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: self._model.encode(texts, batch_size=self._batch_size, show_progress_bar=False)
        )
        
        return [
            EmbeddingResult(
                embedding=emb.tolist(),
                model=self._model_name,
                dimensions=self._dimensions,
                tokens_used=sum(len(t.split()) for t in texts),
            )
            for emb in embeddings
        ]

    async def embed_single(self, text: str) -> EmbeddingResult:
        results = await self.embed([text])
        return results[0] if results else EmbeddingResult(
            embedding=[0.0] * self.dimensions,
            model=self._model_name,
            dimensions=self._dimensions,
        )

    async def health_check(self) -> bool:
        try:
            result = await self.embed_single("health check")
            return len(result.embedding) > 0
        except Exception as e:
            logger.warning(f"SentenceTransformer health check failed: {e}")
            return False


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock embedding provider for testing."""

    def __init__(self, dimensions: int = 384, model_name: str = "mock"):
        self._model_name = model_name
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: List[str]) -> List[EmbeddingResult]:
        import random
        return [
            EmbeddingResult(
                embedding=[random.uniform(-1, 1) for _ in range(self.dimensions)],
                model=self._model_name,
                dimensions=self._dimensions,
                tokens_used=len(text.split()),
            )
            for text in texts
        ]

    async def embed_single(self, text: str) -> EmbeddingResult:
        import random
        return EmbeddingResult(
            embedding=[random.uniform(-1, 1) for _ in range(self.dimensions)],
            model=self._model_name,
            dimensions=self._dimensions,
            tokens_used=len(text.split()),
        )


def create_embedding_provider(config: Optional[Dict[str, Any]] = None) -> EmbeddingProvider:
    """Factory function to create embedding provider from config."""
    config = config or {}
    provider_type = config.get("type", "mock")
    
    if provider_type == "openai":
        return OpenAIEmbeddingProvider(
            api_key=config.get("api_key"),
            model=config.get("model", "text-embedding-3-small"),
            dimensions=config.get("dimensions"),
            base_url=config.get("base_url"),
        )
    elif provider_type == "ollama":
        return OllamaEmbeddingProvider(
            model=config.get("model", "nomic-embed-text"),
            base_url=config.get("base_url", "http://localhost:11434"),
            dimensions=config.get("dimensions", 768),
        )
    elif provider_type == "sentence_transformer":
        return SentenceTransformerProvider(
            model_name=config.get("model", "sentence-transformers/all-MiniLM-L6-v2"),
            device=config.get("device"),
        )
    elif provider_type == "mock":
        return MockEmbeddingProvider(
            dimensions=config.get("dimensions", 384),
            model_name=config.get("model", "mock"),
        )
    else:
        # Default to mock for testing
        return MockEmbeddingProvider(
            dimensions=config.get("dimensions", 384),
            model_name="mock",
        )


# Export all providers
__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "OpenAIEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "SentenceTransformerProvider",
    "MockEmbeddingProvider",
    "create_embedding_provider",
]