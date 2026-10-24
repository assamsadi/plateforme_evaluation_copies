from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.core.config import settings


def get_llm(provider: str):

    if provider == "groq":
        return ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model="llama-3.3-70b-versatile",
            temperature=0.2,
        )

    elif provider == "openai":
        return ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.2,
        )

    else:
        raise ValueError(
            f"Provider LLM inconnu: {provider}"
        )