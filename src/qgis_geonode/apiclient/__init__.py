import dataclasses
import importlib
import typing

from .models import UNSUPPORTED_REMOTE


def get_geonode_client(
    connection_settings: "ConnectionSettings",
) -> typing.Optional["BaseGeonodeClient"]:
    module_path, class_name = connection_settings.api_client_class_path.rpartition(".")[
        ::2
    ]
    imported_module = importlib.import_module(module_path)
    class_type = getattr(imported_module, class_name)
    return class_type.from_connection_settings(connection_settings)


@dataclasses.dataclass
class GeonodeVersion:
    major: int
    minor: int
    patch: int
    pre_release: typing.Optional[str] = None
    build_metadata: typing.Optional[str] = None


def parse_geonode_version(raw_version: str) -> GeonodeVersion:
    """Parse GeoNode version as if it were using semantic versioning.

    Consult https://semver.org/ for more detail on semantic versioning.

    """

    pre_release_fragment, build_metadata = raw_version.partition("+")[::2]
    version_fragment, pre_release = pre_release_fragment.partition("-")[::2]
    major, minor, patch = (int(part) for part in version_fragment.split("."))
    return GeonodeVersion(
        major, minor, patch, pre_release or None, build_metadata or None
    )
