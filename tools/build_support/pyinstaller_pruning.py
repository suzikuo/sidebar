"""Conservative PySide6 pruning rules for the frozen host build."""


EXCLUDED_QT_BINARY_PREFIXES = (
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Graphs",
    "Qt6Location",
    "Qt6Multimedia",
    "Qt6Pdf",
    "Qt6Labs",
    "Qt6OpenGL",
    "Qt6Qml",
    "Qt6Quick",
    "Qt6ShaderTools",
    "Qt6RemoteObjects",
    "Qt6Scxml",
    "Qt6Sensors",
    "Qt6SerialPort",
    "Qt6TextToSpeech",
    "Qt6WebEngineCore",
    "Qt6WebEngineQuick",
    "Qt6WebEngineWidgets",
    "Qt63D",
    "QtCharts",
    "QtDataVisualization",
    "QtGraphs",
    "QtLocation",
    "QtMultimedia",
    "QtPdf",
    "QtLabs",
    "QtOpenGL",
    "QtQml",
    "QtQuick",
    "QtShaderTools",
    "QtRemoteObjects",
    "QtScxml",
    "QtSensors",
    "QtSerialPort",
    "QtTextToSpeech",
    "QtWebEngineCore",
    "QtWebEngineQuick",
    "QtWebEngineWidgets",
)

EXCLUDED_QT_DATA_NAMES = {
    "qtwebengine_devtools_resources.debug.pak",
    "qtwebengine_resources.debug.pak",
    "qtwebengine_resources_100p.debug.pak",
    "qtwebengine_resources_200p.debug.pak",
    "v8_context_snapshot.debug.bin",
    # Chromium DevTools are not exposed by the application.
    "qtwebengine_devtools_resources.pak",
}


def is_excluded_qt_binary(destination):
    name = str(destination).replace("\\", "/").rsplit("/", 1)[-1]
    return name.casefold() == "opengl32sw.dll" or name.startswith(
        EXCLUDED_QT_BINARY_PREFIXES
    )


def _filter_entries(entries, is_excluded):
    retained = [entry for entry in entries if not is_excluded(entry[0])]
    if type(entries) is list:
        return retained
    return type(entries)(retained)


def prune_qt_binaries(entries, *, include_webengine=False):
    def is_excluded(destination):
        if is_excluded_qt_binary(destination):
            return True
        name = str(destination).replace("\\", "/").rsplit("/", 1)[-1].lower()
        return name.startswith(("qt6webengine", "qtwebengine"))

    return _filter_entries(entries, is_excluded)


def is_excluded_qt_data(destination, *, include_webengine=False):
    normalized = str(destination).replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    wrapped = f"/{normalized}"
    if name.startswith(("qtwebengine", "icudtl", "v8_context_snapshot")):
        return True
    if "/qtwebengine_locales/" in wrapped:
        return True
    if "/pyside6/qml/" in wrapped:
        return True
    if "/pyside6/resources/" in wrapped and name in EXCLUDED_QT_DATA_NAMES:
        return True
    if "/pyside6/translations/" in wrapped and name.endswith(".qm"):
        return not (name.endswith("_zh_cn.qm") or name.endswith("_zh_tw.qm"))
    return False


def prune_qt_data(entries, *, include_webengine=True):
    return _filter_entries(
        entries,
        lambda destination: is_excluded_qt_data(
            destination,
            include_webengine=include_webengine,
        ),
    )
