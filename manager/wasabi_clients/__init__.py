from .wasabi_client_v1 import WasabiClientV1
from .wasabi_client_v2 import WasabiClientV2
from .wasabi_client_v204 import WasabiClientV204
from .wasabi_client_v26 import WasabiClientV26
from .wasabi_client_base import WasabiClientBase


def WasabiClient(version: str) -> type[WasabiClientBase]:
    if version < "2.0.0":
        return WasabiClientV1
    if version >= "2.0.0" and version < "2.0.4":
        return WasabiClientV2
    if version >= "2.0.4" and version < "2.6.0":
        return WasabiClientV204
    return WasabiClientV26
