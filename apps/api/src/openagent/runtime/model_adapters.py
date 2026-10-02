"""Model provider adapters."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, AsyncIterator
from dataclasses import dataclass, field

import aiohttp
import structlog

from openagent.runtime.agent_core import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelProviderRegistry,
    model_provider_registry,
)

logger = structlog.get_logger("runtime.model")


@dataclass
class OpenAIConfig:
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    organization: Optional[str] = None


class OpenAIAdapter(ModelProvider):
    """OpenAI API adapter."""
    
    provider_id = "openai"
    supported_models = [
        "gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini",
        "gpt-3.5-turbo", "gpt-3.5-turbo-16k",
    ]
    
    def __init__(self, config: OpenAIConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def provider_id(self) -> str:
        return self.provider_id
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
            if self.config.organization:
                headers["OpenAI-Organization"] = self.config.organization
            
            self._session = aiohttp.ClientSession(
                base_url=self.config.base_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return self._session
    
    async def generate(self, request: ModelRequest) -> ModelResponse:
        session = await self._get_session()
        
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice or "auto"
        
        if request.response_format:
            payload["response_format"] = request.response_format
        
        async with session.post("/chat/completions", json=payload) as response:
            data = await response.json()
            
            if response.status != 200:
                error = data.get("error", {})
                raise ModelProviderError(
                    code=error.get("code", "API_ERROR"),
                    message=error.get("message", "Unknown error"),
                    provider=self.provider_id,
                )
            
            choice = data["choices"][0]
            message = choice["message"]
            
            return ModelResponse(
                id=data.get("id"),
                content=message.get("content"),
                tool_calls=message.get("tool_calls"),
                finish_reason=choice.get("finish_reason"),
                usage=data.get("usage"),
                metadata={"provider": self.provider_id, "model": request.model},
            )
    
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        session = await self._get_session()
        
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice or "auto"
        
        if request.response_format:
            payload["response_format"] = request.response_format
        
        async with session.post("/chat/completions", json=payload) as response:
            if response.status != 200:
                error_data = await response.json()
                raise ModelProviderError(
                    code=error_data.get("error", {}).get("code", "API_ERROR"),
                    message=error_data.get("error", {}).get("message", "Stream error"),
                    provider=self.provider_id,
                )
            
            async for line in response.content:
                line = line.decode("utf-8").strip()
                if not line or line == "data: [DONE]":
                    continue
                
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        delta = data["choices"][0].get("delta", {})
                        
                        if "content" in delta and delta["content"]:
                            yield ModelStreamEvent(
                                type="delta",
                                content=delta["content"],
                            )
                        
                        if "tool_calls" in delta:
                            yield ModelStreamEvent(
                                type="tool_call",
                                tool_call=delta["tool_calls"][0],
                            )
                        
                        if data["choices"][0].get("finish_reason"):
                            yield ModelStreamEvent(
                                type="done",
                                finish_reason=data["choices"][0]["finish_reason"],
                            )
                    except json.JSONDecodeError:
                        continue


class AnthropicConfig:
    api_key: str
    base_url: str = "https://api.anthropic.com/v1"


class AnthropicAdapter(ModelProvider):
    """Anthropic (Claude) API adapter."""
    
    provider_id = "anthropic"
    supported_models = [
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
        "claude-3-5-sonnet-20241022",
    ]
    
    def __init__(self, config: AnthropicConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def provider_id(self) -> str:
        return self.provider_id
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "x-api-key": self.config.api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            self._session = aiohttp.ClientSession(
                base_url=self.config.base_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return self._session
    
    async def generate(self, request: ModelRequest) -> ModelResponse:
        session = await self._get_session()
        
        # Convert messages to Anthropic format
        system_prompt = ""
        messages = []
        for msg in request.messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                messages.append(msg)
        
        payload = {
            "model": request.model,
            "messages": messages,
            "system": system_prompt,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
        }
        
        if request.tools:
            payload["tools"] = self._convert_tools(request.tools)
            payload["tool_choice"] = request.tool_choice or "auto"
        
        async with session.post("/messages", json=payload) as response:
            data = await response.json()
            
            if response.status != 200:
                raise ModelProviderError(
                    code="API_ERROR",
                    message=data.get("error", {}).get("message", "Unknown error"),
                    provider=self.provider_id,
                )
            
            content = data["content"][0]["text"] if data["content"] else ""
            tool_calls = []
            
            for block in data["content"]:
                if block["type"] == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    })
            
            return ModelResponse(
                id=data.get("id"),
                content=content,
                tool_calls=tool_calls if tool_calls else None,
                finish_reason=data.get("stop_reason"),
                usage={
                    "input_tokens": data.get("usage", {}).get("input_tokens", 0),
                    "output_tokens": data.get("usage", {}).get("output_tokens", 0),
                },
                metadata={"provider": self.provider_id, "model": request.model},
            )
    
    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI-style tools to Anthropic format."""
        converted = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool["function"]
                converted.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                })
        return converted
    
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        # Similar to generate but with streaming
        # Implementation omitted for brevity
        response = await self.generate(request)
        yield ModelStreamEvent(type="delta", content=response.content)
        yield ModelStreamEvent(type="done", finish_reason="stop")


