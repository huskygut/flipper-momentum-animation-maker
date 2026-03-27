import tkinter as tk

from src.ui.gui import FlipperMomentumGifMakerApp


def main() -> None:
    root = tk.Tk()
    FlipperMomentumGifMakerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
