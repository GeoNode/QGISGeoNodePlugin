import typing
import uuid
from functools import partial

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
    QtXml,
)

from ..utils import (
    log,
)
from .. import network
from . import models
from .models import GeonodeApiSearchParameters


class BaseGeonodeClient(QtCore.QObject):
    auth_config: str
    base_url: str
    network_fetcher_task: typing.Optional[network.NetworkFetcherTask]
    capabilities: typing.List[models.ApiClientCapability]
    page_size: int

    # TODO: remove this signal
    layer_list_received = QtCore.pyqtSignal(list, models.GeonodePaginationInfo)

    dataset_list_received = QtCore.pyqtSignal(list, models.GeonodePaginationInfo)

    # TODO: remove this signal
    layer_detail_received = QtCore.pyqtSignal(models.GeonodeResource)

    dataset_detail_received = QtCore.pyqtSignal(object)

    style_detail_received = QtCore.pyqtSignal(QtXml.QDomElement)
    layer_styles_received = QtCore.pyqtSignal(list)
    map_list_received = QtCore.pyqtSignal(list, models.GeonodePaginationInfo)
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

    def get_ordering_filter_name(
        self,
        ordering_type: models.OrderingType,
        reverse_sort: typing.Optional[bool] = False,
    ) -> str:
        raise NotImplementedError

    def get_search_result_identifier(
        self, resource: models.BriefGeonodeResource
    ) -> str:
        raise NotImplementedError

    def get_layers_url_endpoint(
        self, search_params: GeonodeApiSearchParameters
    ) -> QtCore.QUrl:
        raise NotImplementedError

    def get_layers_request_payload(
        self, search_params: GeonodeApiSearchParameters
    ) -> typing.Optional[str]:
        return None

    def get_maps_request_payload(
        self, search_params: GeonodeApiSearchParameters
    ) -> typing.Optional[str]:
        return None

    def get_layer_detail_url_endpoint(
        self, id_: typing.Union[int, uuid.UUID]
    ) -> QtCore.QUrl:
        raise NotImplementedError

    def get_layer_styles_url_endpoint(self, layer_id: int):
        raise NotImplementedError

    def get_maps_url_endpoint(
        self, search_params: GeonodeApiSearchParameters
    ) -> QtCore.QUrl:
        raise NotImplementedError

    def get_keywords_url_endpoint(self) -> QtCore.QUrl:
        url = QtCore.QUrl(f"{self.base_url}/h_keywords_api")
        return url

    def deserialize_response_contents(self, contents: QtCore.QByteArray) -> typing.Any:
        raise NotImplementedError

    def deserialize_sld_style(self, raw_sld: QtCore.QByteArray) -> QtXml.QDomDocument:
        sld_doc = QtXml.QDomDocument()
        # in the line below, `True` means use XML namespaces and it is crucial for
        # QGIS to be able to load the SLD
        sld_loaded = sld_doc.setContent(raw_sld, True)
        if not sld_loaded:
            raise RuntimeError("Could not load downloaded SLD document")
        return sld_doc

    # TODO: remove this in favor of handle_dataset_list
    def handle_layer_list(self, original_search_params: GeonodeApiSearchParameters):
        raise NotImplementedError

    # TODO: remove this in favor of handle_dataset_detail
    def handle_layer_detail(self):
        raise NotImplementedError

    def handle_layer_style_detail(self):
        deserialized = self.deserialize_sld_style(
            self.network_fetcher_task.reply_content
        )
        sld_root = deserialized.documentElement()
        error_message = "Could not parse downloaded SLD document"
        if sld_root.isNull():
            raise RuntimeError(error_message)
        sld_named_layer = sld_root.firstChildElement("NamedLayer")
        if sld_named_layer.isNull():
            raise RuntimeError(error_message)
        self.style_detail_received.emit(sld_named_layer)

    def handle_layer_style_list(self):
        raise NotImplementedError

    def handle_map_list(self, original_search_params: GeonodeApiSearchParameters):
        raise NotImplementedError

    def handle_keyword_list(self):
        if self.network_fetcher_task.reply_content is not None:
            deserialized = self.deserialize_response_contents(
                self.network_fetcher_task.reply_content
            )
            keywords = []
            for item in deserialized:
                keywords.append(item["text"])
            self.keyword_list_received.emit(keywords)
        else:
            log(f"Couldn't find any keywords in {self.base_url}")
            self.error_received[str].emit(
                f"Couldn't find any keywords in {self.base_url}"
            )

    def get_dataset_list(self, search_params: GeonodeApiSearchParameters):
        self.network_fetcher_task = network.MultipleNetworkFetcherTask(
            [network.RequestToPerform(url=self.get_dataset_list_url(search_params))],
            self.auth_config,
        )
        self.network_fetcher_task.all_finished.connect(self.handle_dataset_list)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    # TODO: Delete this in favor of get_dataset_list
    def get_layers(
        self, search_params: typing.Optional[GeonodeApiSearchParameters] = None
    ):
        """Initiate a search for remote GeoNode datasets"""
        params = (
            search_params if search_params is not None else GeonodeApiSearchParameters()
        )
        self.network_fetcher_task = network.NetworkFetcherTask(
            self,
            QtNetwork.QNetworkRequest(self.get_layers_url_endpoint(params)),
            request_payload=self.get_layers_request_payload(params),
            authcfg=self.auth_config,
        )
        self.network_fetcher_task.request_finished.connect(
            partial(self.handle_layer_list, params)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    # TODO: delete this in favor of get_dataset_detail
    def get_layer_detail_from_brief_resource(
        self, brief_resource: models.BriefGeonodeResource
    ):
        raise NotImplementedError

    # TODO: delete this in favor of get_dataset_detail
    def get_layer_detail(self, id_: typing.Union[int, uuid.UUID]):
        self.network_fetcher_task = network.NetworkFetcherTask(
            self,
            QtNetwork.QNetworkRequest(self.get_layer_detail_url_endpoint(id_)),
            authcfg=self.auth_config,
        )
        self.network_fetcher_task.request_finished.connect(self.handle_layer_detail)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

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
        self, layer: models.GeonodeResource, style_name: typing.Optional[str] = None
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

    def get_maps(self, search_params: GeonodeApiSearchParameters):
        url = self.get_maps_url_endpoint(search_params)
        request_payload = self.get_maps_request_payload(search_params)
        log(f"URL: {url.toString()}")
        self.network_fetcher_task = network.NetworkFetcherTask(
            self,
            QtNetwork.QNetworkRequest(url),
            request_payload=request_payload,
            authcfg=self.auth_config,
        )
        self.network_fetcher_task.request_finished.connect(
            partial(self.handle_map_list, search_params)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def get_keywords(self):
        url = self.get_keywords_url_endpoint()
        self.network_fetcher_task = network.NetworkFetcherTask(
            self,
            QtNetwork.QNetworkRequest(url),
            authcfg=self.auth_config,
        )
        self.network_fetcher_task.request_finished.connect(self.handle_keyword_list)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)