class GoogleConfig:
    api_key: str
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"


class GoogleAdapter(ModelProvider):
    """Google (Gemini) API adapter."""
    
    provider_id = "google"
    supported_models = [
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-1.0-pro",
    ]
    
    def __init__(self, config: GoogleConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def provider_id(self) -> str:
        return self.provider_id
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=self.config.base_url,
                headers={"x-goog-api-key": self.config.api_key},
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return self._session
    
    async def generate(self, request: ModelRequest) -> ModelResponse:
        # Implementation similar to OpenAI/Anthropic
        # Omitted for brevity
        pass


class OllamaConfig:
    base_url: str = "http://localhost:11434"
    # No API key needed for local Ollama


class OllamaAdapter(ModelProvider):
    """Ollama local model adapter."""
    
    provider_id = "ollama"
    supported_models = [
        "llama3", "llama3:70b", "mistral", "mixtral",
        "codellama", "phi3", "gemma", "qwen2",
    ]
    
    def __init__(self, config: OllamaConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def provider_id(self) -> str:
        return self.provider_id
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=self.config.base_url,
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return self._session
    
    async def generate(self, request: ModelRequest) -> ModelResponse:
        session = await self._get_session()
        
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": False,
        }
        
        if request.tools:
            payload["tools"] = request.tools
        
        async with session.post("/api/chat", json=payload) as response:
            data = await response.json()
            
            if response.status != 200:
                raise ModelProviderError(
                    code="API_ERROR",
                    message=data.get("error", "Unknown error"),
                    provider=self.provider_id,
                )
            
            message = data.get("message", {})
            
            return ModelResponse(
                content=message.get("content"),
                tool_calls=message.get("tool_calls"),
                finish_reason="stop" if not message.get("tool_calls") else "tool_calls",
                usage=None,  # Ollama doesn't always return usage
                metadata={"provider": self.provider_id, "model": request.model},
            )
    
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        # Similar to generate but streaming
        pass


class OpenAICompatibleConfig:
    api_key: str
    base_url: str
    # Any OpenAI-compatible endpoint


class OpenAICompatibleAdapter(OpenAIAdapter):
    """Adapter for OpenAI-compatible APIs (e.g., Together, Anyscale, etc.)."""
    
    provider_id = "openai-compatible"
    
    def __init__(self, config: OpenAICompatibleConfig):
        super().__init__(config)
        # Override supported models to be dynamic
        self._supported_models: Optional[List[str]] = None
    
    async def _fetch_models(self) -> List[str]:
        """Fetch available models from the API."""
        session = await self._get_session()
        async with session.get("/models") as response:
            data = await response.json()
            return [m["id"] for m in data.get("data", [])]
    
    @property
    def supported_models(self) -> List[str]:
        if self._supported_models is None:
            # Sync property cannot fetch; caller should await refresh_models()
            # first when dynamic discovery is needed.
            self._supported_models = [
                "gpt-3.5-turbo", "gpt-4", "gpt-4-turbo",
                "llama3", "mixtral", "codellama",
            ]
        return self._supported_models

    async def refresh_models(self) -> List[str]:
        """Fetch available models from the API (async discovery)."""
        try:
            self._supported_models = await self._fetch_models()
        except Exception:
            pass
        return self.supported_models


class ModelProviderError(Exception):
    """Error from a model provider."""
    def __init__(self, code: str, message: str, provider: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider = provider


# Auto-register providers from environment
def register_providers_from_env() -> None:
    """Register model providers from environment variables."""
    
    # OpenAI
    if os.getenv("OPENAI_API_KEY"):
        config = OpenAIConfig(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            organization=os.getenv("OPENAI_ORGANIZATION"),
        )
        model_provider_registry.register(OpenAIAdapter(config))
    
    # Anthropic
    if os.getenv("ANTHROPIC_API_KEY"):
        config = AnthropicConfig(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
        )
        model_provider_registry.register(AnthropicAdapter(config))
    
    # Google
    if os.getenv("GOOGLE_API_KEY"):
        config = GoogleConfig(
            api_key=os.getenv("GOOGLE_API_KEY"),
            base_url=os.getenv("GOOGLE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
        )
        model_provider_registry.register(GoogleAdapter(config))
    
    # Ollama
    if os.getenv("OLLAMA_BASE_URL"):
        config = OllamaConfig(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
        model_provider_registry.register(OllamaAdapter(config))
    
    # OpenAI-compatible
    if os.getenv("OPENAI_COMPATIBLE_API_KEY") and os.getenv("OPENAI_COMPATIBLE_BASE_URL"):
        config = OpenAICompatibleConfig(
            api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY"),
            base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL"),
        )
        model_provider_registry.register(OpenAICompatibleAdapter(config))


# Import required modules
import os
import structlog
import aiohttp
import json

logger = structlog.get_logger("runtime.model")

# Register providers on module import
register_providers_from_env()