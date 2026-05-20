from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

import cv2
import numpy as np

try:
    from aicspylibczi import CziFile
except ImportError:  # pragma: no cover - optional dependency
    CziFile = None


_DEFAULT_COLORS = [
    (0, 255, 0),
    (0, 128, 255),
    (255, 0, 255),
    (255, 0, 0),
    (0, 255, 255),
    (255, 255, 0),
]


def native_czi_available() -> bool:
    return CziFile is not None


@lru_cache(maxsize=16)
def _reader_for(path_text: str):
    if CziFile is None:
        raise RuntimeError("aicspylibczi is not available")
    return CziFile(path_text)


def read_czi_plane(
    path: Path,
    *,
    z: int = 0,
    c: int = 0,
    t: int = 0,
    s: int | None = None,
) -> np.ndarray:
    arr = read_czi_image(path, z=z, c=c, t=t, s=s)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3 and arr.shape[-1] in {3, 4}:
        return arr[..., min(int(c), arr.shape[-1] - 1)]
    raise ValueError(f"Expected a 2-D plane or RGB plane, got shape {arr.shape}")


def read_czi_image(
    path: Path,
    *,
    z: int = 0,
    c: int = 0,
    t: int = 0,
    s: int | None = None,
) -> np.ndarray:
    reader = _reader_for(str(path))
    dims = _reader_dims(reader)
    kwargs: dict[str, int] = {}
    if "S" in dims:
        kwargs["S"] = max(0, min(int(0 if s is None else s), dims["S"] - 1))
    if "T" in dims:
        kwargs["T"] = max(0, min(int(t), dims["T"] - 1))
    if "Z" in dims:
        kwargs["Z"] = max(0, min(int(z), dims["Z"] - 1))
    if "C" in dims:
        kwargs["C"] = max(0, min(int(c), dims["C"] - 1))
    arr, _shape = reader.read_image(**kwargs)
    return _normalize_native_shape(np.asarray(arr))


