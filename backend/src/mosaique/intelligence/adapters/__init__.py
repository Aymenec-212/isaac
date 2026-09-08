"""Concrete `LLMProvider` implementations.

Same shape as `speech/adapters/`: the translation between our contract and a
vendor's wire format lives here, and the socket that carries it does not. The
transport is injected (`llm_runtime/`), which is what lets every line below be
tested without a network or an API key.
"""
