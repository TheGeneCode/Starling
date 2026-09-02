"""Support `python -m starling`, which is what the capture window relaunches."""

import sys

from starling.cli import main

if __name__ == "__main__":
    sys.exit(main())
