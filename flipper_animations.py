import io
import re
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageSequence, ImageTk
except ImportError as exc:
    raise SystemExit("Pillow is required. Install it with: pip install pillow") from exc

try:
    import heatshrink2
except ImportError as exc:
    raise SystemExit("heatshrink2 is required. Install it with: pip install heatshrink2") from exc

WIDTH = 128
HEIGHT = 64
PREVIEW_SCALE = 3
PREVIEW_SIZE = (WIDTH * PREVIEW_SCALE, HEIGHT * PREVIEW_SCALE)
PREVIEW_BG = (202, 214, 180)
PREVIEW_FG = (39, 52, 35)

THEME_BG = "#0f0f10"
THEME_PANEL = "#18181b"
THEME_PANEL_ALT = "#202024"
THEME_INPUT = "#111214"
THEME_FG = "#f3f3f3"
THEME_ACCENT = "#ff8c1a"
THEME_ACCENT_HOVER = "#ff9f3d"
THEME_ACCENT_DARK = "#c96a08"
THEME_BORDER = "#38383f"

DEFAULT_OUTPUT_TEXT = (
    "Load a GIF, tweak threshold / contrast with the slider or number box, then export.\n"
)


def sanitize_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or fallback


class FlipperMomentumGifMaker:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Flipper Momentum GIF Maker")
        self.root.geometry("1060x700")
        self.root.minsize(980, 640)

        self.frames: list[Image.Image] = []
        self.preview_image = None
        self.preview_canvas_image_id = None
        self.current_frame_index = 0
        self.play_job = None
        self.preview_refresh_job = None
        self.info_refresh_job = None
        self.playing = False

        self.pack_name = tk.StringVar(value="HuskyPack")
        self.anim_name = tk.StringVar(value="ghostcat")
        self.threshold = tk.IntVar(value=140)
        self.contrast = tk.DoubleVar(value=2.2)
        self.frame_rate = tk.IntVar(value=6)
        self.duration = tk.IntVar(value=360)
        self.weight = tk.IntVar(value=3)
        self.min_butthurt = tk.IntVar(value=0)
        self.max_butthurt = tk.IntVar(value=18)
        self.min_level = tk.IntVar(value=1)
        self.max_level = tk.IntVar(value=30)
        self.active_cycles = tk.IntVar(value=1)
        self.active_cooldown = tk.IntVar(value=1)
        self.passive_frames = tk.IntVar(value=1)
        self.fit_mode = tk.StringVar(value="contain")
        self.create_zip = tk.BooleanVar(value=True)

        self._build_ui()
        self._apply_theme()
        self._wire_preview_refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _safe_int(self, var, default=0) -> int:
        try:
            return int(float(var.get()))
        except Exception:
            return default

    def _safe_float(self, var, default=0.0) -> float:
        try:
            return float(var.get())
        except Exception:
            return default

    def _apply_theme(self) -> None:
        self.root.configure(bg=THEME_BG)
        self._style_widget(self.root)

    def _style_widget(self, widget) -> None:
        cls = widget.winfo_class()

        try:
            if cls in {"Frame", "Toplevel"}:
                widget.configure(bg=THEME_BG)
            elif cls == "LabelFrame":
                widget.configure(
                    bg=THEME_PANEL,
                    fg=THEME_ACCENT,
                    bd=1,
                    highlightthickness=1,
                    highlightbackground=THEME_BORDER,
                )
            elif cls == "Label":
                widget.configure(bg=widget.master.cget("bg"), fg=THEME_FG)
            elif cls == "Button":
                widget.configure(
                    bg=THEME_ACCENT,
                    fg="#111111",
                    activebackground=THEME_ACCENT_HOVER,
                    activeforeground="#111111",
                    relief="flat",
                    bd=0,
                    highlightthickness=0,
                    cursor="hand2",
                    padx=10,
                    pady=6,
                )
            elif cls == "Entry":
                widget.configure(
                    bg=THEME_INPUT,
                    fg=THEME_FG,
                    insertbackground=THEME_FG,
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=THEME_BORDER,
                    highlightcolor=THEME_ACCENT,
                )
            elif cls == "Spinbox":
                widget.configure(
                    bg=THEME_INPUT,
                    fg=THEME_FG,
                    insertbackground=THEME_FG,
                    buttonbackground=THEME_PANEL_ALT,
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=THEME_BORDER,
                    highlightcolor=THEME_ACCENT,
                )
            elif cls == "Scale":
                widget.configure(
                    bg=widget.master.cget("bg"),
                    fg=THEME_FG,
                    troughcolor=THEME_PANEL_ALT,
                    activebackground=THEME_ACCENT,
                    highlightthickness=0,
                )
            elif cls == "Checkbutton":
                widget.configure(
                    bg=widget.master.cget("bg"),
                    fg=THEME_FG,
                    activebackground=widget.master.cget("bg"),
                    activeforeground=THEME_FG,
                    selectcolor=THEME_PANEL_ALT,
                )
            elif cls == "Menubutton":
                widget.configure(
                    bg=THEME_PANEL_ALT,
                    fg=THEME_FG,
                    activebackground=THEME_ACCENT,
                    activeforeground="#111111",
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=THEME_BORDER,
                )
                try:
                    widget["menu"].configure(
                        bg=THEME_PANEL_ALT,
                        fg=THEME_FG,
                        activebackground=THEME_ACCENT,
                        activeforeground="#111111",
                    )
                except Exception:
                    pass
            elif cls == "Canvas":
                widget.configure(bg="#AAB995", highlightbackground=THEME_ACCENT)
            elif cls == "Text":
                widget.configure(
                    bg=THEME_INPUT,
                    fg=THEME_FG,
                    insertbackground=THEME_FG,
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=THEME_BORDER,
                    highlightcolor=THEME_ACCENT,
                    selectbackground=THEME_ACCENT_DARK,
                )
        except tk.TclError:
            pass

        for child in widget.winfo_children():
            self._style_widget(child)

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg=THEME_BG)
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="Pack Name").grid(row=0, column=0, sticky="w")
        tk.Entry(top, textvariable=self.pack_name, width=18).grid(row=1, column=0, padx=4)

        tk.Label(top, text="Animation Name").grid(row=0, column=1, sticky="w")
        tk.Entry(top, textvariable=self.anim_name, width=18).grid(row=1, column=1, padx=4)

        tk.Button(top, text="Load GIF", command=self.load_gif, width=14).grid(row=1, column=2, padx=6)
        tk.Button(top, text="Export Pack", command=self.export_pack, width=14).grid(row=1, column=3, padx=6)
        tk.Button(top, text="Play / Stop", command=self.toggle_playback, width=14).grid(row=1, column=4, padx=6)

        options = tk.LabelFrame(self.root, text="Conversion / Momentum Settings", bg=THEME_PANEL)
        options.pack(fill="x", padx=10, pady=6)

        self._add_slider_plus_number(
            options,
            label="Threshold",
            variable=self.threshold,
            from_=0,
            to=255,
            row=0,
            column=0,
            resolution=1,
        )
        self._add_slider_plus_number(
            options,
            label="Contrast",
            variable=self.contrast,
            from_=0.1,
            to=5.0,
            row=0,
            column=4,
            resolution=0.1,
            is_float=True,
        )

        self._add_spinbox(options, "Frame rate", self.frame_rate, 1, 60, 2, 0)
        self._add_spinbox(options, "Duration", self.duration, 1, 5000, 2, 2)
        self._add_spinbox(options, "Passive frames", self.passive_frames, 1, 9999, 2, 4)
        self._add_spinbox(options, "Active cycles", self.active_cycles, 1, 9999, 2, 6)
        self._add_spinbox(options, "Active cooldown", self.active_cooldown, 0, 9999, 2, 8)

        self._add_spinbox(options, "Min butthurt", self.min_butthurt, 0, 18, 4, 0)
        self._add_spinbox(options, "Max butthurt", self.max_butthurt, 0, 18, 4, 2)
        self._add_spinbox(options, "Min level", self.min_level, 0, 30, 4, 4)
        self._add_spinbox(options, "Max level", self.max_level, 0, 30, 4, 6)
        self._add_spinbox(options, "Weight", self.weight, 1, 100, 4, 8)

        tk.Label(options, text="Fit mode").grid(row=6, column=0, sticky="w", padx=6, pady=(8, 0))
        fit_menu = tk.OptionMenu(options, self.fit_mode, "contain", "cover")
        fit_menu.grid(row=7, column=0, sticky="w", padx=6)

        tk.Checkbutton(options, text="Also make ZIP", variable=self.create_zip).grid(
            row=7, column=2, sticky="w", padx=6
        )

        middle = tk.Frame(self.root, bg=THEME_BG)
        middle.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.LabelFrame(middle, text="Preview", bg=THEME_PANEL)
        left.pack(side="left", fill="y", expand=False, padx=(0, 8), anchor="n")

        self.preview_canvas = tk.Canvas(
            left,
            width=PREVIEW_SIZE[0],
            height=PREVIEW_SIZE[1],
            bg="#AAB995",
            highlightthickness=1,
            highlightbackground="#5E6B52",
        )
        self.preview_canvas.pack(padx=8, pady=8)
        self.preview_canvas_image_id = self.preview_canvas.create_image(
            PREVIEW_SIZE[0] // 2,
            PREVIEW_SIZE[1] // 2,
            image="",
        )

        controls = tk.Frame(left, bg=THEME_PANEL)
        controls.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(controls, text="Prev", command=self.prev_frame, width=10).pack(side="left", padx=4)
        tk.Button(controls, text="Next", command=self.next_frame, width=10).pack(side="left", padx=4)

        self.frame_slider = tk.Scale(
            controls,
            from_=0,
            to=0,
            orient="horizontal",
            command=self.on_frame_slider_move,
            length=190,
        )
        self.frame_slider.pack(side="left", fill="x", expand=True, padx=8)

        self.status_label = tk.Label(left, text="No GIF loaded", anchor="w", justify="left")
        self.status_label.pack(fill="x", padx=8, pady=(0, 8))

        right = tk.LabelFrame(middle, text="Generated files", bg=THEME_PANEL)
        right.pack(side="right", fill="both", expand=True)

        self.output_text = tk.Text(right, width=52, height=28)
        self.output_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.output_text.insert("1.0", DEFAULT_OUTPUT_TEXT)
        self.output_text.configure(state="disabled")

    def _wire_preview_refresh(self) -> None:
        preview_vars = [
            self.threshold,
            self.contrast,
            self.frame_rate,
            self.fit_mode,
        ]
        info_vars = [
            self.threshold,
            self.contrast,
            self.frame_rate,
            self.duration,
            self.passive_frames,
            self.active_cycles,
            self.active_cooldown,
            self.fit_mode,
            self.pack_name,
            self.anim_name,
            self.weight,
            self.min_butthurt,
            self.max_butthurt,
            self.min_level,
            self.max_level,
        ]

        for var in preview_vars:
            var.trace_add("write", self._queue_preview_refresh)
        for var in info_vars:
            var.trace_add("write", self._queue_info_refresh)

    def _queue_preview_refresh(self, *_args) -> None:
        if self.preview_refresh_job is None:
            self.preview_refresh_job = self.root.after_idle(self._run_preview_refresh)

    def _queue_info_refresh(self, *_args) -> None:
        if self.info_refresh_job is None:
            self.info_refresh_job = self.root.after_idle(self._run_info_refresh)

    def _run_preview_refresh(self) -> None:
        self.preview_refresh_job = None
        self.refresh_preview()

    def _run_info_refresh(self) -> None:
        self.info_refresh_job = None
        self.refresh_info_text()

    def _cancel_queued_refreshes(self) -> None:
        if self.preview_refresh_job is not None:
            try:
                self.root.after_cancel(self.preview_refresh_job)
            except Exception:
                pass
            self.preview_refresh_job = None
        if self.info_refresh_job is not None:
            try:
                self.root.after_cancel(self.info_refresh_job)
            except Exception:
                pass
            self.info_refresh_job = None

    def _add_slider_plus_number(
        self,
        parent,
        label,
        variable,
        from_,
        to,
        row,
        column,
        resolution,
        is_float=False,
    ) -> None:
        tk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=6, pady=(8, 0))

        slider = tk.Scale(
            parent,
            from_=from_,
            to=to,
            resolution=resolution,
            orient="horizontal",
            variable=variable,
            length=220,
            showvalue=False,
        )
        slider.grid(row=row + 1, column=column, columnspan=2, sticky="w", padx=6, pady=(0, 6))

        if is_float:
            box = tk.Spinbox(
                parent,
                from_=from_,
                to=to,
                increment=resolution,
                textvariable=variable,
                width=8,
                format="%.1f",
                command=lambda: self._coerce_spinbox_value(variable, from_, to, True),
            )
        else:
            box = tk.Spinbox(
                parent,
                from_=int(from_),
                to=int(to),
                increment=int(resolution),
                textvariable=variable,
                width=8,
                command=lambda: self._coerce_spinbox_value(variable, from_, to, False),
            )
        box.grid(row=row + 1, column=column + 2, sticky="w", padx=6, pady=(0, 6))

        box.bind("<KeyRelease>", lambda _e: (self._queue_preview_refresh(), self._queue_info_refresh()))
        box.bind("<FocusOut>", lambda _e: self._coerce_spinbox_value(variable, from_, to, is_float))
        box.bind("<Return>", lambda _e: self._coerce_spinbox_value(variable, from_, to, is_float))

    def _coerce_spinbox_value(self, variable, minv, maxv, is_float=False) -> None:
        try:
            value = float(variable.get()) if is_float else int(float(variable.get()))
        except Exception:
            value = minv
        value = max(minv, min(maxv, value))
        variable.set(round(value, 1) if is_float else int(value))

    def _add_spinbox(self, parent, label, variable, minv, maxv, row, col, increment=1):
        tk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=(8, 0))
        box = tk.Spinbox(
            parent,
            from_=minv,
            to=maxv,
            increment=increment,
            width=8,
            textvariable=variable,
            command=lambda: self._coerce_spinbox_value(variable, minv, maxv, False),
        )
        box.grid(row=row + 1, column=col, sticky="w", padx=6, pady=(0, 6))
        box.bind("<KeyRelease>", lambda _e: self._queue_info_refresh())
        box.bind("<FocusOut>", lambda _e: self._coerce_spinbox_value(variable, minv, maxv, False))
        box.bind("<Return>", lambda _e: self._coerce_spinbox_value(variable, minv, maxv, False))

    def set_output_text(self, text: str) -> None:
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", text)
        self.output_text.configure(state="disabled")

    def load_gif(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a GIF",
            filetypes=[("GIF files", "*.gif"), ("All files", "*.*")],
        )
        if not path:
            return

        self.playing = False
        self._cancel_playback()
        self._cancel_queued_refreshes()

        try:
            with Image.open(path) as img:
                loaded_frames = [frame.copy().convert("RGBA") for frame in ImageSequence.Iterator(img)]
        except Exception as exc:
            messagebox.showerror("Load failed", f"Could not load GIF:\n{exc}")
            return

        if not loaded_frames:
            messagebox.showerror("Load failed", "No frames were found in that GIF.")
            return

        self.frames = loaded_frames
        base_name = sanitize_name(Path(path).stem, "animation")
        self.anim_name.set(base_name)
        self.current_frame_index = 0
        self.frame_slider.configure(to=max(0, len(self.frames) - 1))
        self.frame_slider.set(0)
        self.refresh_preview()
        self.refresh_info_text()

    def fit_image(self, img: Image.Image) -> Image.Image:
        src = img.convert("RGBA")
        bg = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 255))

        if self.fit_mode.get() == "cover":
            scale = max(WIDTH / src.width, HEIGHT / src.height)
        else:
            scale = min(WIDTH / src.width, HEIGHT / src.height)

        new_size = (
            max(1, int(round(src.width * scale))),
            max(1, int(round(src.height * scale))),
        )
        resized = src.resize(new_size, Image.LANCZOS)
        x = (WIDTH - resized.width) // 2
        y = (HEIGHT - resized.height) // 2
        bg.paste(resized, (x, y), resized)
        return bg.convert("RGB")

    def process_frame(self, img: Image.Image) -> Image.Image:
        fitted = self.fit_image(img)
        gray = fitted.convert("L")
        contrast = max(0.1, self._safe_float(self.contrast, 2.2))
        gray = ImageEnhance.Contrast(gray).enhance(contrast)
        threshold = max(0, min(255, self._safe_int(self.threshold, 140)))
        return gray.point(lambda p: 255 if p > threshold else 0, mode="1")

    def build_preview_image(self, frame: Image.Image) -> Image.Image:
        mask = frame.convert("L").point(lambda p: 255 if p == 0 else 0, mode="L")
        preview = Image.new("RGB", (WIDTH, HEIGHT), PREVIEW_BG)
        preview.paste(PREVIEW_FG, mask=mask)
        preview = preview.resize(PREVIEW_SIZE, Image.NEAREST)
        if not self.playing:
            preview = preview.filter(ImageFilter.BoxBlur(0.2))
        return preview

    def refresh_preview(self) -> None:
        if not self.frames:
            self.preview_canvas.itemconfig(self.preview_canvas_image_id, image="")
            self.preview_image = None
            self.status_label.config(text="No GIF loaded")
            return

        self.current_frame_index = max(0, min(self.current_frame_index, len(self.frames) - 1))
        frame = self.process_frame(self.frames[self.current_frame_index])
        preview = self.build_preview_image(frame)
        self.preview_image = ImageTk.PhotoImage(preview)
        self.preview_canvas.itemconfig(self.preview_canvas_image_id, image=self.preview_image)
        self.status_label.config(
            text=(
                f"Frame {self.current_frame_index + 1}/{len(self.frames)}   "
                f"{WIDTH}x{HEIGHT}   {max(1, self._safe_int(self.frame_rate, 6))} fps\n"
                f"Threshold {self._safe_int(self.threshold, 140)}   Contrast {self._safe_float(self.contrast, 2.2):.1f}"
            )
        )

    def refresh_info_text(self) -> None:
        if not self.frames:
            self.set_output_text(DEFAULT_OUTPUT_TEXT)
            return

        passive = max(1, min(self._safe_int(self.passive_frames, 1), len(self.frames)))
        active = max(0, len(self.frames) - passive)
        frame_order = " ".join(str(i) for i in range(len(self.frames)))
        anim_dir = f"{sanitize_name(self.anim_name.get(), 'animation')}_128x64"
        text = (
            f"Pack folder:\n{sanitize_name(self.pack_name.get(), 'PackName')}/Anims/\n\n"
            f"Animation folder:\n{anim_dir}\n\n"
            f"Frames loaded: {len(self.frames)}\n"
            f"Passive frames: {passive}\n"
            f"Active frames: {active}\n"
            f"Threshold: {self._safe_int(self.threshold, 140)}\n"
            f"Contrast: {self._safe_float(self.contrast, 2.2):.1f}\n"
            f"Frames order:\n{frame_order}\n"
        )
        self.set_output_text(text)

    def on_frame_slider_move(self, value: str) -> None:
        try:
            self.current_frame_index = int(float(value))
        except Exception:
            self.current_frame_index = 0
        self.refresh_preview()

    def prev_frame(self) -> None:
        if not self.frames:
            return
        self.current_frame_index = (self.current_frame_index - 1) % len(self.frames)
        self.frame_slider.set(self.current_frame_index)

    def next_frame(self) -> None:
        if not self.frames:
            return
        self.current_frame_index = (self.current_frame_index + 1) % len(self.frames)
        self.frame_slider.set(self.current_frame_index)

    def toggle_playback(self) -> None:
        if not self.frames:
            return
        self.playing = not self.playing
        if self.playing:
            self._play_step()
        else:
            self._cancel_playback()
            self.refresh_preview()

    def _cancel_playback(self) -> None:
        if self.play_job is not None:
            try:
                self.root.after_cancel(self.play_job)
            except Exception:
                pass
            self.play_job = None

    def _play_step(self) -> None:
        if not self.playing or not self.frames:
            return
        self.current_frame_index = (self.current_frame_index + 1) % len(self.frames)
        self.frame_slider.set(self.current_frame_index)
        delay = max(20, int(1000 / max(1, self._safe_int(self.frame_rate, 6))))
        self.play_job = self.root.after(delay, self._play_step)

    def convert_bm(self, img: Image.Image) -> bytes:
        with io.BytesIO() as output:
            bm_img = img.convert("1")
            bm_img = ImageOps.invert(bm_img)
            bm_img.save(output, format="XBM")
            xbm = output.getvalue().decode(errors="ignore")

        try:
            hex_bytes = re.findall(r"0x([0-9a-fA-F]{2})", xbm)
            if not hex_bytes:
                raise ValueError("No XBM byte data found")
            raw_bytes = bytearray(int(byte, 16) for byte in hex_bytes)
        except Exception as exc:
            raise ValueError(f"Failed to parse XBM data: {exc}") from exc

        compressed_payload = bytearray(heatshrink2.compress(raw_bytes, window_sz2=8, lookahead_sz2=4))
        compressed = bytearray([len(compressed_payload) & 0xFF, len(compressed_payload) >> 8]) + compressed_payload

        if len(compressed) + 2 < len(raw_bytes) + 1:
            return b"\x01\x00" + compressed
        return b"\x00" + raw_bytes

    def build_meta(self, frame_count: int) -> str:
        passive = max(1, min(self._safe_int(self.passive_frames, 1), frame_count))
        active = max(0, frame_count - passive)
        frame_order = " ".join(str(i) for i in range(frame_count))
        return (
            "Filetype: Flipper Animation\n"
            "Version: 1\n\n"
            f"Width: {WIDTH}\n"
            f"Height: {HEIGHT}\n"
            f"Passive frames: {passive}\n"
            f"Active frames: {active}\n"
            f"Frames order: {frame_order}\n"
            f"Active cycles: {max(1, self._safe_int(self.active_cycles, 1))}\n"
            f"Frame rate: {max(1, self._safe_int(self.frame_rate, 6))}\n"
            f"Duration: {max(1, self._safe_int(self.duration, 360))}\n"
            f"Active cooldown: {max(0, self._safe_int(self.active_cooldown, 1))}\n\n"
            "Bubble slots: 0\n"
        )

    def build_manifest_block(self, anim_dir_name: str) -> str:
        min_butthurt = max(0, min(18, self._safe_int(self.min_butthurt, 0)))
        max_butthurt = max(min_butthurt, min(18, self._safe_int(self.max_butthurt, 18)))
        min_level = max(0, min(30, self._safe_int(self.min_level, 1)))
        max_level = max(min_level, min(30, self._safe_int(self.max_level, 30)))
        weight = max(1, self._safe_int(self.weight, 3))
        return (
            f"Name: {anim_dir_name}\n"
            f"Min butthurt: {min_butthurt}\n"
            f"Max butthurt: {max_butthurt}\n"
            f"Min level: {min_level}\n"
            f"Max level: {max_level}\n"
            f"Weight: {weight}\n"
        )

    def update_manifest(self, anims_dir: Path, anim_dir_name: str) -> int:
        manifest_path = anims_dir / "manifest.txt"
        header = "Filetype: Flipper Animation Manifest\nVersion: 1\n\n"
        blocks: dict[str, str] = {}

        if manifest_path.exists():
            raw = manifest_path.read_text(encoding="utf-8", errors="ignore")
            body = raw
            if raw.startswith("Filetype:"):
                parts = raw.split("\n\n", 1)
                body = parts[1] if len(parts) > 1 else ""
            for block in [b.strip() for b in body.split("\n\n") if b.strip()]:
                name = None
                for line in block.splitlines():
                    if line.startswith("Name:"):
                        name = line.split(":", 1)[1].strip()
                        break
                if name:
                    blocks[name] = block + "\n"

        blocks[anim_dir_name] = self.build_manifest_block(anim_dir_name)

        ordered_names = sorted(blocks.keys(), key=str.lower)
        content = header + "\n".join(blocks[name].rstrip() + "\n" for name in ordered_names)
        manifest_path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
        return len(ordered_names)

    def export_pack(self) -> None:
        if not self.frames:
            messagebox.showerror("No GIF", "Load a GIF first.")
            return

        out_root = filedialog.askdirectory(title="Choose export folder")
        if not out_root:
            return

        pack_name = sanitize_name(self.pack_name.get(), "PackName")
        anim_base = sanitize_name(self.anim_name.get(), "animation")
        anim_dir_name = f"{anim_base}_128x64"

        pack_dir = Path(out_root) / pack_name
        anims_dir = pack_dir / "Anims"
        anim_dir = anims_dir / anim_dir_name
        anim_dir.mkdir(parents=True, exist_ok=True)

        for old_frame in anim_dir.glob("frame_*.bm"):
            try:
                old_frame.unlink()
            except OSError:
                pass

        try:
            processed_frames = [self.process_frame(frame) for frame in self.frames]
            for idx, frame in enumerate(processed_frames):
                (anim_dir / f"frame_{idx}.bm").write_bytes(self.convert_bm(frame))

            (anim_dir / "meta.txt").write_text(
                self.build_meta(len(processed_frames)), encoding="utf-8", newline="\n"
            )
            manifest_count = self.update_manifest(anims_dir, anim_dir_name)
        except Exception as exc:
            messagebox.showerror("Export failed", f"Could not export pack:\n{exc}")
            return

        zip_path = None
        if self.create_zip.get():
            zip_path = Path(out_root) / f"{pack_name}.zip"
            try:
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for path in pack_dir.rglob("*"):
                        if path.is_file():
                            zf.write(path, path.relative_to(Path(out_root)))
            except Exception as exc:
                messagebox.showerror("ZIP failed", f"Pack exported, but ZIP creation failed:\n{exc}")
                zip_path = None

        result = [
            "Built Momentum animation pack successfully.",
            "",
            f"Folder: {pack_dir}",
            f"Animation dir: {anim_dir}",
            f"Frames: {len(processed_frames)}",
            f"Threshold: {self._safe_int(self.threshold, 140)}",
            f"Contrast: {self._safe_float(self.contrast, 2.2):.1f}",
            f"Manifest entries: {manifest_count}",
        ]
        if zip_path:
            result.append(f"ZIP: {zip_path}")
        result.extend(
            [
                "",
                "Install path on Flipper:",
                "/ext/asset_packs/PackName/Anims/...",
                "",
                "Then pick the pack in Momentum Settings.",
            ]
        )
        self.set_output_text("\n".join(result))
        messagebox.showinfo("Done", "Momentum pack created.")

    def on_close(self) -> None:
        self.playing = False
        self._cancel_playback()
        self._cancel_queued_refreshes()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    FlipperMomentumGifMaker(root)
    root.mainloop()


if __name__ == "__main__":
    main()
