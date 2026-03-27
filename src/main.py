import sys
from pathlib import Path

# Ensure the project root is in sys.path so the src package is importable
# when this file is run directly (python src/main.py).
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import tkinter as tk

from src.ui.gui import FlipperMomentumGifMakerApp


def main() -> None:
    root = tk.Tk()
    FlipperMomentumGifMakerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
