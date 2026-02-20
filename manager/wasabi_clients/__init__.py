from manager.wasabi_clients.wasabi_client_v1 import WasabiClientV1
from manager.wasabi_clients.wasabi_client_v2 import WasabiClientV2
from manager.wasabi_clients.wasabi_client_v204 import WasabiClientV204
from manager.wasabi_clients.wasabi_client_v26 import WasabiClientV26


def WasabiClient(version):
    if version < "2.0.0":
        return WasabiClientV1
    elif version >= "2.0.0" and version < "2.0.4":
        return WasabiClientV2
    elif version >= "2.0.4" and version < "2.6.0":
        return WasabiClientV204
    else:
        return WasabiClientV26
