from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .status import CaseStatus


@dataclass(frozen=True)
class Generation:
    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    raw_usage: dict[str, Any]


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: CaseStatus = CaseStatus.TRANSPORT_ERROR,
        http_status: int | None = None,
        diagnostic: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.http_status = http_status
        self.diagnostic = diagnostic or {}

    def payload(self) -> dict[str, Any]:
        return {
            "category": self.status.value,
            "message": str(self),
            "httpStatus": self.http_status,
            "diagnostic": self.diagnostic,
        }


def _http_status(code: int) -> CaseStatus:
    if code == 402:
        return CaseStatus.BILLING_DEPLETED
    if code == 429:
        return CaseStatus.RATE_LIMITED
    if code in {401, 403}:
        return CaseStatus.AUTHENTICATION_ERROR
    if code in {408, 504}:
        return CaseStatus.TRANSPORT_TIMEOUT
    return CaseStatus.TRANSPORT_ERROR


def _json_request(
    url: str,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
    timeout: int = 120,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **headers},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4000).decode("utf-8", errors="replace")
        raise ProviderError(
            f"HTTP {exc.code}: {detail}",
            status=_http_status(exc.code),
            http_status=exc.code,
            diagnostic={"responseBody": detail[:4000]},
        ) from exc
    except TimeoutError as exc:
        raise ProviderError(
            f"Transport timeout after {timeout} seconds",
            status=CaseStatus.TRANSPORT_TIMEOUT,
            diagnostic={"timeoutSeconds": timeout},
        ) from exc
    except urllib.error.URLError as exc:
        is_timeout = isinstance(exc.reason, (TimeoutError, socket.timeout))
        raise ProviderError(
            f"Network error: {exc.reason}",
            status=CaseStatus.TRANSPORT_TIMEOUT if is_timeout else CaseStatus.TRANSPORT_ERROR,
            diagnostic={"reason": str(exc.reason)},
        ) from exc


