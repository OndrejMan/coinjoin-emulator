import asyncio
import sys
from time import sleep, time

from manager.driver import Driver
from manager.engine.base.protocols import EngineArgs
from manager.engine.configuration import JoinMarketConfig, JoinMarketRole, ScenarioConfig, WalletConfig
from manager.engine.engine_base import EngineBase
from manager.engine.joinmarket.events import JoinMarketRoundEventsMixin
from manager.engine.joinmarket.funding import JoinMarketFundingMixin
from manager.engine.joinmarket.lifecycle import JoinMarketLifecycleMixin
from manager.engine.joinmarket.logs import JoinMarketLogsMixin
from manager.engine.joinmarket.rounds import JoinMarketRoundsMixin
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


class JoinmarketEngine(
    JoinMarketLogsMixin,
    JoinMarketFundingMixin,
    JoinMarketRoundsMixin,
    JoinMarketLifecycleMixin,
    JoinMarketRoundEventsMixin,
    EngineBase,
):

    def __init__(self, args: EngineArgs, driver: Driver) -> None:
        super().__init__(args, driver,
                         log_src_path="/home/joinmarket/.joinmarket/logs")
        self.obwatch_client: OrderbookWatchClient | None = None
        # Feature flag to enable async client updates (default: enabled for better performance)
        self.async_updates = bool(getattr(args, "async_updates", True))
        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_resource_check = 0  # Track when we last checked resources

    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig(
            name="default",
            default_version="joinmarket",
            rounds=0,  # the number of coinjoins after which the simulation stops (0 for no limit)
            blocks=0,  # the number of mined blocks after which the simulation stops (0 for no limit)
            wallets=[
                WalletConfig(
                    funds=[75000, 75000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.TAKER,
                        tumbler_options={
                            'addrcount': 3,
                            'minmakercount': 4,
                            'makercountrange': [5, 1],
                            'mixdepthcount': 3,
                            'mintxcount': 2,
                            'txcountparams': [3, 1],
                            'timelambda': 5,
                            'stage1_timelambda_increase': 1,
                            'liquiditywait': 60,
                            'waittime': 20,
                            'mixdepthsrc': 0,
                            'restart': True,
                            'mincjamount': 35000,
                            'amtmixdepths': 4,
                            'rounding_chance': 0,
                            'rounding_sigfig_weights': [55, 15, 25, 65, 45],
                        },
                    ),
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[3000000, 15000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[3000000, 600000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[200000, 50000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[3000000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[3000000, 15000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
                WalletConfig(
                    funds=[3000000, 600000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{
                            'txfee': 0,
                            'cjfee_a': 5000,
                            'cjfee_r': 4e-05,
                            'ordertype': 'sw0reloffer',
                            'minsize': 30000,
                            'maxsize': 3000000,
                        }],
                    ),
                ),
            ],
        )



    def start_engine_infrastructure(self) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        self.node.create_wallet("jm_wallet")
        print("- created jm_wallet in BitcoinCore")

        self.start_irc_server()
        print("- started irc-server")

        # Start the JoinMarket orderbook watcher service and attach a client to poll it
        try:
            self.start_orderbook_watch()
            print("- started orderbook watcher")
        except Exception as e:
            print(f"- could not start orderbook watcher ({e})")























    async def cleanup_async_clients(self) -> None:
        """
        Cleanup async HTTP clients to prevent resource leaks.
        Should be called when shutting down the engine.
        """
        cleanup_tasks = []
        
        for client in self.clients:
            if hasattr(client, 'aclose'):
                cleanup_tasks.append(client.aclose())
        
        if self.obwatch_client and hasattr(self.obwatch_client, 'aclose'):
            cleanup_tasks.append(self.obwatch_client.aclose())
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            print("- closed all async HTTP clients")


    def shutdown_engine(self) -> None:
        """
        Shutdown the engine and cleanup resources.
        """
        if self.async_updates:
            try:
                asyncio.run(self.cleanup_async_clients())
            except Exception as e:
                print(f"- error during async client cleanup: {e}")

    def run_engine(self) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")

        # Note: Initial invoice payments now happen before this method is called
        try:
            initial_block = self.node.get_block_count()
        except Exception as e:
            print(f"- could not get initial block count: {e}")
            initial_block = 0
        for _ in range(5):
            # Takers need 3 confirmations of transactions for the sourcing commitments
            self.node.mine_block()

        print(f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60))

        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            while (self.scenario.rounds == 0 or self.current_round < self.scenario.rounds ) and (
                    self.scenario.blocks == 0 or self.current_block < self.scenario.blocks):
                # refresh block count
                for _ in range(3):
                    try:
                        self.current_block = self.node.get_block_count() - initial_block
                        break
                    except Exception as e:
                        print("- could not get blocks".ljust(60), end="\r")
                        print(f"Block exception: {e}", file=sys.stderr)

                # Check resource usage every 5 minutes (10 iterations * 30s = 5 min)
                current_time = int(time())
                if current_time - self.last_resource_check > 300:  # 5 minutes
                    try:
                        self.check_client_resources()
                        self.last_resource_check = current_time
                    except Exception as e:
                        print(f"- resource check failed: {e}")

                # safe updates
                try:
                    self.update_invoice_payments()
                except Exception as e:
                    print(f"- invoice update failed: {e}")
                try:
                    if self.async_updates:
                        # Use async path for parallel client updates
                        self.loop.run_until_complete(self.update_coinjoins_joinmarket_async())
                    else:
                        # Use synchronous path (legacy)
                        self.update_coinjoins_joinmarket()
                except Exception as e:
                    print(f"- coinjoin update failed: {e}")
                print(
                    f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60),
                    end="\r",
                )
                sleep(30)

            print()
            print("- limit reached")
            sleep(60)
            self.node.mine_block()

        finally:
            if self.loop is not None and not self.loop.is_closed():
                self.loop.close()

