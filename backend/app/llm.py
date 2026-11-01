
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

load_dotenv(Path(".env").resolve())


def get_chat_model(provider: str | None = None):
    """Return the configured chat model."""
    provider = (provider or os.getenv("LLM_PROVIDER", "openai")).lower()

    if provider == "openai":
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        return ChatOpenAI(
            model=model_name,
            temperature=0,
        )

    if provider == "ollama":
        model_name = os.getenv("OLLAMA_MODEL", "llama3.2")
        base_url = os.getenv(
            "OLLAMA_BASE_URL",
            "http://localhost:11434",
        )

        return ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=0,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")
