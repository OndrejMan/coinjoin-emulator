---
name: repo-python-tests
description: Use when adding, refactoring, or reviewing Python tests in this coinjoin-emulator repository, especially tests for CLI dispatch, orchestration functions, parser behavior, or functions that would otherwise require patching globals.
---

# Repo Python Tests

## Style

Write new tests in pytest function style, not `unittest.TestCase`, unless editing an existing unittest-only file where matching local style is more important.

Prefer:

```python
def test_dispatch_clean_runs_cleanup() -> None:
    ...
    assert exit_code == 0
```

Avoid new class-based tests for simple function behavior.

## Test Data Helpers

Use small local helper constructors when fake argument objects repeat. Name them after the domain concept, not the implementation.

For CLI command arguments:

```python
from types import SimpleNamespace


def command_args(command: str, **overrides: object) -> SimpleNamespace:
    return SimpleNamespace(command=command, **overrides)
```

For `run_engine` arguments:

```python
from types import SimpleNamespace


def run_args(
    no_logs: bool = False,
    download_btc_data: str = "",
    image_prefix: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        no_logs=no_logs,
        download_btc_data=download_btc_data,
        image_prefix=image_prefix,
    )
```

This keeps tests readable for developers used to Java/C# factory helpers.

## Mocking

Prefer explicit dependency injection over string-based `patch(...)`.

Good:

```python
driver = Mock()
create_driver = Mock(return_value=driver)

exit_code = cli.dispatch(args, driver_factory=create_driver)
```

Avoid when possible:

```python
with patch("manager.cli.create_driver", return_value=driver):
    ...
```

If production code is hard to test without patching, consider adding optional callable parameters with production defaults, as done in `manager.cli.dispatch()` and `manager.application.run_engine()`.

## Assertions

Use plain pytest assertions for values:

```python
assert exit_code == 0
```

Use mock verification for interactions:

```python
create_driver.assert_called_once_with(args)
create_engine.assert_not_called()
driver.cleanup.assert_called_once_with("prefix/")
```

Use `pytest.raises` for expected exceptions and `capsys` for stdout/stderr:

```python
with pytest.raises(RuntimeError):
    download_btc_data(driver, destination)

assert "failed to download" in capsys.readouterr().err
```

## Structure

Separate parser tests from dispatch/orchestration tests:

- Parser tests should call `cli.main(argv, dispatcher=mock_dispatcher)` and assert parsed fields.
- Dispatch tests should pass `command_args(...)` directly and inject mock factories/runners.
- Application tests should call orchestration functions directly with `run_args(...)`.

Keep each test focused on one branch or behavior.

## Verification

After changing these tests or the tested modules, run:

```bash
uv run pytest
uv run ruff check manager.py manager tests/test_application.py tests/test_cli.py tests/test_manager.py
uv run mypy manager/application.py manager/cli.py tests/test_application.py tests/test_cli.py tests/test_manager.py
```
