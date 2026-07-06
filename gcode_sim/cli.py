"""Command-line entry point: gcode-sim run foo.nc [--plot] [--animate] [--ignore ignore.txt]"""

from __future__ import annotations

import argparse
import sys

from .errors import GcodeSimError
from .simulator import run_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gcode-sim")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Simulate an NC program and optionally plot it")
    run_parser.add_argument("path", help="Path to the .nc source file")
    run_parser.add_argument("--plot", action="store_true", help="Show a static plot of the toolpath")
    run_parser.add_argument("--animate", action="store_true", help="Show a continuous playback animation")
    run_parser.add_argument(
        "--ignore",
        metavar="FILE",
        help="Path to an ignore-list file (see gcode_sim/ignore_config.py): "
        "one 'G<n>' or '#<n>' per line to force-skip that G-code/variable",
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            toolpath = run_file(args.path, ignore_config_path=args.ignore)
        except GcodeSimError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        print(f"{len(toolpath.moves)} moves generated")

        if args.animate or args.plot:
            import matplotlib.pyplot as plt

            from .viz_matplotlib import animate, plot_static

            if args.animate:
                animate(toolpath)
            else:
                plot_static(toolpath)
            plt.show()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
