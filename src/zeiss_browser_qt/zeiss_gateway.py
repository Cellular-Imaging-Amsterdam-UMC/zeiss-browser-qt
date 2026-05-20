"""Zeiss path scanning and XML-backed CZI metadata adapter.

This first implementation stage wires the copied Leica UI to `.czi` files and
returns stable Zeiss image contexts. Native libCZI-backed pixel reads are still
deferred, but embedded ImageDocument XML is parsed directly from the `.czi`
files so dimensions, channels, scenes, and scaling are real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .czi_metadata import extract_czi_xml_metadata
from .metadata import context_from_metadata
from .models import LeicaImageContext

CZI_EXTENSIONS = {".czi"}
LEICA_EXTENSIONS = CZI_EXTENSIONS
IGNORED_NAME_PARTS = (
    "metadata",
    "_pmd_",
    "_histo",
    "_environmetalgraph",
    "iomanagerconfiguation",
    "iomanagerconfiguration",
)


@dataclass
class LeicaTreeNode:
    name: str
    kind: str
    path: Path | None = None
    internal_path: str = ""
    image_id: str | None = None
    context: LeicaImageContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    folder_metadata: dict[str, Any] | None = None
    metadata_loaded: bool = False
    warning: str | None = None
    children: list["LeicaTreeNode"] = field(default_factory=list)

    @property
    def is_image(self) -> bool:
        return self.context is not None


class ConvertLeicaAdapter:
    """Compatibility shim kept temporarily while the Zeiss backend grows."""

    def __init__(self) -> None:
        self._helpers = None

    def _load_helpers(self):
        return None

    def read_tree(self, path: Path, folder_uuid: str | None = None) -> dict[str, Any]:
        raise RuntimeError("Zeiss CZI tree parsing is not implemented yet.")

    def read_image_metadata(
        self,
        path: Path,
        image_uuid: str | None,
        folder_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {}


class LeicaGateway:
    """Scan Zeiss roots and bridge the UI to XML-backed CZI metadata."""

    def __init__(self, adapter: ConvertLeicaAdapter | None = None) -> None:
        self.adapter = adapter or ConvertLeicaAdapter()

    def scan_roots(self, roots: Iterable[str | Path] | None = None) -> list[LeicaTreeNode]:
        paths = [Path(p).expanduser() for p in roots] if roots else [Path.cwd()]
        nodes: list[LeicaTreeNode] = []
        for path in paths:
            nodes.extend(self.scan_path(path))
        return nodes

    def scan_path(self, path: str | Path) -> list[LeicaTreeNode]:
        root = Path(path).expanduser()
        if root.is_dir():
            return [self._scan_directory(root)]
        if root.is_file() and root.suffix.lower() in CZI_EXTENSIONS:
            return [self.container_node(root)]
        if not root.exists():
            return [
                LeicaTreeNode(
                    name=root.name or str(root),
                    kind="warning",
                    path=root,
                    warning=f"Path does not exist: {root}",
                )
            ]
        return []

    def _scan_directory(self, path: Path) -> LeicaTreeNode:
        node = LeicaTreeNode(name=path.name or str(path), kind="folder", path=path)
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            node.warning = str(exc)
            return node

        for child in entries:
            if self._ignore_name(child.name):
                continue
            if child.is_dir():
                node.children.append(self._scan_directory(child))
            elif child.suffix.lower() in CZI_EXTENSIONS:
                node.children.append(self.container_node(child))
        return node

    def container_node(self, path: str | Path) -> LeicaTreeNode:
        container = Path(path)
        node = LeicaTreeNode(
            name=container.name,
            kind="container",
            path=container,
            internal_path=container.name,
        )

        metadata = self._safe_image_metadata(container, None, {}, {})
        image_name = container.stem or container.name
        internal_path = f"{container.name}/{image_name}"
        node.children.append(
            LeicaTreeNode(
                name=image_name,
                kind=self._image_kind(container),
                path=container,
                internal_path=internal_path,
                image_id=image_name,
                context=context_from_metadata(
                    name=image_name,
                    container_path=container,
                    internal_path=internal_path,
                    image_id=image_name,
                    kind=self._image_kind(container),
                    metadata=metadata,
                ),
                metadata=metadata,
                metadata_loaded=True,
            )
        )
        return node

    def children_for_folder(
        self,
        container: Path,
        folder_uuid: str,
        parent_internal_path: str,
    ) -> list[LeicaTreeNode]:
        return []

    def _children_from_metadata(
        self,
        container: Path,
        folder_metadata: dict[str, Any],
        parent_internal_path: str,
    ) -> list[LeicaTreeNode]:
        return []

    def hydrate_image_node(self, node: LeicaTreeNode) -> LeicaImageContext | None:
        """Load full image metadata for an image node on demand.

        Building large Leica trees is much faster when the tree is made from
        the folder-level XML only. Full image metadata can require extra LIF
        XML parsing or LOF reads, so defer it until the image is returned to
        callers.
        """

        if node.context is None:
            return None
        if node.metadata_loaded:
            return node.context
        if node.path is None:
            node.metadata_loaded = True
            return node.context

        metadata = self._safe_image_metadata(
            node.path,
            node.image_id,
            node.folder_metadata or {},
            node.metadata,
        )
        node.metadata = metadata
        node.metadata_loaded = True
        node.context = context_from_metadata(
            name=node.name,
            container_path=node.context.container_path,
            internal_path=node.internal_path,
            image_id=node.image_id,
            kind=node.kind,
            metadata=metadata,
        )
        return node.context

    def _lightweight_image_metadata(
        self,
        container: Path,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(source)
        metadata.setdefault("filetype", container.suffix.lower())
        metadata.setdefault("source_file", str(container))
        return metadata

    def _safe_image_metadata(
        self,
        container: Path,
        image_uuid: str | None,
        folder_metadata: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(fallback)
        try:
            stat = container.stat()
        except OSError as exc:
            metadata["warning"] = str(exc)
            stat = None
        try:
            metadata.update(extract_czi_xml_metadata(container))
        except Exception as exc:
            metadata.setdefault("filetype", container.suffix.lower())
            metadata.setdefault("source_file", str(container))
            metadata.setdefault("save_child_name", container.stem or container.name)
            metadata.setdefault("name", container.stem or container.name)
            metadata.setdefault("size_x", 512)
            metadata.setdefault("size_y", 384)
            metadata.setdefault("size_z", 1)
            metadata.setdefault("size_c", 1)
            metadata.setdefault("size_t", 1)
            metadata.setdefault("size_s", 1)
            metadata.setdefault(
                "dimensions",
                {"x": metadata["size_x"], "y": metadata["size_y"], "z": 1, "c": 1, "t": 1, "s": 1},
            )
            metadata.setdefault("channel_names", ["Channel 1"])
            metadata.setdefault("pixel_type", "u1")
            metadata.setdefault("placeholder_size_x", 512)
            metadata.setdefault("placeholder_size_y", 384)
            metadata.setdefault("backend_status", "placeholder")
            metadata.setdefault(
                "warning",
                f"Embedded CZI XML metadata could not be parsed; using placeholder metadata. {exc}",
            )
        if stat is not None:
            metadata["file_size_bytes"] = int(stat.st_size)
        return metadata

    def _safe_lof_metadata(self, container: Path) -> dict[str, Any]:
        return self._safe_image_metadata(container, None, {}, {})

    def read_thumbnail(self, context: LeicaImageContext, max_size: int = 512):
        from .preview import preview_png_from_metadata

        preview_path = preview_png_from_metadata(
            context.metadata,
            selected_s=context.selected_s,
            preview_height=max_size,
        )
        try:
            import cv2

            image = cv2.imread(str(preview_path), cv2.IMREAD_UNCHANGED)
            if image is not None:
                return image
        except ImportError:
            pass
        return np.asarray(preview_path)

    def read_plane(
        self,
        context: LeicaImageContext,
        z: int = 0,
        c: int = 0,
        t: int = 0,
        s: int | None = None,
    ):
        from .zeiss_pixels import read_zeiss_plane

        return read_zeiss_plane(context, z=z, c=c, t=t, s=s)

    def read_array(self, context: LeicaImageContext, s: int | None = None):
        from .zeiss_pixels import read_zeiss_array

        return read_zeiss_array(context, s=s)

    @staticmethod
    def _ignore_name(name: str) -> bool:
        low = name.lower()
        return low.endswith(".lifext") or any(part in low for part in IGNORED_NAME_PARTS)

    @staticmethod
    def _image_kind(container: Path) -> str:
        return {
            ".czi": "czi-image",
        }.get(container.suffix.lower(), "zeiss-image")


ZeissTreeNode = LeicaTreeNode
ZeissGateway = LeicaGateway
