# CoinJoin Emulator Feature TODO

This list tracks missing or incomplete emulator features discovered during the
source audit. Keep `TODO.md` focused on cleanup and maintenance items.

## High Priority

- Add a documented scenario schema for both Wasabi and JoinMarket scenarios.
- Validate scenario files strictly:
  - reject unknown top-level and wallet fields;
  - reject invalid JoinMarket roles instead of treating every non-`maker` value as `taker`;
  - parse booleans explicitly instead of relying on Python truthiness.
- Extend JoinMarket scenario configuration beyond `role`, funds, delays, and stops:
  - coinjoin amount;
  - counterparties;
  - maker fee settings;
  - maker order type;
  - maker minimum size;
  - taker mixdepth;
  - round timeout and final settlement block count.
- Add JoinMarket scenario generation support to `manager.py genscen`.

## Medium Priority

- Decide whether the `console` subcommand should be implemented as an interactive
  control surface or removed from the CLI.
- Capture richer JoinMarket wallet artifacts during log export. Current
  `list_coins()` and `list_keys()` return placeholder strings.
- Support JoinMarket schedule/tumbler workflows through scenario configuration.
- Allow multiple concurrent JoinMarket taker rounds when the scenario explicitly
  requests it and enough makers are available.
- Add tests that prove JoinMarket feature parameters from a scenario reach the
  client RPC calls.

## Low Priority

- Consider adding engines for additional CoinJoin protocols if thesis scope
  expands beyond Wasabi and JoinMarket.
- Add README examples for minimal and advanced JoinMarket scenarios.
- Document which fields are engine-specific and which are shared across engines.
