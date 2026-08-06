"""Very small metrics facade.

If the project later adopts prometheus_client (or any other library) only
:func:`increment` needs to change. When no metrics backend is available the
counters are kept in-process so tests and ``/metrics`` style debugging still
work, and callers never have to branch.
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Dict, Optional, Tuple

__all__ = ["increment", "snapshot", "reset", "RATE_LIMIT_REJECTIONS_TOTAL"]

RATE_LIMIT_REJECTIONS_TOTAL = "rate_limit_rejections_total"

_lock = threading.Lock()
_counters: "Counter[Tuple[str, Tuple[Tuple[str, str], ...]]]" = Counter()

try:  # pragma: no cover - optional dependency
    from prometheus_client import Counter as PromCounter  # type: ignore
except Exception:  # noqa: BLE001 - prometheus_client is optional
    PromCounter = None  # type: ignore

_prom_counters: Dict[str, object] = {}


def _prom_counter(name: str, label_names: Tuple[str, ...]):  # pragma: no cover
    if PromCounter is None:
        return None
    counter = _prom_counters.get(name)
    if counter is None:
        counter = PromCounter(name, name.replace("_", " "), list(label_names))
        _prom_counters[name] = counter
    return counter


def increment(
    name: str, value: int = 1, labels: Optional[Dict[str, str]] = None
) -> None:
    """Increment a counter metric; never raises."""
    label_items = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
    with _lock:
        _counters[(name, label_items)] += value
    try:  # pragma: no cover - only when prometheus_client is installed
        counter = _prom_counter(name, tuple(k for k, _ in label_items))
        if counter is not None:
            if label_items:
                counter.labels(**dict(label_items)).inc(value)
            else:
                counter.inc(value)
    except Exception:  # noqa: BLE001 - metrics must never break a request
        pass


def snapshot() -> Dict[Tuple[str, Tuple[Tuple[str, str], ...]], int]:
    with _lock:
        return dict(_counters)


def get(name: str, labels: Optional[Dict[str, str]] = None) -> int:
    label_items = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
    with _lock:
        return _counters.get((name, label_items), 0)


def reset() -> None:
    with _lock:
        _counters.clear()
