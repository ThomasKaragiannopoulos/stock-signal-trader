"""Shared LLM call wrapper with exponential-backoff retry."""
from openai import APIError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@retry(
    retry=retry_if_exception_type((RateLimitError, APIError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
def llm_complete(client, **kwargs):
    """OpenAI chat completion with retry on transient API errors."""
    return client.chat.completions.create(**kwargs)
