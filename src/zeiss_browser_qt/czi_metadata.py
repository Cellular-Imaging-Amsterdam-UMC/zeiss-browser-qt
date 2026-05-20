from __future__ import annotations

from pathlib import Path
from typing import Any
from collections import Counter
import xml.etree.ElementTree as ET

from .czi_native import native_czi_available


def extract_czi_xml_metadata(path: Path) -> dict[str, Any]:
    """Extract a normalized metadata dict from embedded CZI ImageDocument XML."""

    xml_text = _extract_image_document_xml(path)
    root = ET.fromstring(xml_text)
    image = root.find(".//Information/Image")

    global_size_x = _as_int(_find_text(image, "SizeX")) or 512
    global_size_y = _as_int(_find_text(image, "SizeY")) or 384
    size_z = _as_int(_find_text(image, "SizeZ")) or 1
    size_c = _as_int(_find_text(image, "SizeC")) or _count_channels(root) or 1
    size_t = _as_int(_find_text(image, "SizeT")) or 1
    size_s = _as_int(_find_text(image, "SizeS")) or _count_scenes(root) or 1
    size_m = _as_int(_find_text(image, "SizeM"))
    scene_frame = _preferred_scene_frame(root)
    if size_s > 1 and scene_frame is not None:
        size_x, size_y = scene_frame
    else:
        size_x, size_y = global_size_x, global_size_y

    scene_names = [
        scene.attrib.get("Name") or f"Scene {idx + 1}"
        for idx, scene in enumerate(root.findall(".//Information/Image/Dimensions/S/Scenes/Scene"))
    ]
    channel_names = _channel_names(root, size_c)
    pixel_type = (_find_text(image, "PixelType") or "").strip()
    component_bit_count = _as_int(_find_text(image, "ComponentBitCount"))
    channel_resolution = _channel_resolution(pixel_type, component_bit_count, size_c)
    is_rgb = pixel_type.lower() in {"bgr24", "bgr48", "rgb24", "rgb48"}
    scaling = _scaling_meters(root)
    placeholder_size_x, placeholder_size_y = _placeholder_shape(size_x, size_y)

    metadata = {
        "filetype": ".czi",
        "source_file": str(path),
        "save_child_name": path.stem or path.name,
        "name": path.stem or path.name,
        "global_size_x": global_size_x,
        "global_size_y": global_size_y,
        "size_x": size_x,
        "size_y": size_y,
        "size_z": size_z,
        "size_c": size_c,
        "size_t": size_t,
        "size_s": size_s,
        "size_m": size_m,
        "xs": size_x,
        "ys": size_y,
        "zs": size_z,
        "channels": size_c,
        "ts": size_t,
        "tiles": size_s,
        "dimensions": {"x": size_x, "y": size_y, "z": size_z, "c": size_c, "t": size_t, "s": size_s},
        "channel_names": channel_names,
        "scene_names": scene_names,
        "pixel_type": pixel_type or "u1",
        "component_bit_count": component_bit_count,
        "channelResolution": channel_resolution,
        "isrgb": is_rgb,
        "placeholder_size_x": placeholder_size_x,
        "placeholder_size_y": placeholder_size_y,
        "backend_status": "xml-metadata",
        "experiment_datetime": _first_text(
            root,
            ".//Information/Image/AcquisitionDateAndTime",
            ".//Information/Document/CreationDate",
        ),
    }

    if scaling.get("x") is not None:
        metadata["xres"] = scaling["x"]
        metadata["xres2"] = scaling["x"] * 1_000_000.0
    if scaling.get("y") is not None:
        metadata["yres"] = scaling["y"]
        metadata["yres2"] = scaling["y"] * 1_000_000.0
    if scaling.get("z") is not None:
        metadata["zres"] = scaling["z"]
        metadata["zres2"] = scaling["z"] * 1_000_000.0
    if any(key in metadata for key in ("xres", "yres", "zres")):
        metadata["resunit"] = "m"
        metadata["resunit2"] = "micrometer"
    if native_czi_available():
        metadata["pixel_backend"] = "native"

    return metadata


def _extract_image_document_xml(path: Path) -> str:
    data = path.read_bytes()
    start = data.find(b"<ImageDocument")
    end = data.find(b"</ImageDocument>")
    if start == -1 or end == -1:
        raise ValueError(f"Embedded ImageDocument XML not found in {path}")
    xml_bytes = data[start : end + len(b"</ImageDocument>")]
    return xml_bytes.decode("utf-8", "ignore")


def _find_text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _first_text(root: ET.Element, *paths: str) -> str | None:
    for path in paths:
        value = root.findtext(path)
        if value is not None:
            value = value.strip()
            if value:
                return value
    return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _count_channels(root: ET.Element) -> int:
    return len(root.findall(".//DisplaySetting//Channel")) or len(root.findall(".//Information/Image/Dimensions/Channels/Channel"))


def _count_scenes(root: ET.Element) -> int:
    return len(root.findall(".//Information/Image/Dimensions/S/Scenes/Scene"))


def _channel_names(root: ET.Element, count: int) -> list[str]:
    names = [channel.attrib.get("Name") for channel in root.findall(".//DisplaySetting//Channel") if channel.attrib.get("Name")]
    if not names:
        names = [channel.attrib.get("Name") for channel in root.findall(".//Information/Image/Dimensions/Channels/Channel") if channel.attrib.get("Name")]
    if names:
        if len(names) < count:
            names.extend(f"Channel {idx + 1}" for idx in range(len(names), count))
        return names[:count]
    return [f"Channel {idx + 1}" for idx in range(count)]


def _channel_resolution(pixel_type: str, component_bit_count: int | None, size_c: int) -> list[int]:
    if pixel_type.lower() in {"bgr24", "rgb24"}:
        return [8, 8, 8]
    if pixel_type.lower() in {"bgr48", "rgb48"}:
        return [16, 16, 16]
    bit_count = component_bit_count or 8
    return [bit_count] * max(size_c, 1)


def _scaling_meters(root: ET.Element) -> dict[str, float | None]:
    result: dict[str, float | None] = {"x": None, "y": None, "z": None}
    for distance in root.findall(".//Scaling//Distance"):
        axis = str(distance.attrib.get("Id") or "").strip().lower()
        value = _as_float(distance.findtext("Value"))
        if axis in result:
            result[axis] = value
    return result


def _placeholder_shape(size_x: int, size_y: int, max_long_edge: int = 1536) -> tuple[int, int]:
    if size_x <= 0 or size_y <= 0:
        return 512, 384
    long_edge = max(size_x, size_y)
    if long_edge <= max_long_edge:
        return size_x, size_y
    scale = max_long_edge / float(long_edge)
    return max(64, int(round(size_x * scale))), max(64, int(round(size_y * scale)))


def _preferred_scene_frame(root: ET.Element) -> tuple[int, int] | None:
    """Return a stable per-scene XY frame when the CZI XML exposes one."""

    for tag in ("ImageFrame", "Frame"):
        sizes = []
        for element in root.iter(tag):
            rect = _parse_rect((element.text or "").strip())
            if rect is None:
                continue
            _, _, width, height = rect
            if width > 0 and height > 0:
                sizes.append((width, height))
        if sizes:
            return Counter(sizes).most_common(1)[0][0]
    return None


def _parse_rect(text: str) -> tuple[int, int, int, int] | None:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        return None
    values = [_as_int(part) for part in parts]
    if any(value is None for value in values):
        return None
    return values[0], values[1], values[2], values[3]