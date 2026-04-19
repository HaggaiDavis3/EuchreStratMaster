import argparse
import sys
from euchre.ui import UI
from euchre.engine import GameEngine


def main() -> None:
    # Ensure stdout uses UTF-8 on Windows so suit symbols display correctly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Euchre practice game")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = parser.parse_args()

    ui = UI(use_color=not args.no_color)
    engine = GameEngine(ui)
    engine.run()


if __name__ == "__main__":
    main()
