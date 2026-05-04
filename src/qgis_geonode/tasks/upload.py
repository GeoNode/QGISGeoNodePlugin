"""Multipart payload assembly for layer uploads to GeoNode.

This module is consumed exclusively by :class:`LayerUploaderTask` and is
GeoNode-specific (form-field names, permissions shape, ``action=upload``
flag) — it doesn't belong in the generic transport layer.
"""

import json
import typing

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)


def build_multipart(
    layer_metadata: qgis.core.QgsLayerMetadata,
    permissions: typing.Dict,
    main_file: QtCore.QFile,
    sidecar_files: typing.List[typing.Tuple[str, QtCore.QFile]],
) -> QtNetwork.QHttpMultiPart:
    encoding = "utf-8"
    multipart = QtNetwork.QHttpMultiPart(QtNetwork.QHttpMultiPart.FormDataType)
    title = layer_metadata.title()
    if title:
        title_part = QtNetwork.QHttpPart()
        title_part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            'form-data; name="dataset_title"',
        )
        title_part.setBody(layer_metadata.title().encode(encoding))
        multipart.append(title_part)
    abstract = layer_metadata.abstract()
    if abstract:
        abstract_part = QtNetwork.QHttpPart()
        abstract_part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            'form-data; name="abstract"',
        )
        abstract_part.setBody(layer_metadata.abstract().encode(encoding))
        multipart.append(abstract_part)
    false_items = (
        "time",
        "mosaic",
        "metadata_uploaded_preserve",
        "metadata_upload_form",
        "style_upload_form",
    )
    for item in false_items:
        part = QtNetwork.QHttpPart()
        part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            f'form-data; name="{item}"',
        )
        part.setBody("false".encode("utf-8"))
        multipart.append(part)

    action_part = QtNetwork.QHttpPart()
    action_part.setHeader(
        QtNetwork.QNetworkRequest.ContentDispositionHeader,
        'form-data; name="action"',
    )
    action_part.setBody("upload".encode("utf-8"))
    multipart.append(action_part)

    permissions_part = QtNetwork.QHttpPart()
    permissions_part.setHeader(
        QtNetwork.QNetworkRequest.ContentDispositionHeader,
        'form-data; name="permissions"',
    )
    permissions_part.setBody(json.dumps(permissions).encode(encoding))
    multipart.append(permissions_part)
    file_parts = [("base_file", main_file)]
    for additional_file_form_name, additional_file_handler in sidecar_files:
        file_parts.append((additional_file_form_name, additional_file_handler))
    for form_element_name, file_handler in file_parts:
        file_name = file_handler.fileName().rpartition("/")[-1]
        part = QtNetwork.QHttpPart()
        part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            f'form-data; name="{form_element_name}"; filename="{file_name}"',
        )
        if file_name.rpartition(".")[-1] == "tif":
            content_type = "image/tiff"
        else:
            content_type = "application/qgis"
        part.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, content_type)
        part.setBodyDevice(file_handler)
        multipart.append(part)
    return multipart
