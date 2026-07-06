"""Command-line entry point: gcode-sim run foo.nc [--plot] [--animate] [--ignore ignore.txt]"""

from __future__ import annotations

import argparse
import sys
import warnings

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
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                toolpath = run_file(args.path, ignore_config_path=args.ignore)
        except GcodeSimError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        # Printed explicitly (rather than left to warnings' own default
        # stderr handling) so a run that skips everything and produces an
        # empty toolpath always has a visible "why" right next to the
        # move count, not just whatever scrolled by earlier.
        for w in caught:
            print(f"warning: {w.message}", file=sys.stderr)

        print(f"{len(toolpath.moves)} moves generated")
        if not toolpath.moves:
            print(
                "note: toolpath is EMPTY -- see the warning(s) above for why "
                "(e.g. every G-code/variable in the file was skipped)",
                file=sys.stderr,
            )

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
