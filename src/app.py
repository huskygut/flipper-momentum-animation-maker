import tkinter as tk

from gui import FlipperMomentumGifMakerApp

def main() -> None:
    root = tk.Tk()
    FlipperMomentumGifMakerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()