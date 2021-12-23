import typing
from functools import partial

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtXml,
)

from .. import network, conf
from ..utils import log

from . import models
from .models import GeonodeApiSearchFilters


class BaseGeonodeClient(QtCore.QObject):
    auth_config: str
    base_url: str
    network_fetcher_task: typing.Optional[network.NetworkRequestTask]
    capabilities: typing.List[models.ApiClientCapability]
    page_size: int
    network_requests_timeout: int

    dataset_list_received = QtCore.pyqtSignal(list, models.GeonodePaginationInfo)
    dataset_detail_received = QtCore.pyqtSignal(object)
    dataset_detail_error_received = QtCore.pyqtSignal([str], [str, int, str])
    style_detail_received = QtCore.pyqtSignal(QtXml.QDomElement)
    keyword_list_received = QtCore.pyqtSignal(list)
    search_error_received = QtCore.pyqtSignal([str], [str, int, str])
    dataset_uploaded = QtCore.pyqtSignal(int)
    dataset_upload_error_received = QtCore.pyqtSignal([str], [str, int, str])

    def __init__(
        self,
        base_url: str,
        page_size: int,
        network_requests_timeout: int,
        auth_config: typing.Optional[str] = None,
    ):
        super().__init__()
        self.auth_config = auth_config or ""
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.network_requests_timeout = network_requests_timeout
        self.network_fetcher_task = None

    @classmethod
    def from_connection_settings(cls, connection_settings: conf.ConnectionSettings):
        return cls(
            base_url=connection_settings.base_url,
            page_size=connection_settings.page_size,
            auth_config=connection_settings.auth_config,
            network_requests_timeout=connection_settings.network_requests_timeout,
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

    def get_dataset_upload_url(self) -> QtCore.QUrl:
        raise NotImplementedError

    def get_dataset_list(self, search_filters: GeonodeApiSearchFilters) -> None:
        self.network_fetcher_task = network.NetworkRequestTask(
            [network.RequestToPerform(url=self.get_dataset_list_url(search_filters))],
            self.auth_config,
            network_task_timeout=self.network_requests_timeout,
            description="Get dataset list",
        )
        self.network_fetcher_task.task_done.connect(self.handle_dataset_list)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_dataset_list(self, result: bool):
        """Handle the list of datasets returned by the remote

        This must emit the `dataset_list_received` signal.
        """
        raise NotImplementedError

    def get_dataset_detail(self, brief_dataset: models.BriefDataset) -> None:
        requests_to_perform = [
            network.RequestToPerform(url=self.get_dataset_detail_url(brief_dataset.pk))
        ]
        if brief_dataset.dataset_sub_type == models.GeonodeResourceType.VECTOR_LAYER:
            sld_url = QtCore.QUrl(brief_dataset.default_style.sld_url)
            requests_to_perform.append(network.RequestToPerform(url=sld_url))

        self.network_fetcher_task = network.NetworkRequestTask(
            requests_to_perform,
            self.auth_config,
            network_task_timeout=self.network_requests_timeout,
            description="Get dataset detail",
        )
        self.network_fetcher_task.task_done.connect(
            partial(self.handle_dataset_detail, brief_dataset)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_dataset_detail(self, brief_dataset: models.BriefDataset, result: bool):
        raise NotImplementedError

    def upload_layer(
        self, layer: qgis.core.QgsMapLayer, allow_public_access: bool
    ) -> None:
        log("inside apiclient upload_layer...")
        self.network_fetcher_task = network.LayerUploaderTask(
            layer,
            self.get_dataset_upload_url(),
            allow_public_access=allow_public_access,
            authcfg=self.auth_config,
            description="Upload layer to GeoNode",
            network_timeout=60,
        )
        self.network_fetcher_task.task_done.connect(self.handle_layer_upload)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)
        log("leaving apiclient upload_layer...")

    def handle_layer_upload(self, result: bool):
        """Handle layer upload outcome.

        This method should emit either `dataset_uploaded` or
        `dataset_upload_error_received`.

        """

        raise NotImplementedError
