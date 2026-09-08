"""Provider plumbing for meeting intelligence: HTTP client and composition root.

Peer of `asr_runtime/`. Nothing in `intelligence/` imports this package; the
dependency runs the other way, which is what the seam is for.
"""

from mosaique.llm_runtime.factory import build_llm_provider
from mosaique.llm_runtime.http import HttpJsonTransport

__all__ = ["HttpJsonTransport", "build_llm_provider"]
