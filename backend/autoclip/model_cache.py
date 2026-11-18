"""Process-wide cache for models that are expensive to load.

Whisper weights take seconds to tens of seconds to load and hundreds of
megabytes of RAM. Reloading them for every job is wasteful; keeping them forever
means the only way to free that memory is to quit the app. The engine control in
the header exposes exactly those two operations — load once, unload on demand —
so the cache is the one place that owns the loaded objects.

Only model *objects* live here. Weights on disk are untouched by
:func:`clear`, so unloading and restarting never re-downloads anything.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)

_lock = threading.RLock()
_whisper: Any | None = None
_whisper_key: tuple[str, str, str] | None = None


def get_whisper_model(name: str, device: str, compute_type: str):
    """Return a loaded Whisper model, loading it if the key changed.

    The key includes the device and compute type as well as the model name: a
    job that overrides either one needs a different model object, and silently
    reusing one built for another device is how you get a crash deep inside
    CTranslate2 instead of a clear reload.
    """
    global _whisper, _whisper_key

    key = (name, device, compute_type)
    with _lock:
        if _whisper is not None and _whisper_key == key:
            return _whisper

        # Drop the old model before building the next one so the peak resident
        # size is one model, not two.
        _whisper = None
        _whisper_key = None

        from faster_whisper import WhisperModel

        log.info("Loading Whisper model %s (device=%s, compute=%s).", name, device, compute_type)
        model = WhisperModel(name, device=device, compute_type=compute_type)
        _whisper = model
        _whisper_key = key
        log.info("Whisper model %s loaded.", name)
        return model


def loaded_whisper() -> str | None:
    """Name of the cached model, or None when nothing is loaded."""
    with _lock:
        if _whisper is None or _whisper_key is None:
            return None
        return _whisper_key[0]


def clear() -> list[str]:
    """Unload every cached model and return what was freed."""
    global _whisper, _whisper_key

    with _lock:
        freed = [key[0] for key in ([_whisper_key] if _whisper_key else [])]
        _whisper = None
        _whisper_key = None
    if freed:
        log.info("Unloaded model(s): %s.", ", ".join(freed))
    return freed
