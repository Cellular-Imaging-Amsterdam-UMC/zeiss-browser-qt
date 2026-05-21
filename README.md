# zeiss-browser-qt

Reusable PyQt6 dialog and viewer for browsing Zeiss `.czi` files and returning
selected image contexts to another application.

The current implementation mirrors the established browser UI, but uses a
Zeiss-specific package surface and CZI metadata extraction.

## Install

Install from [PyPI](https://pypi.org/project/zeiss-browser-qt/):

```bash
pip install zeiss-browser-qt
```

Or install in editable mode for development:

```bash
pip install -e .
```

## Current Status

- The browser scans `.czi` files and opens them in a Zeiss-branded browser and
    viewer.
- Embedded `ImageDocument` XML is parsed directly from the `.czi` bytes, so the
    browser now shows real image dimensions, scene count, channel names,
    acquisition time, pixel type, and pixel size metadata.
- When `aicspylibczi` is available, the browser and viewer use real native CZI
    reads for scene previews and viewer planes.
- Multi-scene CZI data are exposed as the `S` axis. The browser can leave `S`
    as `All` or pin a fixed scene before returning a context.
- The viewer already supports channel toggles, contrast, projection mode,
    zooming, scale bar display, Z/T controls, and S controls.
- Embedded attachment thumbnails are only used as a fallback when a native
    scene preview is unavailable and the attachment is still meaningful.

## Single Select

```python
from PyQt6.QtWidgets import QApplication
from zeiss_browser_qt import ZeissBrowserDialog

app = QApplication([])
ctx = ZeissBrowserDialog.select_image_context(roots=[r"D:\data"])
if ctx is not None:
        print(ctx.name, ctx.container_path, ctx.internal_path)
        print("size_s=", ctx.size_s, "selected_s=", ctx.selected_s)
```

## Multi Select

```python
from PyQt6.QtWidgets import QApplication
from zeiss_browser_qt import ZeissBrowserDialog

app = QApplication([])
contexts = ZeissBrowserDialog.select_image_contexts(
        roots=[r"D:\data\plate1.czi", r"D:\data\run2.czi"],
)
for ctx in contexts:
        print(ctx.name, ctx.container_path, ctx.internal_path)
```

## CLI

```bash
zeiss_browser D:\data
zeiss_browser D:\data\sample.czi --multi
python -m zeiss_browser_qt.cli D:\data\sample.czi --single
zeiss_viewer
run_viewer.cmd
python -m zeiss_browser_qt.zeiss_viewer
```

The CLI prints selected contexts as JSON.

## Viewer

```python
from PyQt6.QtWidgets import QApplication
from zeiss_browser_qt import ZeissViewerWindow

app = QApplication([])
win = ZeissViewerWindow()
win.show()
app.exec()
```

Browser and viewer `S` behavior:

- `All` in the browser keeps the full `S` dimension available and the viewer
    shows an `S` slider for interactive browsing.
- `Fixed` in the browser pins one `S` scene on the returned context and the
    viewer opens that scene directly.

## Direct Pixel Reads

The public API already exposes:

```python
handle = ctx.open()

plane = handle.read_plane(z=0, c=0, t=0, s=3)
stack = handle.read_stack(c=0, t=0, s=3)
arr = handle.read_array(s=3)
```

When the native backend is available, those reads return real CZI pixel data.
If the native backend is unavailable or a file variant cannot be read yet, the
code falls back to safe placeholder arrays.

## Known Limitations

- Some CZI variants may still fall back to generated placeholders if the native
    reader cannot open them yet.
- The current browser treats `S` as scene selection only. Mosaic/tile (`M`)
    stitching is supported.
- Some older tests and compatibility shims are still being retired as the Zeiss
    surface replaces the initial Leica-based port.
