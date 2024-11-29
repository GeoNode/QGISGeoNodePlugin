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
from ..utils import log
from ..tasks import network_task
from ..utils import log, sanitize_layer_name
from .. import network


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


class LayerUploaderTask(network_task.NetworkRequestTask):
    VECTOR_UPLOAD_FORMAT = ExportFormat("ESRI Shapefile", "shp")
    RASTER_UPLOAD_FORMAT = ExportFormat("GTiff", "tif")

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
        """Task to perform upload of QGIS layers to remote GeoNode servers."""
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
            source_path = Path(
                self.layer.dataProvider().dataSourceUri().partition("|")[0]
            )
            export_error = None
        else:
            log(
                "Exporting layer to an uploadable format before proceeding with "
                "the upload..."
            )
            source_path, export_error = self._export_layer_to_temp_dir()
        log(f"source_path: {source_path}")
        if export_error is None:
            sld_path, sld_error = self._export_layer_style()
            log(f"sld_path: {sld_path}")
            if sld_path is None:
                log(
                    f"Could not export the layer's style as SLD "
                    f"({sld_error}), skipping..."
                )
            multipart = self._prepare_multipart(source_path, sld_path=sld_path)
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
                    self._pending_replies[request_id] = network.PendingReply(
                        0, qt_reply, False
                    )
                else:
                    self._all_requests_finished.emit()
            loop_forcibly_ended = not bool(event_loop_result.result)
            if loop_forcibly_ended:
                result = False
            else:
                result = self._num_finished >= len(self.requests_to_perform)
        else:
            result = False
        return result

    def finished(self, result: bool) -> None:
        if self._temporary_directory is not None:
            shutil.rmtree(self._temporary_directory, ignore_errors=True)
        super().finished(result)

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
        multipart = network.build_multipart(
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
