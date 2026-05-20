from PyQt6.QtWidgets import QApplication

from zeiss_browser_qt import ZeissBrowserDialog


app = QApplication([])
ctx = ZeissBrowserDialog.select_image_context()
if ctx is not None:
    print(ctx.to_dict())

