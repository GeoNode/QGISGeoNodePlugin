import json
import typing
import urllib.parse
import shutil
import tempfile
from pathlib import Path
import dataclasses

from qgis.PyQt import (
    QtCore,
    QtWidgets,
    QtGui,
    QtNetwork,
)

from ..apiclient import (
    base,
    models,
)
import qgis.core
from ..httpclient import (
    ErrorKind,
    HttpMethod,
    NetworkError,
    NetworkResponse,
    Request,
    RequestToPerform,
)
from ..utils import log, sanitize_layer_name
from . import upload


@dataclasses.dataclass()
class ExportFormat:
    driver_name: str
    file_extension: str


class ThumbnailLoaderTask(qgis.core.QgsTask):
    def __init__(
        self,
        raw_thumbnail: QtCore.QByteArray,
        label: QtWidgets.QLabel,
        resource_title: str,
    ):
        """Load thumbnail data

        This task reads the thumbnail gotten over the network into a QImage object in a
        separate thread and then loads it up onto the main GUI in its `finished()`
        method - `finished` runs in the main thread. This is done because this plugin's
        GUI wants to load multiple thumbnails concurrently. If we were to read the raw
        thumbnail bytes into a pixmap in the main thread it would not be possible to
        load them in parallel because QPixmap does blocking IO.

        """

        super().__init__()
        self.raw_thumbnail = raw_thumbnail
        self.label = label
        self.resource_title = resource_title
        self.thumbnail_image = None
        self.exception = None

    def run(self):
        self.thumbnail_image = QtGui.QImage.fromData(self.raw_thumbnail)
        return True

    def finished(self, result: bool):
        if result:
            thumbnail = QtGui.QPixmap.fromImage(self.thumbnail_image)
            self.label.setPixmap(thumbnail)
        else:
            log(f"Error retrieving thumbnail for {self.resource_title!r}")


class LayerLoaderTask(qgis.core.QgsTask):
    brief_dataset: models.BriefDataset
    brief_resource: models.BriefDataset
    service_type: models.GeonodeService
    api_client: base.BaseGeonodeClient
    layer: typing.Optional["QgsMapLayer"]
    _exception: typing.Optional[str]

    def __init__(
        self,
        brief_dataset: models.BriefDataset,
        service_type: models.GeonodeService,
        api_client: base.BaseGeonodeClient,
    ):
        """Load a QGIS layer

        This is done in a QgsTask in order to allow the loading of a layer from the
        network to be done in a background thread and not block the main QGIS UI.

        """

        super().__init__()
        self.brief_dataset = brief_dataset
        self.service_type = service_type
        self.api_client = api_client
        self.layer = None
        self._exception = None

    def run(self):
        if self.service_type == models.GeonodeService.OGC_WMS:
            layer = self._load_wms()
        elif self.service_type == models.GeonodeService.OGC_WFS:
            layer = self._load_wfs()
        elif self.service_type == models.GeonodeService.OGC_WCS:
            layer = self._load_wcs()
        else:
            layer = None
            self._exception = f"Unrecognized layer type: {self.service_type!r}"

        result = False
        if layer is not None and layer.isValid():
            self.layer = layer
            result = True
        else:
            layer_error_message_list = layer.error().messageList()
            layer_error = ", ".join(err.message() for err in layer_error_message_list)
            self._exception = layer_error
            log(f"layer errors: {layer_error}")
            provider_error_message_list = layer.dataProvider().error().messageList()
            log(
                f"provider errors: "
                f"{', '.join([err.message() for err in provider_error_message_list])}"
            )
        return result

    def finished(self, result: bool):
        if result:
            # Cloning the layer seems to be required in order to make sure the WMS
            # layers work appropriately - Otherwise we get random crashes when loading
            # WMS layers. This may be related to how the layer is moved from the
            # secondary thread by QgsTaskManager and the layer's ownership.
            self.layer = self.layer.clone()
        else:
            message = (
                f"Error loading layer {self.brief_dataset.title!r} from "
                f"{self.brief_dataset.service_urls[self.service_type]!r}: "
                f"{self._exception}"
            )
            log(message)

    def _load_wms(self) -> qgis.core.QgsMapLayer:
        params = {
            "crs": f"EPSG:{self.brief_dataset.srid.postgisSrid()}",
            "url": self.brief_dataset.service_urls[self.service_type],
            "format": "image/png",
            "layers": self.brief_dataset.name,
            "styles": "",
            "version": "auto",
        }
        if self.api_client.auth_config:
            params["authcfg"] = self.api_client.auth_config
        return qgis.core.QgsRasterLayer(
            urllib.parse.unquote(urllib.parse.urlencode(params)),
            self.brief_dataset.title,
            "wms",
        )

    def _load_wcs(self) -> qgis.core.QgsMapLayer:
        params = {
            "url": self.brief_dataset.service_urls[self.service_type],
            "identifier": self.brief_dataset.name,
            "crs": f"EPSG:{self.brief_dataset.srid.postgisSrid()}",
        }
        if self.api_client.auth_config:
            params["authcfg"] = self.api_client.auth_config
        return qgis.core.QgsRasterLayer(
            urllib.parse.unquote(urllib.parse.urlencode(params)),
            self.brief_dataset.title,
            "wcs",
        )

    def _load_wfs(self) -> qgis.core.QgsMapLayer:
        params = {
            "srsname": f"EPSG:{self.brief_dataset.srid.postgisSrid()}",
            "typename": self.brief_dataset.name,
            "url": self.brief_dataset.service_urls[self.service_type].rstrip("/"),
            "version": self.api_client.wfs_version.value,
        }
        if self.api_client.auth_config:
            params["authcfg"] = self.api_client.auth_config
        uri = " ".join(f"{key}='{value}'" for key, value in params.items())
        return qgis.core.QgsVectorLayer(uri, self.brief_dataset.title, "WFS")


