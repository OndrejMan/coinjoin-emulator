from .joinmarket_client import JoinMarketClientServer

class MakerClient(JoinMarketClientServer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.maker_running = False

    def get_status(self):
        response = self.session()
        self.maker_running = response.get("maker_running", False)
        return response

    def update(self, current_block, current_round) -> int:
        # Only update if we are not already running and the delay is over
        if self.is_paused(current_block):
            return 0

        if not self.maker_running:
            offer = self.get_offer(current_round)
            self.start_maker(**offer)
            print(f"Starting maker {self.name}")
            self.maker_running = True
        # Maker doesn’t affect the coinjoin round counter.
        return 0

class TakerClient(JoinMarketClientServer):
    """
    This class implements the logic for a taker that does *not* have tumbler options.
    """

    def get_status(self):
        response = self.session()
        self.coinjoin_in_process = response.get("coinjoin_in_process", False)
        return response

    def update(self, current_block, current_round):
        self.get_status()

        # Check delay first
        delta = 0
        # If no coinjoin is running, start one
        if not self.coinjoin_in_process and not self.is_paused(current_block):
            offer = self.get_offer(current_round)
            offer["destination"] = self.get_new_address()
            self.start_coinjoin(**offer)
            self.coinjoin_start = current_block
            self.coinjoin_in_process = True
            delta = +1
            print(f"Starting coinjoin {self.name}")
            print(f"- coinjoin rounds: {current_round + delta} (block {current_block})".ljust(60))

        # Otherwise, if coinjoin is running and the elapsed blocks are sufficient, stop it.
        elif self.coinjoin_in_process and self.coinjoin_start + 8 < current_block:
            self.stop_coinjoin()
            self.coinjoin_in_process = False
            self.next_coinjoin_allowed = current_block + self.time_between_rounds
            delta = -1
            print(f"Stopping coinjoin {self.name}")
            print(f"- coinjoin rounds: {current_round + delta} (block {current_block})".ljust(60))
        return delta

class TumblerTakerClient(JoinMarketClientServer):
    """
    This subclass is for a taker with tumbler options.
    It splits its behavior between starting a scheduled coinjoin and updating an ongoing one.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tumbler_options = kwargs.get("tumbler_options", None)
        self.last_schedule = None
        self.coinjoin_completed = True

    def get_status(self):
        response = self.session()
        self.coinjoin_in_process = response.get("coinjoin_in_process", False)
        schedule = response.get("schedule", None)
        if schedule != self.last_schedule:
            self.coinjoin_completed = True
            self.last_schedule = schedule
        return response

    def update(self, current_block, current_round):
        self.get_status()

        # If no coinjoin is running, run the scheduled coinjoin.
        if not self.coinjoin_in_process and not self.is_paused(current_block):
            print(f"Starting scheduled coinjoin for {self.name}")
            response = self.run_schedule()
            self.last_schedule = response["schedule"]
            print(response)
            self.coinjoin_in_process = True
            self.coinjoin_start = current_block
            return 0

        delta = 0
        if self.coinjoin_completed:
            delta = +1
            self.coinjoin_completed = False

        # If a coinjoin is running and enough blocks have passed, update the schedule.
        if self.coinjoin_in_process and self.coinjoin_start + 4 < current_block:
            # TODO: If Schedule is not running, start it.
            response = self.get_schedule()
            print(response)
            response = self.list_unspent_coins()
            print(response)
            self.coinjoin_start = current_block

        return delta