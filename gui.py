from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageTk
except ImportError as exc:
    raise SystemExit("Pillow is required. Install it with: pip install pillow") from exc

from constants import (
    DEFAULT_OUTPUT_TEXT,
    HEIGHT,
    PREVIEW_SIZE,
    THEME_ACCENT,
    THEME_ACCENT_DARK,
    THEME_ACCENT_HOVER,
    THEME_BG,
    THEME_BORDER,
    THEME_FG,
    THEME_INPUT,
    THEME_PANEL,
    THEME_PANEL_ALT,
    WIDTH,
)
from bm_encoder import BMEncoder
from exporter import PackExporter
from image_processing import ImageProcessor
from manifest import ManifestBuilder
from utils import sanitize_name


class FlipperMomentumGifMakerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Flipper Momentum GIF Maker")
        self.root.geometry("1060x700")
        self.root.minsize(980, 640)

        self.all_frames: list[Image.Image] = []
        self.active_indices: list[int] = []
        self._indices_clean: bool = True   # False → _normalize_active_indices must validate
        self.preview_image = None
        self.preview_canvas_image_id = None
        self.current_frame_index = 0
        self.play_job = None
        self.preview_refresh_job = None
        self.info_refresh_job = None
        self.playing = False
        self.frame_tools_widgets: list[tk.Widget] = []
        self._trace_ids: list[tuple] = []  # (var, mode, trace_id) – cleaned up on close

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
        self.target_frames = tk.IntVar(value=50)
        self.trim_start = tk.IntVar(value=0)
        self.trim_end = tk.IntVar(value=0)

        self.image_processor = ImageProcessor(
            fit_mode_getter=lambda: self.fit_mode.get(),
            threshold_getter=lambda: self._safe_int(self.threshold, 140),
            contrast_getter=lambda: self._safe_float(self.contrast, 2.2),
        )
        self.manifest_builder = ManifestBuilder(
            frame_rate_getter=lambda: self._safe_int(self.frame_rate, 6),
            duration_getter=lambda: self._safe_int(self.duration, 360),
            passive_frames_getter=lambda: self._safe_int(self.passive_frames, 1),
            active_cycles_getter=lambda: self._safe_int(self.active_cycles, 1),
            active_cooldown_getter=lambda: self._safe_int(self.active_cooldown, 1),
            min_butthurt_getter=lambda: self._safe_int(self.min_butthurt, 0),
            max_butthurt_getter=lambda: self._safe_int(self.max_butthurt, 18),
            min_level_getter=lambda: self._safe_int(self.min_level, 1),
            max_level_getter=lambda: self._safe_int(self.max_level, 30),
            weight_getter=lambda: self._safe_int(self.weight, 3),
        )
        self.exporter = PackExporter(self.image_processor, self.manifest_builder)

        self._build_ui()
        self._apply_theme()
        self._wire_preview_refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)


    def _normalize_active_indices(self) -> None:
        if self._indices_clean:
            return
        if not self.all_frames:
            self.active_indices = []
            self._indices_clean = True
            return
        valid = [i for i in self.active_indices if 0 <= i < len(self.all_frames)]
        if len(valid) != len(self.active_indices):
            self.active_indices = valid
        self._indices_clean = True

    def has_active_frames(self) -> bool:
        self._normalize_active_indices()
        return bool(self.active_indices)

    def active_frame_count(self) -> int:
        self._normalize_active_indices()
        return len(self.active_indices)

    def get_active_frame(self, active_pos: int):
        if not self.has_active_frames():
            return None
        active_pos = max(0, min(active_pos, len(self.active_indices) - 1))
        return self.all_frames[self.active_indices[active_pos]]

    def iter_active_frames_for_export(self):
        self._normalize_active_indices()
        for idx in self.active_indices:
            yield self.all_frames[idx]

    def _clamp_current_frame(self) -> None:
        active_count = self.active_frame_count()
        if active_count == 0:
            self.current_frame_index = 0
            self.frame_slider.configure(from_=0, to=0)
            self.frame_slider.set(0)
            return
        self.current_frame_index = max(0, min(self.current_frame_index, active_count - 1))
        self.frame_slider.configure(from_=0, to=max(0, active_count - 1))
        self.frame_slider.set(self.current_frame_index)

    def _evenly_reduce_indices(self, total: int, target: int) -> list[int]:
        target = max(1, min(target, total))
        if target >= total:
            return list(range(total))
        if target == 1:
            return [0]
        step = (total - 1) / (target - 1)
        indices = [round(i * step) for i in range(target)]
        deduped: list[int] = []
        seen = set()
        for idx in indices:
            idx = max(0, min(total - 1, int(idx)))
            if idx not in seen:
                deduped.append(idx)
                seen.add(idx)
        candidate = 0
        while len(deduped) < target and candidate < total:
            if candidate not in seen:
                deduped.append(candidate)
                seen.add(candidate)
            candidate += 1
        return sorted(deduped)[:target]

    def _apply_active_indices(self, new_indices: list[int], action_name: str) -> None:
        if not self.all_frames:
            return
        normalized = sorted({i for i in new_indices if 0 <= i < len(self.all_frames)})
        if not normalized:
            messagebox.showerror("No frames left", f"{action_name} would remove every frame. Keep at least one frame.")
            return
        was_playing = self.playing
        self.playing = False
        self._cancel_playback()
        self.active_indices = normalized
        self._indices_clean = True
        self.current_frame_index = min(self.current_frame_index, len(self.active_indices) - 1)
        self._clamp_current_frame()
        self._update_control_states()
        self.refresh_preview()
        self.refresh_info_text()
        if was_playing:
            self.playing = True
            self._play_step()

    def reduce_frames_evenly(self) -> None:
        if not self.has_active_frames():
            return
        current_total = self.active_frame_count()
        target = max(1, self._safe_int(self.target_frames, current_total))
        if target >= current_total:
            messagebox.showinfo("Nothing to reduce", "Target frame count is already greater than or equal to the active frame count.")
            return
        reduced_positions = self._evenly_reduce_indices(current_total, target)
        new_indices = [self.active_indices[pos] for pos in reduced_positions]
        self._apply_active_indices(new_indices, "Frame reduction")

    def apply_trim(self) -> None:
        if not self.has_active_frames():
            return
        start_trim = max(0, self._safe_int(self.trim_start, 0))
        end_trim = max(0, self._safe_int(self.trim_end, 0))
        current_total = self.active_frame_count()
        if start_trim == 0 and end_trim == 0:
            messagebox.showinfo("Nothing to trim", "Trim start and trim end are both set to 0.")
            return
        if start_trim + end_trim >= current_total:
            messagebox.showerror("Trim too large", "Trim values would remove every active frame.")
            return
        new_indices = self.active_indices[start_trim: current_total - end_trim]
        self._apply_active_indices(new_indices, "Trim")

    def reset_active_frames(self) -> None:
        if not self.all_frames:
            return
        self.trim_start.set(0)
        self.trim_end.set(0)
        self.target_frames.set(len(self.all_frames))
        self._apply_active_indices(list(range(len(self.all_frames))), "Reset")

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

        self.load_button = tk.Button(top, text="Load GIF", command=self.load_gif, width=14)
        self.load_button.grid(row=1, column=2, padx=6)
        self.export_button = tk.Button(top, text="Export Pack", command=self.export_pack, width=14)
        self.export_button.grid(row=1, column=3, padx=6)
        self.play_button = tk.Button(top, text="Play / Stop", command=self.toggle_playback, width=14)
        self.play_button.grid(row=1, column=4, padx=6)

        options = tk.LabelFrame(self.root, text="Conversion / Momentum Settings", bg=THEME_PANEL)
        options.pack(fill="x", padx=10, pady=6)

        self._add_slider_plus_number(options, "Threshold", self.threshold, 0, 255, 0, 0, 1)
        self._add_slider_plus_number(
            options,
            "Contrast",
            self.contrast,
            0.1,
            5.0,
            0,
            4,
            0.1,
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

        frame_tools = tk.LabelFrame(self.root, text="Frame Tools", bg=THEME_PANEL)
        frame_tools.pack(fill="x", padx=10, pady=(0, 6))

        self.target_frames_box = self._add_spinbox(frame_tools, "Target frames", self.target_frames, 1, 9999, 0, 0)
        self.reduce_button = tk.Button(frame_tools, text="Reduce Evenly", command=self.reduce_frames_evenly, width=14)
        self.reduce_button.grid(row=1, column=1, sticky="w", padx=6, pady=(20, 6))

        self.trim_start_box = self._add_spinbox(frame_tools, "Trim start", self.trim_start, 0, 9999, 0, 2)
        self.trim_end_box = self._add_spinbox(frame_tools, "Trim end", self.trim_end, 0, 9999, 0, 3)
        self.trim_button = tk.Button(frame_tools, text="Apply Trim", command=self.apply_trim, width=12)
        self.trim_button.grid(row=1, column=4, sticky="w", padx=6, pady=(20, 6))

        self.reset_frames_button = tk.Button(frame_tools, text="Reset Frames", command=self.reset_active_frames, width=12)
        self.reset_frames_button.grid(row=1, column=5, sticky="w", padx=6, pady=(20, 6))
        self.frame_tools_widgets = [self.target_frames_box, self.trim_start_box, self.trim_end_box]

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
        self.prev_button = tk.Button(controls, text="Prev", command=self.prev_frame, width=10)
        self.prev_button.pack(side="left", padx=4)
        self.next_button = tk.Button(controls, text="Next", command=self.next_frame, width=10)
        self.next_button.pack(side="left", padx=4)

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
        self._update_control_states()

    def _wire_preview_refresh(self) -> None:
        preview_vars = [self.threshold, self.contrast, self.frame_rate, self.fit_mode]
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
            tid = var.trace_add("write", self._queue_preview_refresh)
            self._trace_ids.append((var, "write", tid))
        for var in info_vars:
            tid = var.trace_add("write", self._queue_info_refresh)
            self._trace_ids.append((var, "write", tid))

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
        return box

    def _set_widget_state(self, widget, state: str) -> None:
        try:
            widget.configure(state=state)
        except Exception:
            pass

    def _update_control_states(self) -> None:
        has_frames = self.has_active_frames()
        nav_state = "normal" if has_frames else "disabled"
        self._set_widget_state(self.export_button, nav_state)
        self._set_widget_state(self.play_button, nav_state)
        self._set_widget_state(self.prev_button, nav_state)
        self._set_widget_state(self.next_button, nav_state)
        self._set_widget_state(self.frame_slider, nav_state)
        self._set_widget_state(self.reduce_button, nav_state)
        self._set_widget_state(self.trim_button, nav_state)
        self._set_widget_state(self.reset_frames_button, nav_state)
        for widget in self.frame_tools_widgets:
            self._set_widget_state(widget, nav_state)

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
        self.image_processor.clear_cache()

        try:
            loaded_frames = self.image_processor.load_gif_frames(path)
        except Exception as exc:
            messagebox.showerror("Load failed", f"Could not load GIF:\n{exc}")
            return

        if not loaded_frames:
            messagebox.showerror("Load failed", "No frames were found in that GIF.")
            return

        estimated_mb = self.image_processor.estimate_memory_mb(loaded_frames)
        if len(loaded_frames) > 300 or estimated_mb > 200:
            proceed = messagebox.askyesno(
                "Large GIF warning",
                f"This GIF has {len(loaded_frames)} frames and may use about {estimated_mb:.1f} MB in memory.\n\nContinue loading it?",
            )
            if not proceed:
                return

        self.all_frames = loaded_frames
        self.active_indices = list(range(len(loaded_frames)))
        self._indices_clean = True
        self.target_frames.set(min(50, max(1, len(loaded_frames))))
        self.trim_start.set(0)
        self.trim_end.set(0)
        self.anim_name.set(self.image_processor.suggest_animation_name(path))
        self.current_frame_index = 0
        self.frame_slider.configure(from_=0, to=max(0, self.active_frame_count() - 1))
        self.frame_slider.set(0)
        self._update_control_states()
        self.refresh_preview()
        self.refresh_info_text()

    def refresh_preview(self) -> None:
        if not self.has_active_frames():
            self.preview_canvas.itemconfig(self.preview_canvas_image_id, image="")
            self.preview_image = None
            self.status_label.config(text="No GIF loaded")
            return

        self.current_frame_index = max(0, min(self.current_frame_index, self.active_frame_count() - 1))
        try:
            current_source = self.get_active_frame(self.current_frame_index)
            if current_source is None:
                raise ValueError("No active frame available for preview.")
            frame = self.image_processor.process_frame(current_source)
            preview = self.image_processor.build_preview_image(frame, self.playing)
            self.preview_image = ImageTk.PhotoImage(preview)
            self.preview_canvas.itemconfig(self.preview_canvas_image_id, image=self.preview_image)
        except Exception as exc:
            self.preview_canvas.itemconfig(self.preview_canvas_image_id, image="")
            self.preview_image = None
            self.status_label.config(text=f"Preview failed: {exc}")
            return
        self.status_label.config(
            text=(
                f"Frame {self.current_frame_index + 1}/{self.active_frame_count()}   "
                f"{WIDTH}x{HEIGHT}   {max(1, self._safe_int(self.frame_rate, 6))} fps\n"
                f"Threshold {self._safe_int(self.threshold, 140)}   Contrast {self._safe_float(self.contrast, 2.2):.1f}"
            )
        )

    def refresh_info_text(self) -> None:
        if not self.has_active_frames():
            self.set_output_text(DEFAULT_OUTPUT_TEXT)
            return

        active_count = self.active_frame_count()
        passive = max(1, min(self._safe_int(self.passive_frames, 1), active_count))
        active = max(0, active_count - passive)
        indices_preview = " ".join(str(i) for i in self.active_indices[:100])
        if len(self.active_indices) > 100:
            indices_preview += " ..."
        anim_dir = f"{sanitize_name(self.anim_name.get(), 'animation')}_128x64"
        text = (
            f"Pack folder:\n{sanitize_name(self.pack_name.get(), 'PackName')}/Anims/\n\n"
            f"Animation folder:\n{anim_dir}\n\n"
            f"Original frames: {len(self.all_frames)}\n"
            f"Active frames: {active_count}\n"
            f"Passive frames: {passive}\n"
            f"Active animation frames: {active}\n"
            f"Threshold: {self._safe_int(self.threshold, 140)}\n"
            f"Contrast: {self._safe_float(self.contrast, 2.2):.1f}\n"
            f"Original frame indices kept:\n{indices_preview}\n"
        )
        self.set_output_text(text)

    def on_frame_slider_move(self, value: str) -> None:
        try:
            self.current_frame_index = int(float(value))
        except Exception:
            self.current_frame_index = 0
        self.refresh_preview()

    def prev_frame(self) -> None:
        if not self.has_active_frames():
            return
        self.current_frame_index = (self.current_frame_index - 1) % self.active_frame_count()
        self.frame_slider.set(self.current_frame_index)

    def next_frame(self) -> None:
        if not self.has_active_frames():
            return
        self.current_frame_index = (self.current_frame_index + 1) % self.active_frame_count()
        self.frame_slider.set(self.current_frame_index)

    def toggle_playback(self) -> None:
        if not self.has_active_frames():
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
        if not self.playing or not self.has_active_frames():
            return
        self.current_frame_index = (self.current_frame_index + 1) % self.active_frame_count()
        self.frame_slider.set(self.current_frame_index)
        delay = max(20, int(1000 / max(1, self._safe_int(self.frame_rate, 6))))
        self.play_job = self.root.after(delay, self._play_step)

    def export_pack(self) -> None:
        if not self.has_active_frames():
            messagebox.showerror("No GIF", "Load a GIF first.")
            return

        out_root = filedialog.askdirectory(title="Choose export folder")
        if not out_root:
            return

        pack_name = sanitize_name(self.pack_name.get(), "PackName")
        anim_base = sanitize_name(self.anim_name.get(), "animation")

        if not BMEncoder.is_available():
            messagebox.showerror(
                "Missing dependency",
                "Export requires heatshrink2. Install it with:\n\npip install heatshrink2",
            )
            return

        try:
            result = self.exporter.export_pack(
                frames=self.iter_active_frames_for_export(),
                out_root=out_root,
                pack_name=pack_name,
                anim_base=anim_base,
                create_zip=bool(self.create_zip.get()),
            )
        except Exception as exc:
            messagebox.showerror("Export failed", f"Could not export pack:\n{exc}")
            return

        lines = [
            "Built Momentum animation pack successfully.",
            "",
            f"Folder: {result.pack_dir}",
            f"Animation dir: {result.anim_dir}",
            f"Frames: {result.frame_count}",
            f"Threshold: {self._safe_int(self.threshold, 140)}",
            f"Contrast: {self._safe_float(self.contrast, 2.2):.1f}",
            f"Manifest entries: {result.manifest_count}",
        ]
        if result.zip_path:
            lines.append(f"ZIP: {result.zip_path}")
        lines.extend(
            [
                "",
                "Install path on Flipper:",
                f"/ext/asset_packs/{pack_name}/Anims/...",
                "",
                "Then pick the pack in Momentum Settings.",
            ]
        )
        self.set_output_text("\n".join(lines))
        messagebox.showinfo("Done", "Momentum pack created.")

    def on_close(self) -> None:
        self.playing = False
        self._cancel_playback()
        self._cancel_queued_refreshes()

        # Remove all variable traces so their callbacks (which hold a ref to
        # self) are released before the widget tree is torn down.
        for var, mode, tid in self._trace_ids:
            try:
                var.trace_remove(mode, tid)
            except Exception:
                pass
        self._trace_ids.clear()

        self.all_frames = []
        self.active_indices = []
        self._indices_clean = True
        self.preview_image = None
        try:
            self.image_processor.clear_cache()
        except Exception:
            pass
        self.root.destroy()
