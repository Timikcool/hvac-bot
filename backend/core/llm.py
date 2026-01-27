"""LLM client wrapper for Anthropic Claude and OpenAI."""

import base64
import time
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from config import get_settings
from core.logging import get_logger

logger = get_logger("core.llm")


@dataclass
class LLMResponse:
    """Response from LLM."""

    content: str
    model: str
    usage: dict[str, int]
    stop_reason: str | None = None


class LLMClient:
    """Async client for Claude API."""

    def __init__(self):
        settings = get_settings()
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.default_model = settings.anthropic_model
        self.default_max_tokens = settings.anthropic_max_tokens

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.1,
        messages: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Generate a response from Claude.

        Args:
            prompt: User prompt (ignored if messages provided)
            system: System prompt
            model: Model to use (defaults to config)
            max_tokens: Max tokens (defaults to config)
            temperature: Temperature (default 0.1 for factual)
            messages: Full messages array (overrides prompt)

        Returns:
            LLMResponse with content and metadata
        """
        if messages is None:
            messages = [{"role": "user", "content": prompt}]

        model_name = model or self.default_model
        logger.debug(f"LLM | Generating response | model={model_name} | temp={temperature}")
        logger.debug(f"LLM | System prompt length: {len(system or '')} chars")
        logger.debug(f"LLM | Messages: {len(messages)} | Last message length: {len(str(messages[-1].get('content', '')))} chars")

        start_time = time.time()
        try:
            response = await self.client.messages.create(
                model=model_name,
                max_tokens=max_tokens or self.default_max_tokens,
                temperature=temperature,
                system=system or "",
                messages=messages,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"LLM | Response received | model={response.model} | "
                f"tokens_in={response.usage.input_tokens} tokens_out={response.usage.output_tokens} | "
                f"stop={response.stop_reason} | time={duration_ms}ms"
            )

            return LLMResponse(
                content=response.content[0].text,
                model=response.model,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                stop_reason=response.stop_reason,
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"LLM | Error | {type(e).__name__}: {e} | time={duration_ms}ms")
            raise

    async def generate_with_vision(
        self,
        prompt: str,
        image_data: bytes,
        image_media_type: str = "image/jpeg",
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """Generate response with image input.

        Args:
            prompt: Text prompt about the image
            image_data: Raw image bytes
            image_media_type: MIME type (image/jpeg, image/png, etc.)
            system: System prompt
            model: Model to use
            max_tokens: Max tokens
            temperature: Temperature

        Returns:
            LLMResponse with content and metadata
        """
        image_b64 = base64.standard_b64encode(image_data).decode("utf-8")
        logger.info(f"LLM | Vision request | image_size={len(image_data)} bytes | media_type={image_media_type}")

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        model_name = model or self.default_model
        start_time = time.time()
        try:
            response = await self.client.messages.create(
                model=model_name,
                max_tokens=max_tokens or self.default_max_tokens,
                temperature=temperature,
                system=system or "",
                messages=messages,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"LLM | Vision response | model={response.model} | "
                f"tokens_in={response.usage.input_tokens} tokens_out={response.usage.output_tokens} | "
                f"time={duration_ms}ms"
            )

            return LLMResponse(
                content=response.content[0].text,
                model=response.model,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                stop_reason=response.stop_reason,
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"LLM | Vision error | {type(e).__name__}: {e} | time={duration_ms}ms")
            raise

    async def analyze_json(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Generate and parse JSON response.

        Args:
            prompt: Prompt that should result in JSON output
            system: System prompt
            model: Model to use

        Returns:
            Parsed JSON as dict
        """
        import json
        import re

        response = await self.generate(
            prompt=prompt,
            system=system,
            model=model,
            temperature=0,
        )

        # Extract JSON from response
        json_match = re.search(r"\{.*\}", response.content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        return {}


class OpenAIVisionClient:
    """Async client for OpenAI Vision API (GPT-4o).
    
    Used as fallback when Claude Vision fails.
    """
    
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.default_model = settings.openai_vision_model
    
    @property
    def is_configured(self) -> bool:
        """Check if OpenAI is configured."""
        settings = get_settings()
        return bool(settings.openai_api_key)
    
    async def generate_with_vision(
        self,
        prompt: str,
        image_data: bytes,
        image_media_type: str = "image/jpeg",
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """Generate response with image input using GPT-4o.

        Args:
            prompt: Text prompt about the image
            image_data: Raw image bytes
            image_media_type: MIME type (image/jpeg, image/png, etc.)
            system: System prompt
            model: Model to use (default: gpt-4o)
            max_tokens: Max tokens
            temperature: Temperature

        Returns:
            LLMResponse with content and metadata
        """
        image_b64 = base64.standard_b64encode(image_data).decode("utf-8")
        logger.info(f"OPENAI | Vision request | image_size={len(image_data)} bytes | media_type={image_media_type}")

        messages = []
        
        if system:
            messages.append({"role": "system", "content": system})
        
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_media_type};base64,{image_b64}",
                        "detail": "high",
                    },
                },
                {"type": "text", "text": prompt},
            ],
        })

        model_name = model or self.default_model
        start_time = time.time()
        
        try:
            response = await self.client.chat.completions.create(
                model=model_name,
                max_tokens=max_tokens or 4096,
                temperature=temperature,
                messages=messages,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            usage = response.usage
            logger.info(
                f"OPENAI | Vision response | model={response.model} | "
                f"tokens_in={usage.prompt_tokens} tokens_out={usage.completion_tokens} | "
                f"time={duration_ms}ms"
            )

            return LLMResponse(
                content=response.choices[0].message.content or "",
                model=response.model,
                usage={
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                },
                stop_reason=response.choices[0].finish_reason,
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"OPENAI | Vision error | {type(e).__name__}: {e} | time={duration_ms}ms")
            raise
