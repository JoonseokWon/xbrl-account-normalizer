"""User-facing local inference failures; no remote response bodies are logged."""
from core.errors import InputError


class LocalLlmError(InputError):
    pass
