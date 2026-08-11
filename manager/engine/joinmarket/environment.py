"""Environment shared by JoinMarket wallet-daemon containers."""

from manager.engine.base.protocols import EngineArgs


def joinmarket_container_env(args: EngineArgs, rpc_wallet_file: str) -> dict[str, str]:
    return {
        "JM_RPC_WALLET_FILE": rpc_wallet_file,
        "JM_DESCRIPTOR_REGTEST_FALLBACK": (
            "1" if args.joinmarket_descriptor_regtest_fallback else "0"
        ),
    }
