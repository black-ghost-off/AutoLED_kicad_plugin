"""Command line use, without the KiCad GUI.

    python -m auto_led.cli IMAGE [--config cfg.json] [--set key=value ...]
                           [--board in.kicad_pcb [--board-out out.kicad_pcb]]

Placing on a board needs KiCad's Python (the one that can `import pcbnew`).
"""

import argparse
import json
import sys

from . import config, generator


def _parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="auto_led", description="Place LEDs on an image shape.")
    ap.add_argument("image", nargs="?", help="SVG / PNG / BMP / JPG file")
    ap.add_argument("--config", help="JSON settings file (see config.DEFAULTS)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a setting, e.g. --set pitch_x=7.5 --set preset='\"LED 0805\"'")
    ap.add_argument("--out-dir", help="output folder")
    ap.add_argument("--board", help="board to place footprints on (needs pcbnew)")
    ap.add_argument("--board-out", help="where to save the board (default: overwrite --board)")
    ap.add_argument("--list", action="store_true", help="list settings and LED presets")
    args = ap.parse_args(argv)

    if args.list:
        print(json.dumps(config.DEFAULTS, indent=2))
        print("presets:", ", ".join(config.PRESETS))
        return 0

    cfg = config.load(args.config) if args.config else dict(config.DEFAULTS)
    for item in args.set:
        key, _, value = item.partition("=")
        if key not in config.DEFAULTS:
            ap.error("unknown setting %r" % key)
        cfg[key] = _parse_value(value)
    if args.image:
        cfg["image_path"] = args.image
    if args.out_dir:
        cfg["out_dir"] = args.out_dir
    if not cfg["image_path"]:
        ap.error("no image given")

    board = None
    if args.board:
        import pcbnew
        board = pcbnew.LoadBoard(args.board)
    else:
        cfg["place_pcb"] = False

    generator.generate(cfg, board=board, board_path=args.board or "")
    if board is not None:
        out = args.board_out or args.board
        board.Save(out)
        print("Saved board " + out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
