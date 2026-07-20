"""Conservative PySide6 pruning rules for the frozen host build."""


EXCLUDED_QT_BINARY_PREFIXES = (
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Graphs",
    "Qt6Location",
    "Qt6Multimedia",
    "Qt6Pdf",
    "Qt6Quick3D",
    "Qt6QuickTest",
    "Qt6RemoteObjects",
    "Qt6Scxml",
    "Qt6Sensors",
    "Qt6SerialPort",
    "Qt6TextToSpeech",
    "Qt6WebView",
    "QtCharts",
    "QtDataVisualization",
    "QtGraphs",
    "QtLocation",
    "QtMultimedia",
    "QtPdf",
    "QtQuick3D",
    "QtQuickTest",
    "QtRemoteObjects",
    "QtScxml",
    "QtSensors",
    "QtSerialPort",
    "QtTextToSpeech",
    "QtWebView",
)

EXCLUDED_QT_DATA_NAMES = {
    "qtwebengine_devtools_resources.debug.pak",
    "qtwebengine_resources.debug.pak",
    "qtwebengine_resources_100p.debug.pak",
    "qtwebengine_resources_200p.debug.pak",
    "v8_context_snapshot.debug.bin",
}


def is_excluded_qt_binary(destination):
    name = str(destination).replace("\\", "/").rsplit("/", 1)[-1]
    return name.startswith(EXCLUDED_QT_BINARY_PREFIXES)


def _filter_entries(entries, is_excluded):
    retained = [entry for entry in entries if not is_excluded(entry[0])]
    if type(entries) is list:
        return retained
    return type(entries)(retained)


def prune_qt_binaries(entries):
    return _filter_entries(entries, is_excluded_qt_binary)


def is_excluded_qt_data(destination):
    normalized = str(destination).replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    wrapped = f"/{normalized}"
    if "/pyside6/resources/" in wrapped and name in EXCLUDED_QT_DATA_NAMES:
        return True
    if "/pyside6/translations/qtwebengine_locales/" in wrapped:
        return name not in {"en-us.pak", "zh-cn.pak", "zh-tw.pak"}
    if "/pyside6/translations/" in wrapped and name.endswith(".qm"):
        return not (name.endswith("_zh_cn.qm") or name.endswith("_zh_tw.qm"))
    return False


def prune_qt_data(entries):
    return _filter_entries(entries, is_excluded_qt_data)
