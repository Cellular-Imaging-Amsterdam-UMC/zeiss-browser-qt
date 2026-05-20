"""Reusable PyQt6 browser for Zeiss CZI image containers."""

from .api import (
    ZeissBrowserDialog,
    ZeissGateway,
    ZeissImageContext,
    ZeissImageHandle,
)

__all__ = [
    "ZeissBrowserDialog",
    "ZeissGateway",
    "ZeissImageContext",
    "ZeissImageHandle",
    "ZeissViewerWindow",
]


def __getattr__(name: str):
    if name == "ZeissViewerWindow":
        from .zeiss_viewer import ZeissViewerWindow

        return ZeissViewerWindow
    raise AttributeError(name)
