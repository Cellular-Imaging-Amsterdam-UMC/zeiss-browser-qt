from zeiss_browser_qt import ZeissBrowserDialog


def open_zeiss_single(parent):
    ctx = ZeissBrowserDialog.select_image_context(parent=parent)
    if ctx is None:
        return None
    handle = ctx.open()
    arr = handle.read_array()
    metadata = ctx.metadata
    return arr, metadata


def open_zeiss_multiple(parent):
    contexts = ZeissBrowserDialog.select_image_contexts(parent=parent)
    results = []
    for ctx in contexts:
        handle = ctx.open()
        results.append((handle.read_array(), ctx.metadata))
    return results

