"""End-to-end cancellation test for ``LayerUploaderTask``.

Phase 7 #3: drives a real ``LayerUploaderTask`` through the QGIS task
manager, points its POST at the mock ``/httpclient/slow`` endpoint, and
cancels mid-flight. Asserts that:

* ``task_done`` fires with ``False``,
* ``task.response`` carries a ``NetworkError`` with
  ``ErrorKind.CANCELLED``.

The CPU work (layer export, multipart assembly) is stubbed via a tiny
subclass — the point of this test is the cancel propagation through the
nested ``QEventLoop`` in ``run()`` to the in-flight ``Request``, not the
shapefile-export pipeline.
"""

import pytest
import qgis.core
from qgis.PyQt import QtCore, QtNetwork

from qgis_geonode.httpclient import ErrorKind
from qgis_geonode.tasks.tasks import LayerUploaderTask


MOCK_BASE = "http://127.0.0.1:9000"


class _StubbedUploaderTask(LayerUploaderTask):
    """Skip the layer-export / multipart-build CPU work.

    The cancel test only cares about the network leg of ``run()``: dispatch
    a Request, wait inside the nested event loop, and observe that
    ``cancel()`` propagates to the in-flight reply. We override the file-
    touching helpers so the test doesn't need a real shapefile fixture.
    """

    def _is_layer_uploadable(self) -> bool:
        # Tell run() to skip _export_layer_to_temp_dir; source_path is
        # constructed from the layer URI but never read by our stubbed
        # _prepare_multipart.
        return True

    def _export_layer_style(self):
        return None, "skipped in test"

    def _prepare_multipart(self, source_path, sld_path=None):
        multipart = QtNetwork.QHttpMultiPart(QtNetwork.QHttpMultiPart.FormDataType)
        part = QtNetwork.QHttpPart()
        part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            'form-data; name="probe"',
        )
        part.setBody(b"x")
        multipart.append(part)
        return multipart


def test_layer_uploader_task_cancellation(qgis_application, mock_geonode_server, qtbot):
    # An in-memory layer is enough — the stubbed methods above never
    # actually export it. We only need a valid QgsMapLayer to satisfy the
    # constructor and the layer.dataProvider().dataSourceUri() read inside
    # run().
    layer = qgis.core.QgsVectorLayer(
        "Point?crs=EPSG:4326", "cancel-test-layer", "memory"
    )
    assert layer.isValid()

    upload_url = QtCore.QUrl(f"{MOCK_BASE}/httpclient/slow")
    task = _StubbedUploaderTask(
        layer=layer,
        upload_url=upload_url,
        allow_public_access=False,
        authcfg="",
        network_task_timeout=10000,
    )

    # /httpclient/slow sleeps 2s; firing cancel() at ~500ms lands well
    # inside the network wait, after the worker thread has reached
    # loop.exec_() but before the response arrives.
    QtCore.QTimer.singleShot(500, task.cancel)

    qgis.core.QgsApplication.taskManager().addTask(task)

    with qtbot.waitSignal(task.task_done, timeout=10000) as blocker:
        pass

    (result,) = blocker.args
    assert result is False, "task_done(result) should be False on cancel"
    assert task.response is not None, "response should be populated even on cancel"
    assert task.response.error is not None
    assert task.response.error.kind == ErrorKind.CANCELLED
