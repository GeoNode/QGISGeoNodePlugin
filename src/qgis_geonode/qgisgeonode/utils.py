from PyQt5.QtCore import QCoreApplication


def tr(text):
    """Get the translation for a string usingg Qt translation API.
    """

    # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
    if type(text) != str:
        text = str(text)
    return QCoreApplication.translate('QgisGeoNode', text)
