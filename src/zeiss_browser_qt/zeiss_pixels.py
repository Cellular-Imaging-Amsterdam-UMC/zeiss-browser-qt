"""Placeholder Zeiss pixel readers used until native libCZI reads land."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .czi_native import is_czi_mosaic, native_czi_available, read_czi_mosaic_plane, read_czi_plane
from .models import LeicaImageContext


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bounded_index(name: str, value: int, size: int) -> int:
    size = max(int(size), 1)
    index = int(value)
    if index < 0 or index >= size:
        raise IndexError(f"{name} index {index} out of range for size {size}")
    return index


def _resolve_s(context: LeicaImageContext, s: int | None) -> int:
    if s is not None:
        return int(s)
    if context.selected_s is not None:
        return int(context.selected_s)
    return 0


def _resolved_shape(context: LeicaImageContext) -> tuple[int, int, int, int, int]:
    metadata = context.metadata
    size_x = max(
        _as_int(
            metadata.get("placeholder_size_x"),
            _as_int(metadata.get("xs"), context.size_x or _as_int(metadata.get("size_x"), 512)),
        ),
        1,
    )
    size_y = max(
        _as_int(
            metadata.get("placeholder_size_y"),
            _as_int(metadata.get("ys"), context.size_y or _as_int(metadata.get("size_y"), 384)),
        ),
        1,
    )
    size_z = max(_as_int(metadata.get("zs"), context.size_z or _as_int(metadata.get("size_z"), 1)), 1)
    size_c = max(_as_int(metadata.get("channels"), context.size_c or _as_int(metadata.get("size_c"), 1)), 1)
    size_t = max(_as_int(metadata.get("ts"), context.size_t or _as_int(metadata.get("size_t"), 1)), 1)
    return size_x, size_y, size_z, size_c, size_t


def _placeholder_plane(width: int, height: int, c: int, z: int, t: int, s: int) -> np.ndarray:
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
    base = (x * 120) + (y * 80)
    signal = base + c * 32 + z * 18 + t * 12 + s * 9
    signal = np.mod(signal, 255)
    return signal.astype(np.uint8)


def read_zeiss_plane(
    context: LeicaImageContext,
    *,
    z: int = 0,
    c: int = 0,
    t: int = 0,
    s: int | None = None,
) -> np.ndarray:
    """Return a deterministic placeholder Zeiss plane as a 2-D array."""

    size_x, size_y, size_z, size_c, size_t = _resolved_shape(context)
    c = _bounded_index("channel", c, size_c)
    z = _bounded_index("z", z, size_z)
    t = _bounded_index("time", t, size_t)
    resolved_s = _resolve_s(context, s)
    source_file = context.metadata.get("source_file")
    if source_file and native_czi_available():
        source_path = Path(str(source_file))
        try:
            if is_czi_mosaic(source_path):
                return read_czi_mosaic_plane(source_path, c=c, max_size=2048)
            return read_czi_plane(source_path, z=z, c=c, t=t, s=resolved_s)
        except Exception:
            pass
    return _placeholder_plane(size_x, size_y, c, z, t, resolved_s)


def read_zeiss_stack(
    context: LeicaImageContext,
    *,
    c: int = 0,
    t: int = 0,
    s: int | None = None,
    progress=None,
) -> np.ndarray:
    """Return a placeholder Zeiss stack as ``ZYX``."""

    _, _, size_z, _, _ = _resolved_shape(context)
    planes = []
    for z in range(size_z):
        planes.append(read_zeiss_plane(context, z=z, c=c, t=t, s=s))
        if progress is not None:
            progress(z + 1, size_z)
    return np.stack(planes, axis=0)


def read_zeiss_array(
    context: LeicaImageContext,
    *,
    s: int | None = None,
    progress=None,
) -> np.ndarray:
    """Return a placeholder Zeiss image as a NumPy array with shape ``TCZYX``."""

    _, _, _, size_c, size_t = _resolved_shape(context)
    total = max(size_t * size_c, 1)
    stacks = []
    done = 0
    for t in range(size_t):
        channel_stacks = []
        for c in range(size_c):
            channel_stacks.append(read_zeiss_stack(context, c=c, t=t, s=s))
            done += 1
            if progress is not None:
                progress(done, total)
        stacks.append(np.stack(channel_stacks, axis=0))
    return np.stack(stacks, axis=0)


read_leica_plane = read_zeiss_plane
read_leica_stack = read_zeiss_stack
read_leica_array = read_zeiss_array