class OpenAIAdapter:
    def __init__(
        self,
        *,
        name: str = "openai",
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str | None = None,
        embedding_model: str | None = None,
    ):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model or self._discover_model()
        self.embedding_model = embedding_model or os.getenv("TESTFAILS_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _discover_model(self) -> str:
        document = _json_request(f"{self.base_url}/models", None, self.headers, 30)
        ids = {item.get("id") for item in document.get("data", [])}
        preferred = ("gpt-5.4-mini", "gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini")
        for model in preferred:
            if model in ids:
                return model
        candidates = sorted(
            model for model in ids
            if isinstance(model, str) and ("gpt" in model.casefold() or "chat" in model.casefold())
        )
        if not candidates:
            raise ProviderError("No chat-capable model was discovered; set TESTFAILS_OPENAI_MODEL explicitly.")
        return candidates[-1]

    def generate(self, prompt: str, image_data_url: str | None = None) -> Generation:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        if image_data_url:
            content.append({"type": "input_image", "image_url": image_data_url, "detail": "low"})
        payload = {
            "model": self.model,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": 1200,
        }
        document = _json_request(f"{self.base_url}/responses", payload, self.headers)
        text = document.get("output_text")
        if not text:
            parts = [
                part["text"]
                for item in document.get("output", [])
                for part in item.get("content", [])
                if isinstance(part.get("text"), str)
            ]
            text = "\n".join(parts)
        if not text:
            raise ProviderError("Provider returned no output text.")
        usage = document.get("usage") or {}
        return Generation(
            text=text,
            model=document.get("model", self.model),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw_usage=usage,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        document = _json_request(
            f"{self.base_url}/embeddings",
            {"model": self.embedding_model, "input": texts},
            self.headers,
        )
        rows = sorted(document.get("data", []), key=lambda row: row.get("index", 0))
        vectors = [row.get("embedding") for row in rows]
        if len(vectors) != len(texts) or not all(isinstance(vector, list) for vector in vectors):
            raise ProviderError("Embedding endpoint returned an incomplete vector set.")
        return vectors


class GeminiAdapter:
    def __init__(self, *, api_key: str, model: str | None = None, embedding_model: str | None = None):
        self.name = "gemini"
        self.api_key = api_key
        self.model = model or os.getenv("TESTFAILS_GEMINI_MODEL", "gemini-3.8-flash")
        self.embedding_model = embedding_model or os.getenv("TESTFAILS_GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

    def _url(self, model: str, action: str) -> str:
        encoded_model = urllib.parse.quote(model, safe="")
        encoded_key = urllib.parse.quote(self.api_key, safe="")
        return f"https://generativelanguage.googleapis.com/v1beta/models/{encoded_model}:{action}?key={encoded_key}"

    def generate(self, prompt: str, image_data_url: str | None = None) -> Generation:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        if image_data_url:
            header, encoded = image_data_url.split(",", 1)
            mime = header.split(":", 1)[1].split(";", 1)[0]
            parts.append({"inlineData": {"mimeType": mime, "data": encoded}})
        document = _json_request(
            self._url(self.model, "generateContent"),
            {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"maxOutputTokens": 1200, "responseMimeType": "application/json"},
            },
            {},
        )
        candidates = document.get("candidates") or []
        if not candidates:
            raise ProviderError(f"Gemini returned no candidate: {document.get('promptFeedback', {})}")
        text = "".join(part.get("text", "") for part in candidates[0].get("content", {}).get("parts", []))
        usage = document.get("usageMetadata") or {}
        return Generation(
            text=text,
            model=self.model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            raw_usage=usage,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            document = _json_request(
                self._url(self.embedding_model, "embedContent"),
                {"content": {"parts": [{"text": text}]}, "taskType": "SEMANTIC_SIMILARITY"},
                {},
            )
            vector = document.get("embedding", {}).get("values")
            if not isinstance(vector, list):
                raise ProviderError("Gemini embedding endpoint returned no vector.")
            vectors.append(vector)
        return vectors


class LocalHuggingFaceAdapter(OpenAIAdapter):
    """Adapter for a local Hugging Face/TGI OpenAI-compatible inference server."""

    def __init__(self, *, base_url: str, model: str, api_key: str = "", embedding_model: str | None = None):
        super().__init__(
            name="local-huggingface",
            api_key=api_key,
            base_url=base_url,
            model=model,
            embedding_model=embedding_model or model,
        )

    def generate(self, prompt: str, image_data_url: str | None = None) -> Generation:
        if image_data_url:
            content: str | list[dict[str, Any]] = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        else:
            content = prompt
        document = _json_request(
            f"{self.base_url}/chat/completions",
            {"model": self.model, "messages": [{"role": "user", "content": content}], "max_tokens": 1200},
            self.headers,
        )
        choices = document.get("choices") or []
        text = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(text, str) or not text:
            raise ProviderError("Local Hugging Face endpoint returned no output text.")
        usage = document.get("usage") or {}
        return Generation(
            text=text,
            model=document.get("model", self.model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw_usage=usage,
        )


# Backward-compatible names retained for callers of the initial release.
OpenAICompatibleProvider = OpenAIAdapter
GeminiProvider = GeminiAdapter


def configured_providers() -> list[Any]:
    providers: list[Any] = []
    if key := os.getenv("OPENAI_API_KEY"):
        providers.append(OpenAIAdapter(api_key=key, model=os.getenv("TESTFAILS_OPENAI_MODEL") or None))
    if key := os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        providers.append(GeminiAdapter(api_key=key))
    if base := os.getenv("TESTFAILS_LOCAL_HF_BASE_URL"):
        model = os.getenv("TESTFAILS_LOCAL_HF_MODEL")
        if not model:
            raise ProviderError("TESTFAILS_LOCAL_HF_MODEL is required with TESTFAILS_LOCAL_HF_BASE_URL.")
        providers.append(LocalHuggingFaceAdapter(
            base_url=base,
            model=model,
            api_key=os.getenv("TESTFAILS_LOCAL_HF_API_KEY", ""),
            embedding_model=os.getenv("TESTFAILS_LOCAL_HF_EMBEDDING_MODEL") or None,
        ))
    if key := os.getenv("TESTFAILS_COMPAT_API_KEY"):
        base = os.getenv("TESTFAILS_COMPAT_BASE_URL")
        model = os.getenv("TESTFAILS_COMPAT_MODEL")
        if not base or not model:
            raise ProviderError("TESTFAILS_COMPAT_BASE_URL and TESTFAILS_COMPAT_MODEL are required with TESTFAILS_COMPAT_API_KEY.")
        providers.append(OpenAIAdapter(
            name=os.getenv("TESTFAILS_COMPAT_NAME", "compatible"),
            api_key=key,
            base_url=base,
            model=model,
            embedding_model=os.getenv("TESTFAILS_COMPAT_EMBEDDING_MODEL") or None,
        ))
    return providers
