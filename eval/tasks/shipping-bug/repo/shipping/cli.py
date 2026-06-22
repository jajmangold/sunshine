"""Command-line entry for the shipping price calculator."""
import sys
from .order import Order, process_order


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    tier = argv[0] if argv else "bronze"
    items = [float(x) for x in argv[1:]]
    print(f"{process_order(Order(items=items, tier=tier)):.2f}")


if __name__ == "__main__":
    main()
