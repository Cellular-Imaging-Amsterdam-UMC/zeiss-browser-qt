from PyQt6.QtWidgets import QApplication

from zeiss_browser_qt import ZeissBrowserDialog


app = QApplication([])
contexts = ZeissBrowserDialog.select_image_contexts()
for ctx in contexts:
    print(ctx.to_dict())
