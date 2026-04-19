"""
groq_client.py — Cliente LLM con fallback automático Groq → OpenRouter.

Intenta Groq primero. Si se agota el rate limit (429), cambia a OpenRouter
automáticamente usando el mismo modelo (llama-3.3-70b) sin interrumpir el flujo.
"""

import json
import logging
import time

import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class GroqResponse:
    """Wrapper mínimo que imita la interfaz de openai.ChatCompletion."""

    def __init__(self, data: dict):
        self._data = data

    @property
    def choices(self):
        return [_Choice(c) for c in self._data.get("choices", [])]

    @property
    def usage(self):
        return _Usage(self._data.get("usage", {}))


class _Choice:
    def __init__(self, data: dict):
        self.message = _Message(data.get("message", {}))


class _Message:
    def __init__(self, data: dict):
        self.content: str = data.get("content", "")


class _Usage:
    def __init__(self, data: dict):
        self.prompt_tokens: int     = data.get("prompt_tokens", 0)
        self.completion_tokens: int = data.get("completion_tokens", 0)


class LLMClient:
    """
    Cliente HTTP que intenta Groq primero y cae a OpenRouter si hay rate limit.
    Ambas APIs son OpenAI-compatibles, el cambio es transparente.
    """

    def __init__(self):
        self._providers = []

        if config.OPENROUTER_API_KEY:
            self._providers.append({
                "name":     "OpenRouter",
                "base_url": config.OPENROUTER_BASE_URL,
                "model":    config.OPENROUTER_MODEL,
                "headers": {
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "Content-Type":  "application/json",
                    "HTTP-Referer":  "https://github.com/autoapply",
                },
            })

        if config.GROQ_API_KEY:
            self._providers.append({
                "name":     "Groq",
                "base_url": config.GROQ_BASE_URL,
                "model":    config.GROQ_MODEL,
                "headers": {
                    "Authorization": f"Bearer {config.GROQ_API_KEY}",
                    "Content-Type":  "application/json",
                },
            })

        if not self._providers:
            raise RuntimeError("No hay API keys configuradas (GROQ o OPENROUTER).")

    def chat_completions_create(
        self,
        model: str = None,          # ignorado — usa el modelo del proveedor activo
        messages: list[dict] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        max_retries: int = 3,
    ) -> GroqResponse:
        """
        Llama a /chat/completions. Intenta cada proveedor en orden.
        Si Groq da 429, cambia a OpenRouter automáticamente.
        """
        last_error = None

        for provider in self._providers:
            payload = {
                "model":       provider["model"],
                "messages":    messages,
                "max_tokens":  max_tokens,
                "temperature": temperature,
            }

            for attempt in range(1, max_retries + 1):
                try:
                    with httpx.Client(timeout=60.0) as http:
                        response = http.post(
                            f"{provider['base_url']}/chat/completions",
                            headers=provider["headers"],
                            json=payload,
                        )
                except Exception as exc:
                    logger.warning("[%s] Error de conexión: %s", provider["name"], exc)
                    last_error = exc
                    break

                if response.status_code == 200:
                    if provider["name"] != "Groq":
                        logger.info("  [%s] Request exitoso.", provider["name"])
                    return GroqResponse(response.json())

                if response.status_code == 429:
                    try:
                        err_msg = response.json().get("error", {}).get("message", response.text[:150])
                    except Exception:
                        err_msg = response.text[:150]
                    logger.warning(
                        "[%s] Rate limit (intento %d/%d): %s — esperando 30s...",
                        provider["name"], attempt, max_retries, err_msg,
                    )
                    time.sleep(30)
                    continue

                # Error no recuperable en este proveedor
                last_error = RuntimeError(
                    f"{provider['name']} error {response.status_code}: {response.text[:200]}"
                )
                logger.warning("[%s] Error %d — probando siguiente proveedor.",
                               provider["name"], response.status_code)
                break  # saltar al siguiente proveedor

            else:
                # Se agotaron los reintentos en este proveedor
                logger.warning("[%s] Rate limit agotado — cambiando a siguiente proveedor.", provider["name"])
                last_error = RuntimeError(f"{provider['name']}: rate limit agotado tras {max_retries} intentos.")
                continue  # probar el siguiente proveedor

        raise RuntimeError(
            f"Todos los proveedores fallaron. Último error: {last_error}"
        )


# ─── Instancia compartida ──────────────────────────────────────────────────────
_client = None

def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
