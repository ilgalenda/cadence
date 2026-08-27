"""One process-wide concurrency governor, replacing the two independent
`threading.Semaphore(1)` globals in the lead and high-intent pipelines.

Applied at pipeline *orchestration* boundaries only — never around an interactive
chat stream, or a long batch run would serialize chat behind it. The default of
1 preserves the safest behaviour under the org's TPM ceiling; raise
MIND_MAX_CONCURRENCY only with confirmed headroom.

Note: merging the two previously-independent slots into one shared slot is a real
behaviour change — the lead and high-intent pipelines used to run concurrently
and now contend for this single slot at concurrency 1.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager


def _max_concurrency() -> int:
    try:
        return max(1, int(os.getenv("MIND_MAX_CONCURRENCY", "1")))
    except ValueError:
        return 1


_GOV = threading.BoundedSemaphore(_max_concurrency())


@contextmanager
def slot():
    """Acquire the shared governor slot for the duration of the block."""
    _GOV.acquire()
    try:
        yield
    finally:
        _GOV.release()
