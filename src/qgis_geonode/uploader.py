import dataclasses
import json
import tempfile
import typing
from pathlib import Path

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from . import network
from .utils import log


@dataclasses.dataclass()
class ExportFormat:
    driver_name: str
    file_extension: str


class LayerUploaderTask(network.NetworkRequestTask):
    VECTOR_UPLOAD_FORMAT: typing.Final[ExportFormat] = ExportFormat(
        "ESRI Shapefile", "shp"
    )
    RASTER_UPLOAD_FORMAT: typing.Final[ExportFormat] = ExportFormat("GTiff", "tif")

    layer: qgis.core.QgsMapLayer
    allow_public_access: bool
    _upload_url: QtCore.QUrl
    _temporary_directory: typing.Optional[Path]

    def __init__(
        self,
        layer: qgis.core.QgsMapLayer,
        upload_url: QtCore.QUrl,
        allow_public_access: bool,
        authcfg: str,
        network_task_timeout: int,
        description: str = "LayerUploaderTask",
    ):
        super().__init__(
            requests_to_perform=[],
            authcfg=authcfg,
            description=description,
            network_task_timeout=network_task_timeout,
        )
        self.response_contents = [None]
        self.layer = layer
        self.allow_public_access = allow_public_access
        self._upload_url = upload_url
        self._temporary_directory = None

    def run(self) -> bool:
        if self._is_layer_uploadable():
            log("Layer is in a format natively supported, no need to export.")
            source_path = Path(
                self.layer.dataProvider().dataSourceUri().partition("|")[0]
            )
            export_error = None
        else:  # we need to export the layer first
            log(
                "Exporting layer to an uploadable format before proceeding with "
                "the upload..."
            )
            source_path, export_error = self._export_layer_to_temp_dir()
        log(f"source_path: {source_path}")
        if export_error is None:
            multipart = self._prepare_multipart(source_path)
            with network.wait_for_signal(
                self._all_requests_finished, timeout=self.network_task_timeout
            ) as event_loop_result:
                request = QtNetwork.QNetworkRequest(self._upload_url)
                request.setHeader(
                    QtNetwork.QNetworkRequest.ContentTypeHeader,
                    f"multipart/form-data; boundary={multipart.boundary().data().decode()}",
                )
                if self.authcfg:
                    auth_manager = qgis.core.QgsApplication.authManager()
                    auth_added, _ = auth_manager.updateNetworkRequest(
                        request, self.authcfg
                    )
                else:
                    auth_added = True
                if auth_added:
                    qt_reply = self._dispatch_request(
                        request, network.HttpMethod.POST, multipart
                    )
                    multipart.setParent(qt_reply)
                    request_id = qt_reply.property("requestId")
                    self._pending_replies[request_id] = (0, qt_reply)
                else:
                    self._all_requests_finished.emit()
            loop_forcibly_ended = not bool(event_loop_result.result)
            log(f"loop_forcibly_ended: {loop_forcibly_ended}")
            if loop_forcibly_ended:
                result = False
            else:
                result = self._num_finished >= len(self.requests_to_perform)
        else:
            result = False
        return result

    def finished(self, result: bool) -> None:
        if self._temporary_directory is not None:
            log(
                f"About to delete the temporary directory "
                f"at {self._temporary_directory} ..."
            )
            # shutil.rmtree(self._temporary_directory, ignore_errors=True)
        super().finished(result)

    def _prepare_multipart(self, source_path: Path) -> QtNetwork.QHttpMultiPart:
        main_file = QtCore.QFile(str(source_path))
        main_file.open(QtCore.QIODevice.ReadOnly)
        sidecar_files = []
        if self.layer.type() == qgis.core.QgsMapLayerType.VectorLayer:
            dbf_file = QtCore.QFile(str(source_path.parent / f"{source_path.stem}.dbf"))
            dbf_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("dbf_file", dbf_file))
            prj_file = QtCore.QFile(str(source_path.parent / f"{source_path.stem}.prj"))
            prj_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("prj_file", prj_file))
            shx_file = QtCore.QFile(str(source_path.parent / f"{source_path.stem}.shx"))
            shx_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("shx_file", shx_file))
        permissions = {
            "users": {},
            "groups": {},
        }
        if self.allow_public_access:
            permissions["users"]["AnonymousUser"] = [
                "view_resourcebase",
                "download_resourcebase",
            ]
        multipart = build_multipart(
            self.layer.metadata(), permissions, main_file, sidecar_files=sidecar_files
        )
        main_file.setParent(multipart)
        for _, qt_file in sidecar_files:
            qt_file.setParent(multipart)
        return multipart

    def _is_layer_uploadable(self) -> bool:
        ds_uri = self.layer.dataProvider().dataSourceUri()
        fragment = ds_uri.split("|")[0]
        extension = fragment.rpartition(".")[-1]
        return extension in (
            self.VECTOR_UPLOAD_FORMAT.file_extension,
            self.RASTER_UPLOAD_FORMAT.file_extension,
        )

    def _export_layer_to_temp_dir(
        self,
    ) -> typing.Tuple[typing.Optional[Path], typing.Optional[str]]:
        self._temporary_directory = Path(tempfile.mkdtemp(prefix="qgis_geonode_"))
        log(f"inside _export_layer_to_temp_dir")
        exported_path = None
        error_message = None
        if self.layer.type() == qgis.core.QgsMapLayerType.VectorLayer:
            log("is vector")
            # exported_path, error_message = self._export_vector_layer()
            exported_path, error_message = self._export_vector_layer_to_shapefile()
        elif self.layer.type() == qgis.core.QgsMapLayerType.RasterLayer:
            log("is raster")
            exported_path, export_error = self._export_raster_layer()
        else:
            log("is unknown - panic!")
            raise NotImplementedError()
        return exported_path, error_message or None

    def _export_vector_layer_to_shapefile(
        self,
    ) -> typing.Tuple[typing.Optional[Path], str]:
        sanitized_layer_name = network.sanitize_layer_name(self.layer.name())
        log("inside _export_vector_layer_to_shapefile")
        target_path = self._temporary_directory / f"{sanitized_layer_name}.shp"
        log(f"target_path: {target_path}")
        export_code, error_message = qgis.core.QgsVectorLayerExporter.exportLayer(
            layer=self.layer,
            uri=str(target_path),
            providerKey="ogr",
            destCRS=qgis.core.QgsCoordinateReferenceSystem(),
            # onlySelected=True,
            options={
                "driverName": "ESRI Shapefile",
            },
        )
        log(f"export_code: {export_code}")
        log(f"error_message: {error_message}")
        if export_code == qgis.core.Qgis.VectorExportResult.Success:
            result = (target_path, error_message)
        else:
            result = (None, error_message)
        log("leaving _export_vector_layer...")
        return result

    def _export_vector_layer(self) -> typing.Tuple[typing.Optional[Path], str]:
        sanitized_layer_name = network.sanitize_layer_name(self.layer.name())
        log("inside _export_vector_layer")
        target_path = (
            self._temporary_directory
            / f"{sanitized_layer_name}.{self.VECTOR_UPLOAD_FORMAT.file_extension}"
        )
        log(f"target_path: {target_path}")
        export_code, error_message = qgis.core.QgsVectorLayerExporter.exportLayer(
            layer=self.layer,
            uri=str(target_path),
            providerKey="ogr",
            destCRS=qgis.core.QgsCoordinateReferenceSystem(),
            onlySelected=True,
            options={
                "driverName": self.VECTOR_UPLOAD_FORMAT.driver_name,
                "layerName": sanitized_layer_name,
            },
        )
        log(f"export_code: {export_code}")
        log(f"error_message: {error_message}")
        if export_code == qgis.core.Qgis.VectorExportResult.Success:
            result = (target_path, error_message)
        else:
            result = (None, error_message)
        log("leaving _export_vector_layer...")
        return result

    def _export_raster_layer(
        self,
    ) -> typing.Tuple[typing.Optional[Path], typing.Optional[int]]:
        sanitized_layer_name = network.sanitize_layer_name(self.layer.name())
        target_path = (
            self._temporary_directory
            / f"{sanitized_layer_name}.{self.RASTER_UPLOAD_FORMAT.file_extension}"
        )
        writer = qgis.core.QgsRasterFileWriter(str(target_path))
        writer.setOutputFormat(self.RASTER_UPLOAD_FORMAT.driver_name)
        pipe = self.layer.pipe()
        raster_interface = self.layer.dataProvider()
        write_error = writer.writeRaster(
            pipe,
            raster_interface.xSize(),
            raster_interface.ySize(),
            raster_interface.extent(),
            raster_interface.crs(),
            qgis.core.QgsCoordinateTransformContext(),
        )
        if write_error == qgis.core.QgsRasterFileWriter.NoError:
            result = (target_path, None)
        else:
            result = (None, write_error)
        return result


def build_multipart(
    layer_metadata: qgis.core.QgsLayerMetadata,
    permissions: typing.Dict,
    main_file: QtCore.QFile,
    sidecar_files: typing.List[typing.Tuple[str, QtCore.QFile]],
) -> QtNetwork.QHttpMultiPart:
    encoding = "utf-8"
    multipart = QtNetwork.QHttpMultiPart(QtNetwork.QHttpMultiPart.FormDataType)
    title_part = QtNetwork.QHttpPart()
    title_part.setHeader(
        QtNetwork.QNetworkRequest.ContentDispositionHeader,
        'form-data; name="dataset_title"',
    )
    title_part.setBody(layer_metadata.title().encode(encoding))
    multipart.append(title_part)
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
        part.setHeader(
            QtNetwork.QNetworkRequest.ContentTypeHeader, "application/x-qgis"
        )
        part.setBodyDevice(file_handler)
        multipart.append(part)
    return multipart