def create_czi_preview(
    metadata: dict[str, Any],
    *,
    selected_s: int | None = None,
    preview_height: int = 512,
) -> Path | None:
    if CziFile is None:
        return None
    source_file = metadata.get("source_file")
    if not source_file:
        return None
    source_path = Path(str(source_file))
    if not source_path.exists():
        return None

    stat = source_path.stat()
    digest = hashlib.sha1(
        json.dumps(
            [
                "native-preview-v2",
                str(source_path.resolve()),
                stat.st_mtime_ns,
                selected_s,
                int(preview_height),
                metadata.get("channel_names"),
            ],
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    out_path = _native_preview_cache_dir() / f"{digest}.png"
    if out_path.exists():
        return out_path

    try:
        preview = _render_preview_array(metadata, selected_s=selected_s, preview_height=preview_height)
    except Exception:
        return None
    if preview is None or preview.size == 0:
        return None
    preview_to_write = preview
    if preview.ndim == 3 and preview.shape[2] == 3:
        preview_to_write = cv2.cvtColor(preview, cv2.COLOR_RGB2BGR)
    if not cv2.imwrite(str(out_path), preview_to_write):
        return None
    return out_path


def _render_preview_array(
    metadata: dict[str, Any],
    *,
    selected_s: int | None,
    preview_height: int,
) -> np.ndarray | None:
    source_path = Path(str(metadata["source_file"]))
    channel_names = metadata.get("channel_names")
    size_c = max(_as_int(metadata.get("channels") or metadata.get("size_c"), 1), 1)
    size_z = max(_as_int(metadata.get("zs") or metadata.get("size_z"), 1), 1)
    size_s = max(_as_int(metadata.get("tiles") or metadata.get("size_s"), 1), 1)
    scene_index = _resolved_scene(selected_s, size_s)
    z_index = size_z // 2

    first_image = read_czi_image(source_path, z=z_index, c=0, s=scene_index)
    if first_image.ndim == 3 and first_image.shape[-1] in {3, 4}:
        rgb = _normalize_color_image(first_image[..., :3])
        return _resize_preview(rgb, preview_height)

    first_plane = np.asarray(first_image)
    height, width = first_plane.shape
    scale = max(float(preview_height) / float(max(height, 1)), 1e-6)
    out_height = max(64, int(round(height * scale)))
    out_width = max(64, int(round(width * scale)))

    if size_c == 1:
        plane = _normalize_plane(first_plane)
        name = channel_names[0] if isinstance(channel_names, list) and channel_names else "Channel 1"
        color = _channel_color(name, 0)
        rgb = np.dstack([
            (plane * (color[0] / 255.0)).astype(np.uint8),
            (plane * (color[1] / 255.0)).astype(np.uint8),
            (plane * (color[2] / 255.0)).astype(np.uint8),
        ])
        return cv2.resize(rgb, (out_width, out_height), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((height, width, 3), dtype=np.float32)
    for channel_index in range(size_c):
        plane = read_czi_plane(source_path, z=z_index, c=channel_index, s=scene_index)
        plane8 = _normalize_plane(plane).astype(np.float32)
        name = channel_names[channel_index] if isinstance(channel_names, list) and channel_index < len(channel_names) else f"Channel {channel_index + 1}"
        color = _channel_color(name, channel_index)
        canvas[..., 0] += plane8 * (color[0] / 255.0)
        canvas[..., 1] += plane8 * (color[1] / 255.0)
        canvas[..., 2] += plane8 * (color[2] / 255.0)
    rgb = np.clip(canvas, 0.0, 255.0).astype(np.uint8)
    return cv2.resize(rgb, (out_width, out_height), interpolation=cv2.INTER_AREA)


def _resize_preview(rgb: np.ndarray, preview_height: int) -> np.ndarray:
    height, width = rgb.shape[:2]
    scale = max(float(preview_height) / float(max(height, 1)), 1e-6)
    out_height = max(64, int(round(height * scale)))
    out_width = max(64, int(round(width * scale)))
    return cv2.resize(rgb, (out_width, out_height), interpolation=cv2.INTER_AREA)


def _normalize_plane(plane: np.ndarray) -> np.ndarray:
    arr = np.asarray(plane, dtype=np.float32)
    lo, hi = np.percentile(arr, [1.0, 99.8])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        hi = lo + 1.0
    return np.clip((arr - lo) * (255.0 / (hi - lo)), 0.0, 255.0).astype(np.uint8)


def _normalize_color_image(image: np.ndarray) -> np.ndarray:
    channels = [_normalize_plane(image[..., idx]) for idx in range(image.shape[-1])]
    return np.dstack(channels[:3])


def _channel_color(name: str, index: int) -> tuple[int, int, int]:
    low = str(name).strip().lower()
    if any(token in low for token in ("dapi", "hoechst", "405")):
        return 0, 128, 255
    if any(token in low for token in ("488", "fitc", "gfp", "alexa fluor 488")):
        return 0, 255, 0
    if any(token in low for token in ("568", "594", "tritc", "cy3")):
        return 255, 128, 0
    if any(token in low for token in ("647", "660", "cy5", "alexa fluor 647")):
        return 255, 0, 128
    return _DEFAULT_COLORS[index % len(_DEFAULT_COLORS)]


def _resolved_scene(selected_s: int | None, size_s: int) -> int:
    if selected_s is None:
        return max(size_s // 2, 0)
    return max(0, min(int(selected_s), max(size_s - 1, 0)))


def _as_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _native_preview_cache_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "zeiss_browser_qt_native_preview_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _reader_dims(reader: Any) -> dict[str, int]:
    return {axis: int(length) for axis, length in zip(str(reader.dims), getattr(reader, "size", ()), strict=False)}


def _normalize_native_shape(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr)
    while arr.ndim > 0 and arr.shape[0] == 1:
        arr = arr[0]
    while arr.ndim > 0 and arr.shape[-1] == 1:
        arr = arr[..., 0]
    if arr.ndim == 3 and arr.shape[0] in {3, 4} and arr.shape[-1] not in {3, 4}:
        arr = np.moveaxis(arr, 0, -1)
    return arr