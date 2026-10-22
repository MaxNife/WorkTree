"""Compatibility import for the process-wide secret masker.

The implementation lives in :mod:`app.domain.masking` so that domain contracts (activities)
can use it without depending on a higher layer.
"""

from app.domain.masking import MASK, MASKER, SecretMasker, get_masker

__all__ = ["MASK", "MASKER", "SecretMasker", "get_masker"]
