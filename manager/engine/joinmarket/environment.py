from ..engine_base import EngineArgs


def joinmarket_container_env(args: EngineArgs, rpc_wallet_file: str) -> dict[str, str | None]:
    fallback = getattr(args, "joinmarket_descriptor_regtest_fallback", False)
    return {
        "JM_RPC_WALLET_FILE": rpc_wallet_file,
        "JM_DESCRIPTOR_REGTEST_FALLBACK": "1" if fallback else "0",
    }
