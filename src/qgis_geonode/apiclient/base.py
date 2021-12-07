import typing
from functools import partial

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
    QtXml,
)

from .. import network
from . import models
from .models import GeonodeApiSearchFilters


class BaseGeonodeClient(QtCore.QObject):
    auth_config: str
    base_url: str
    network_fetcher_task: typing.Optional[network.MultipleNetworkFetcherTask]
    capabilities: typing.List[models.ApiClientCapability]
    page_size: int

    dataset_list_received = QtCore.pyqtSignal(list, models.GeonodePaginationInfo)
    dataset_detail_received = QtCore.pyqtSignal(object)
    style_detail_received = QtCore.pyqtSignal(QtXml.QDomElement)
    keyword_list_received = QtCore.pyqtSignal(list)
    error_received = QtCore.pyqtSignal([str], [str, int, str])

    def __init__(
        self,
        base_url: str,
        page_size: int,
        auth_config: typing.Optional[str] = None,
    ):
        super().__init__()
        self.auth_config = auth_config or ""
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.network_fetcher_task = None

    @classmethod
    def from_connection_settings(cls, connection_settings: "ConnectionSettings"):
        return cls(
            base_url=connection_settings.base_url,
            page_size=connection_settings.page_size,
            auth_config=connection_settings.auth_config,
        )

    def get_ordering_fields(self) -> typing.List[typing.Tuple[str, str]]:
        raise NotImplementedError

    def get_layer_styles_url_endpoint(self, layer_id: int):
        raise NotImplementedError

    def get_dataset_list_url(
        self, search_filters: models.GeonodeApiSearchFilters
    ) -> QtCore.QUrl:
        raise NotImplementedError

    def get_dataset_detail_url(self, dataset_id: int) -> QtCore.QUrl:
        raise NotImplementedError

    def get_dataset_list(self, search_filters: GeonodeApiSearchFilters):
        self.network_fetcher_task = network.MultipleNetworkFetcherTask(
            [network.RequestToPerform(url=self.get_dataset_list_url(search_filters))],
            self.auth_config,
        )
        self.network_fetcher_task.all_finished.connect(self.handle_dataset_list)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_dataset_list(self, result: bool):
        """Handle the list of datasets returned by the remote

        This must emit the `dataset_list_received` signal.
        """
        raise NotImplementedError

    def get_dataset_detail(self, brief_dataset: models.BriefDataset):
        requests_to_perform = [
            network.RequestToPerform(url=self.get_dataset_detail_url(brief_dataset.pk))
        ]
        if brief_dataset.dataset_sub_type == models.GeonodeResourceType.VECTOR_LAYER:
            sld_url = QtCore.QUrl(brief_dataset.default_style.sld_url)
            requests_to_perform.append(network.RequestToPerform(url=sld_url))

        self.network_fetcher_task = network.MultipleNetworkFetcherTask(
            requests_to_perform, self.auth_config
        )
        self.network_fetcher_task.all_finished.connect(
            partial(self.handle_dataset_detail, brief_dataset)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_dataset_detail(self, brief_dataset: models.BriefDataset, result: bool):
        raise NotImplementedError

    def get_layer_styles(self, layer_id: int):
        request = QtNetwork.QNetworkRequest(
            self.get_layer_styles_url_endpoint(layer_id)
        )
        self.network_fetcher_task = network.NetworkFetcherTask(
            self, request, authcfg=self.auth_config
        )
        self.network_fetcher_task.request_finished.connect(self.handle_layer_style_list)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def get_layer_style(
        self, layer: models.Dataset, style_name: typing.Optional[str] = None
    ):
        if style_name is None:
            style_url = layer.default_style.sld_url
        else:
            style_details = [i for i in layer.styles if i.name == style_name][0]
            style_url = style_details.sld_url
        self.network_fetcher_task = network.NetworkFetcherTask(
            self,
            QtNetwork.QNetworkRequest(QtCore.QUrl(style_url)),
            authcfg=self.auth_config,
        )
        self.network_fetcher_task.request_finished.connect(
            self.handle_layer_style_detail
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def deserialize_sld_style(self, raw_sld: QtCore.QByteArray) -> QtXml.QDomDocument:
        sld_doc = QtXml.QDomDocument()
        # in the line below, `True` means use XML namespaces and it is crucial for
        # QGIS to be able to load the SLD
        sld_loaded = sld_doc.setContent(raw_sld, True)
        if not sld_loaded:
            raise RuntimeError("Could not load downloaded SLD document")
        return sld_doc
