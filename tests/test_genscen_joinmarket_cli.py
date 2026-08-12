"""JoinMarket generator CLI regressions."""

from manager import cli


def test_joinmarket_generator_help_formats_percent_signs() -> None:
    try:
        cli.build_parser().parse_args(["genscen-joinmarket", "--help"])
    except SystemExit as error:
        assert error.code == 0
