import typing
from functools import partial

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtXml,
)

from .. import (
    conf,
    network,
)

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
    style_detail_error_received = QtCore.pyqtSignal([str], [str, int, str])
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
            self.network_requests_timeout,
            self.auth_config,
            description="Get dataset list",
        )
        self.network_fetcher_task.task_done.connect(self.handle_dataset_list)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_dataset_list(self, result: bool):
        """Handle the list of datasets returned by the remote

        This must emit the `dataset_list_received` signal.
        """
        raise NotImplementedError

    def get_dataset_style(
        self, dataset: models.Dataset, emit_dataset_detail_received: bool = False
    ) -> None:
        self.network_fetcher_task = network.NetworkRequestTask(
            [network.RequestToPerform(QtCore.QUrl(dataset.default_style.sld_url))],
            self.network_requests_timeout,
            self.auth_config,
            description="Get dataset style",
        )
        self.network_fetcher_task.task_done.connect(
            partial(
                self.handle_dataset_style,
                dataset,
                emit_dataset_detail_received=emit_dataset_detail_received,
            )
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_dataset_style(
        self,
        dataset: models.Dataset,
        task_result: bool,
        emit_dataset_detail_received: typing.Optional[bool] = False,
    ) -> None:
        raise NotImplementedError

    def get_dataset_detail(
        self, brief_dataset: models.BriefDataset, get_style_too: bool = False
    ) -> None:
        requests_to_perform = [
            network.RequestToPerform(url=self.get_dataset_detail_url(brief_dataset.pk))
        ]
        if get_style_too:
            is_vector = (
                brief_dataset.dataset_sub_type
                == models.GeonodeResourceType.VECTOR_LAYER
            )
            should_load_vector_style = (
                models.ApiClientCapability.LOAD_VECTOR_LAYER_STYLE in self.capabilities
            )
            if is_vector and should_load_vector_style:
                sld_url = QtCore.QUrl(brief_dataset.default_style.sld_url)
                requests_to_perform.append(network.RequestToPerform(url=sld_url))

        self.network_fetcher_task = network.NetworkRequestTask(
            requests_to_perform,
            self.network_requests_timeout,
            self.auth_config,
            description="Get dataset detail",
        )
        self.network_fetcher_task.task_done.connect(
            partial(self.handle_dataset_detail, brief_dataset)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_dataset_detail(self, brief_dataset: models.BriefDataset, result: bool):
        """Handle dataset detail retrieval outcome.

        This method should emit either `dataset_detail_received` or
        `dataset_detail_error_received`.

        """

        raise NotImplementedError

    def get_dataset_detail_from_id(self, dataset_id: int):
        self.network_fetcher_task = network.NetworkRequestTask(
            [network.RequestToPerform(url=self.get_dataset_detail_url(dataset_id))],
            self.network_requests_timeout,
            self.auth_config,
            description="Get dataset detail",
        )
        self.network_fetcher_task.task_done.connect(self.handle_dataset_detail_from_id)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_dataset_detail_from_id(self, task_result: bool):
        raise NotImplementedError

    def get_uploader_task(
        self, layer: qgis.core.QgsMapLayer, allow_public_access: bool, timeout: int
    ) -> qgis.core.QgsTask:
        raise NotImplementedError

    def upload_layer(
        self, layer: qgis.core.QgsMapLayer, allow_public_access: bool
    ) -> None:
        self.network_fetcher_task = self.get_uploader_task(
            layer, allow_public_access, timeout=10 * 60 * 1000
        )  # the GeoNode GUI also uses a 10 minute timeout for uploads
        self.network_fetcher_task.task_done.connect(self.handle_layer_upload)
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def handle_layer_upload(self, result: bool):
        """Handle layer upload outcome.

        This method should emit either `dataset_uploaded` or
        `dataset_upload_error_received`.

        """

        raise NotImplementedError
