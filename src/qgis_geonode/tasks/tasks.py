import typing
import urllib.parse

from qgis.PyQt import (
    QtCore,
    QtWidgets,
    QtGui,
)

from ..apiclient import (
    base,
    models,
)
import qgis.core
from ..utils import log


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
