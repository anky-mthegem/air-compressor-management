import json
import logging
from typing import AsyncGenerator, Optional
import httpx
from app.config import settings

logger = logging.getLogger("app.chatbot.ollama")

class OllamaClient:
    def __init__(self, base_url: str = settings.OLLAMA_BASE_URL, model: str = settings.OLLAMA_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def is_available(self) -> bool:
        """Checks if local Ollama daemon is running."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def stream_chat(self, system_prompt: str, user_message: str) -> AsyncGenerator[str, None]:
        """Streams tokens from local Ollama chat API."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "stream": True,
            "options": {
                "temperature": 0.3,
                "top_p": 0.9
            }
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    yield f"Error from Ollama (status {response.status_code})"
                    return
                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            if content:
                                yield content
                        except Exception:
                            continue

ollama_client = OllamaClient()