class LayerUploaderTask(qgis.core.QgsTask):
    VECTOR_UPLOAD_FORMAT = ExportFormat("ESRI Shapefile", "shp")
    RASTER_UPLOAD_FORMAT = ExportFormat("GTiff", "tif")

    _POLL_INTERVAL_MS = 3000
    _POLL_OVERALL_TIMEOUT_MS = 60 * 60 * 1000

    layer: qgis.core.QgsMapLayer
    allow_public_access: bool
    authcfg: str
    network_task_timeout: int
    response: typing.Optional[NetworkResponse]
    upload_response: typing.Optional[NetworkResponse]
    _upload_url: QtCore.QUrl
    _execution_request_url_template: typing.Optional[str]
    _temporary_directory: typing.Optional[Path]
    _request: typing.Optional[Request]
    _poll_wait_loop: typing.Optional[QtCore.QEventLoop]

    task_done = QtCore.pyqtSignal(bool)
    # Fired once the multipart POST has been accepted by the server (HTTP
    # 2xx + execution_id parsed) and the task is about to enter the polling
    # phase. The GUI uses this to switch the status message from
    # "uploading" to "processing on the server".
    upload_received = QtCore.pyqtSignal()

    def __init__(
        self,
        layer: qgis.core.QgsMapLayer,
        upload_url: QtCore.QUrl,
        allow_public_access: bool,
        authcfg: str,
        network_task_timeout: int,
        description: str = "LayerUploaderTask",
        execution_request_url_template: typing.Optional[str] = None,
    ):
        """Task to perform upload of QGIS layers to remote GeoNode servers.

        Subclasses :class:`qgis.core.QgsTask` directly: ``run()`` does the
        layer export + multipart assembly on the worker thread, then drives a
        single ``Request`` POST through a nested ``QEventLoop`` (legitimate
        here — the surrounding QgsTask is genuinely a worker thread doing
        non-network work first; this is the case ``wait_for_signal`` was
        ostensibly written for).

        ``execution_request_url_template`` must contain an ``{execution_id}``
        placeholder. When provided, the task does not consider the upload done
        once the POST returns 201 — that response only carries the
        ``execution_id`` for the async ingestion job. The task then polls
        ``GET /executionrequest/{id}`` until the server reports status
        ``finished`` (success) or ``failed`` (error). When the template is
        ``None`` the POST result is the final answer (used by tests).
        """
        super().__init__(description)
        self.layer = layer
        self.allow_public_access = allow_public_access
        self.authcfg = authcfg
        self.network_task_timeout = network_task_timeout
        self._upload_url = upload_url
        self._execution_request_url_template = execution_request_url_template
        self._temporary_directory = None
        self._request = None
        self._poll_wait_loop = None
        self.response = None
        self.upload_response = None

    def run(self) -> bool:
        if self._is_layer_uploadable():
            source_path = Path(
                self.layer.dataProvider().dataSourceUri().partition("|")[0]
            )
        else:
            log(
                "Exporting layer to an uploadable format before proceeding with "
                "the upload..."
            )
            source_path, export_error = self._export_layer_to_temp_dir()
            if source_path is None:
                log(f"Could not export layer for upload: {export_error}")
                return False
        log(f"source_path: {source_path}")
        if self.isCanceled():
            return False

        sld_path, sld_error = self._export_layer_style()
        log(f"sld_path: {sld_path}")
        if sld_path is None:
            log(
                f"Could not export the layer's style as SLD "
                f"({sld_error}), skipping..."
            )
        if self.isCanceled():
            return False

        multipart = self._prepare_multipart(source_path, sld_path=sld_path)
        boundary = multipart.boundary().data().decode()

        self._dispatch_request_blocking(
            RequestToPerform(
                url=self._upload_url,
                method=HttpMethod.POST,
                payload=multipart,
                content_type=f"multipart/form-data; boundary={boundary}",
            )
        )

        self.upload_response = self.response
        if self.isCanceled():
            return False
        if self.response is None or not self.response.ok:
            return False

        if self._execution_request_url_template is None:
            return True

        execution_id = self._parse_execution_id(self.response.body)
        if not execution_id:
            self.response = self._synthesise_error_response(
                self._upload_url,
                "Upload accepted but server did not return an execution_id",
                body=self.response.body,
            )
            return False

        self.upload_received.emit()
        self.response = self._poll_execution_status(execution_id)
        return self.response is not None and self.response.ok

    def _on_request_finished(self, response: NetworkResponse) -> None:
        self.response = response

    def cancel(self) -> None:
        super().cancel()
        if self._request is not None:
            self._request.cancel()
        if self._poll_wait_loop is not None:
            self._poll_wait_loop.quit()

    def _dispatch_request_blocking(self, request: RequestToPerform) -> None:
        """Send ``request`` and block until it completes.

        Uses the same nested ``QEventLoop`` pattern as the original POST —
        the worker thread is genuinely waiting for I/O here. The result
        lands in ``self.response`` via ``_on_request_finished``.

        The ``_on_request_finished`` slot is connected with
        ``Qt.DirectConnection``: this task QObject lives on the main thread
        but ``run()`` executes on a worker thread, so the default
        ``AutoConnection`` would queue the slot on the main thread's event
        loop — which the nested ``QEventLoop`` here does not process. The
        loop would then exit on ``loop.quit`` (a same-thread direct call)
        with ``self.response`` still ``None``. ``DirectConnection`` makes
        the assignment happen synchronously in the worker thread; it's a
        plain Python attribute set, so the GIL is enough for safety.
        """
        loop = QtCore.QEventLoop()
        self._request = Request()
        self._request.finished.connect(
            self._on_request_finished, type=QtCore.Qt.DirectConnection
        )
        self._request.finished.connect(loop.quit)
        self._request.send(
            request,
            authcfg=self.authcfg or None,
            timeout_ms=self.network_task_timeout,
        )
        loop.exec()

    def _poll_execution_status(self, execution_id: str) -> NetworkResponse:
        """Poll the executionrequest endpoint until the import terminates.

        Returns the last poll response. On a logical failure (HTTP 200 but
        ``status == "failed"``) the response carries a synthesised
        ``NetworkError`` so callers can rely on ``response.ok`` alone.
        """
        poll_url = QtCore.QUrl(
            self._execution_request_url_template.format(execution_id=execution_id)
        )
        deadline_ms = self._POLL_OVERALL_TIMEOUT_MS
        elapsed_ms = 0
        last_response: typing.Optional[NetworkResponse] = None

        while not self.isCanceled() and elapsed_ms < deadline_ms:
            self._dispatch_request_blocking(
                RequestToPerform(url=poll_url, method=HttpMethod.GET)
            )
            last_response = self.response
            if self.isCanceled():
                return last_response or self._synthesise_error_response(
                    poll_url, "Upload tracking cancelled"
                )
            if last_response is None or not last_response.ok:
                return last_response or self._synthesise_error_response(
                    poll_url, "Upload tracking failed: empty response"
                )

            status = self._parse_execution_status(last_response.body)
            if status == "finished":
                return last_response
            if status == "failed":
                return dataclasses.replace(
                    last_response,
                    error=NetworkError(
                        kind=ErrorKind.HTTP,
                        url=poll_url.toString(),
                        message=self._failure_message(last_response.body),
                        body=last_response.body,
                    ),
                )

            self._sleep_between_polls()
            elapsed_ms += self._POLL_INTERVAL_MS

        if self.isCanceled():
            return last_response or self._synthesise_error_response(
                poll_url, "Upload tracking cancelled"
            )
        return self._synthesise_error_response(
            poll_url,
            f"Upload tracking timed out after {deadline_ms // 1000}s",
            body=last_response.body if last_response is not None else None,
        )

    def _sleep_between_polls(self) -> None:
        """Block the worker thread for ``_POLL_INTERVAL_MS``, cancellable.

        ``cancel()`` calls ``quit()`` on this loop to interrupt the wait
        immediately rather than waiting out the full interval.
        """
        self._poll_wait_loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(self._POLL_INTERVAL_MS, self._poll_wait_loop.quit)
        self._poll_wait_loop.exec()
        self._poll_wait_loop = None

    @staticmethod
    def _parse_execution_id(body: typing.Optional[bytes]) -> typing.Optional[str]:
        if not body:
            return None
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return None
        if isinstance(data, dict):
            value = data.get("execution_id")
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _parse_execution_status(body: typing.Optional[bytes]) -> typing.Optional[str]:
        # DynamicREST wraps detail responses under the serializer's ``name``
        # ("request" for ExecutionRequestSerializer); fall back to a flat
        # shape so older / non-wrapped responses still parse.
        if not body:
            return None
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        wrapped = data.get("request")
        record = wrapped if isinstance(wrapped, dict) else data
        status = record.get("status")
        return status if isinstance(status, str) else None

    @staticmethod
    def _failure_message(body: typing.Optional[bytes]) -> str:
        default = "Upload failed on the GeoNode server"
        if not body:
            return default
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return default
        if not isinstance(data, dict):
            return default
        record = data.get("request") if isinstance(data.get("request"), dict) else data
        log_text = record.get("log") if isinstance(record.get("log"), str) else None
        if log_text:
            return f"{default}: {log_text}"
        return default

    @staticmethod
    def _synthesise_error_response(
        url: typing.Union[QtCore.QUrl, str],
        message: str,
        body: typing.Optional[bytes] = None,
    ) -> NetworkResponse:
        url_str = url.toString() if isinstance(url, QtCore.QUrl) else url
        request = RequestToPerform(
            url=url if isinstance(url, QtCore.QUrl) else QtCore.QUrl(url),
            method=HttpMethod.GET,
        )
        return NetworkResponse(
            request=request,
            body=body or b"",
            error=NetworkError(
                kind=ErrorKind.TRANSPORT,
                url=url_str,
                message=message,
                body=body,
            ),
        )

    def finished(self, result: bool) -> None:
        if self._temporary_directory is not None:
            shutil.rmtree(self._temporary_directory, ignore_errors=True)
        self.task_done.emit(result)

    def _prepare_multipart(
        self, source_path: Path, sld_path: typing.Optional[Path] = None
    ) -> QtNetwork.QHttpMultiPart:
        main_file = QtCore.QFile(str(source_path))
        main_file.open(QtCore.QIODevice.ReadOnly)
        sidecar_files = []
        if sld_path is not None:
            sld_file = QtCore.QFile(str(sld_path))
            sld_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("sld_file", sld_file))
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
        elif self.layer.type() == qgis.core.QgsMapLayerType.RasterLayer:
            # when uploading tif files GeoNode seems to want the same file be uploaded
            # twice - one under the `base_file` form field and another under the
            # `tif_file` form field. This seems like a bug in GeoNode though
            tif_file = QtCore.QFile(str(source_path))
            tif_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("tif_file", tif_file))
        permissions = {
            "users": {},
            "groups": {},
        }
        if self.allow_public_access:
            permissions["users"]["AnonymousUser"] = [
                "view_resourcebase",
                "download_resourcebase",
            ]
        multipart = upload.build_multipart(
            self.layer.metadata(), permissions, main_file, sidecar_files=sidecar_files
        )
        # below we set all QFiles as children of the multipart object and later we
        # also make the multipart object a children on the network reply object. This is
        # done in order to ensure deletion of resources at the correct time, as
        # recommended by the Qt documentation at:
        # https://doc.qt.io/qt-5/qhttppart.html#details
        main_file.setParent(multipart)
        for _, qt_file in sidecar_files:
            qt_file.setParent(multipart)
        return multipart

    def _is_layer_uploadable(self) -> bool:
        """Check if the layer is in a format suitable for uploading to GeoNode."""
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
        if self._temporary_directory is None:
            self._temporary_directory = Path(tempfile.mkdtemp(prefix="qgis_geonode_"))
        if self.layer.type() == qgis.core.QgsMapLayerType.VectorLayer:
            exported_path, error_message = self._export_vector_layer()
        elif self.layer.type() == qgis.core.QgsMapLayerType.RasterLayer:
            exported_path, export_error = self._export_raster_layer()
            error_message = str(export_error)
        else:
            raise NotImplementedError()
        return exported_path, (error_message or None)

    def _export_vector_layer(
        self,
    ) -> typing.Tuple[typing.Optional[Path], str]:
        sanitized_layer_name = sanitize_layer_name(self.layer.name())
        target_path = self._temporary_directory / f"{sanitized_layer_name}.shp"
        export_code, error_message = qgis.core.QgsVectorLayerExporter.exportLayer(
            layer=self.layer,
            uri=str(target_path),
            providerKey="ogr",
            destCRS=qgis.core.QgsCoordinateReferenceSystem(),
            options={
                "driverName": "ESRI Shapefile",
            },
        )
        if export_code == qgis.core.Qgis.VectorExportResult.Success:
            result = (target_path, error_message)
        else:
            result = (None, error_message)
        return result

    def _export_raster_layer(
        self,
    ) -> typing.Tuple[typing.Optional[Path], typing.Optional[int]]:
        sanitized_layer_name = sanitize_layer_name(self.layer.name())
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

    def _export_layer_style(self) -> typing.Tuple[typing.Optional[Path], str]:
        sanitized_layer_name = sanitize_layer_name(self.layer.name())
        if self._temporary_directory is None:
            self._temporary_directory = Path(tempfile.mkdtemp(prefix="qgis_geonode_"))
        target_path = self._temporary_directory / f"{sanitized_layer_name}.sld"
        saved_sld_details, sld_exported_flag = self.layer.saveSldStyle(str(target_path))
        if "created default style" in saved_sld_details.lower():
            result = (target_path, "")
        else:
            result = (None, saved_sld_details)
        return result
