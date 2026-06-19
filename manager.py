import sys

from manager.cli import main
from manager.log_output import install_structured_print_logger

if __name__ == "__main__":
    install_structured_print_logger()
    sys.exit(main())
