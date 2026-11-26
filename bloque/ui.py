from __future__ import annotations

import ctypes
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from functools import lru_cache
from pathlib import Path
from tkinter import filedialog

from PIL import Image, ImageDraw, ImageFilter

from . import __version__, java, paths

BG = "#100f0d"
PANEL = "#191713"
CARD = "#221f19"
CARD_RGB = (34, 31, 25, 255)
INPUT = "#28241d"
INPUT_DISABLED = "#1d1a15"
BORDER = "#3a352b"
BORDER_SOFT = "#2a261f"
TEXT = "#f1ead9"
MUTED = "#a19785"
FAINT = "#6e6658"
ACCENT = "#e2b25a"
ACCENT_HOVER = "#f0c877"
ACCENT_DOWN = "#bd8f3c"
ACCENT_INK = "#241a06"
GRASS = "#95c46a"
DANGER = "#d76f5c"
WARN = "#d9a24e"
LOG_BG = "#131110"

FONT = "Segoe UI"
DISPLAY = "Bahnschrift SemiBold"
MONO = "Consolas"


def tracked(text: str) -> str:
    return " ".join(text)


def apply_theme(root: tk.Tk) -> None:
    root.option_add("*Font", (FONT, 10))
    root.option_add("*tearOff", False)
    root.option_add("*Listbox.background", PANEL)
    root.option_add("*Listbox.foreground", TEXT)
    root.option_add("*Listbox.selectBackground", ACCENT)
    root.option_add("*Listbox.selectForeground", ACCENT_INK)
    root.option_add("*Menu.background", PANEL)
    root.option_add("*Menu.foreground", TEXT)


def work_area_rect() -> tuple[int, int, int, int]:
    try:
        class Rect(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        rect = Rect()
        if ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0):
            return (rect.left, rect.top,
                    rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        pass
    return 0, 0, 1280, 720


def work_area() -> tuple[int, int]:
    _, _, width, height = work_area_rect()
    return width, height


def _parent_bg(parent) -> str:
    try:
        return parent.cget("bg")
    except (tk.TclError, AttributeError):
        return BG


def label(parent, text="", size=10, color=TEXT, weight=None, wrap=0,
          justify="left", anchor="w", bg=None, font=None, width=None):
    if font is None:
        font = (FONT, size, weight) if weight else (FONT, size)
    return tk.Label(parent, text=text, bg=bg or _parent_bg(parent), fg=color,
                    font=font, wraplength=wrap, justify=justify, anchor=anchor,
                    width=width)


def divider(parent, top: int = 0, bottom: int = 0):
    line = tk.Frame(parent, bg=BORDER_SOFT, height=1)
    line.pack(fill="x", pady=(top, bottom))
    return line


def section(parent, text: str) -> tk.Canvas:
    canvas = tk.Canvas(parent, bg=_parent_bg(parent), height=18,
                       highlightthickness=0, bd=0, width=1)
    font = (DISPLAY, 8)
    measure = tkfont.Font(parent, font=font)

    def draw(event=None):
        canvas.delete("all")
        width = canvas.winfo_width()
        title = tracked(text.upper())
        canvas.create_text(0, 9, text=title, fill=FAINT, font=font, anchor="w")
        start = measure.measure(title) + 12
        if width > start + 8:
            canvas.create_line(start, 9, width, 9, fill=BORDER_SOFT)

    canvas.bind("<Configure>", draw)
    return canvas


def enable_dark_titlebar(window) -> None:
    def colorref(hex_color: str) -> int:
        value = hex_color.lstrip("#")
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
        return red | (green << 8) | (blue << 16)

    def apply():
        try:
            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
                return
            for attr in (20, 19):
                flag = ctypes.c_int(2)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(flag), ctypes.sizeof(flag)) == 0:
                    break
            for attr, color in ((35, BG), (34, BORDER), (36, TEXT)):
                value = ctypes.c_int(colorref(color))
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    apply()
    try:
        window.after(240, apply)
        window.after(900, apply)
        window.bind("<Map>", lambda _event: apply(), add="+")
    except tk.TclError:
        pass


def set_app_icon(window) -> None:
    icon = Path(__file__).with_name("assets") / "icon.ico"
    try:
        window.iconbitmap(default=str(icon))
    except tk.TclError:
        pass


def draw_cube(canvas: tk.Canvas, x: float, y: float, size: float) -> None:
    top = (x + size * 0.5, y)
    right_top = (x + size, y + size * 0.28)
    center = (x + size * 0.5, y + size * 0.56)
    left_top = (x, y + size * 0.28)
    left_bottom = (x, y + size * 0.74)
    center_bottom = (x + size * 0.5, y + size)
    right_bottom = (x + size, y + size * 0.74)

    canvas.create_polygon(top, right_top, center, left_top,
                          fill="#a6cf72", outline="")
    canvas.create_polygon(left_top, center, center_bottom, left_bottom,
                          fill="#7a5a3c", outline="")
    canvas.create_polygon(right_top, center, center_bottom, right_bottom,
                          fill="#5b4229", outline="")

    unit = size * 0.11
    for px, py in ((0.34, 0.18), (0.62, 0.26), (0.46, 0.42)):
        cx = x + size * px
        cy = y + size * py
        canvas.create_polygon(
            (cx, cy - unit * 0.5), (cx + unit, cy),
            (cx, cy + unit * 0.5), (cx - unit, cy),
            fill="#8fba5e", outline="")
    for px, py in ((0.32, 0.5), (0.57, 0.62)):
        canvas.create_rectangle(x + size * px, y + size * py,
                                x + size * px + unit * 0.9,
                                y + size * py + unit * 0.9,
                                fill="#684a30", outline="")
    for px, py in ((0.74, 0.48), (0.82, 0.64)):
        canvas.create_rectangle(x + size * px, y + size * py,
                                x + size * px + unit * 0.9,
                                y + size * py + unit * 0.9,
                                fill="#4d3722", outline="")


class Button(tk.Canvas):
    def __init__(self, parent, text: str = "", command=None, kind: str = "secondary",
                 width: int | None = None, height: int = 36, font=None):
        self._text = text
        self._command = command
        self._kind = kind
        self._state = "normal"
        self._hover = False
        self._pressed = False
        self._font = font or ((DISPLAY, 13)
                              if kind in ("primary", "destructive") else (FONT, 9))
        super().__init__(parent, width=width or 1, height=height,
                         bg=_parent_bg(parent), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda _event: self._draw())

    def configure(self, cnf=None, **kw):
        redraw = False
        if "text" in kw:
            self._text = kw.pop("text")
            redraw = True
        if "state" in kw:
            self._state = kw.pop("state")
            self.configure(cursor="hand2" if self._state == "normal" else "arrow")
            redraw = True
        if "command" in kw:
            self._command = kw.pop("command")
        if "kind" in kw:
            self._kind = kw.pop("kind")
            redraw = True
        if cnf:
            kw.update(cnf)
        if kw:
            super().configure(**kw)
        if redraw:
            self._draw()

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event=None) -> None:
        if self._state != "normal":
            return
        self._pressed = True
        self._draw()

    def _on_release(self, event=None) -> None:
        if self._state != "normal":
            return
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and event is not None and 0 <= event.x <= self.winfo_width() \
                and 0 <= event.y <= self.winfo_height() and self._command:
            self._command()

    def _geometry(self):
        width = max(self.winfo_width(), 2)
        height = max(self.winfo_height(), 2)
        kind = self._kind
        if self._state != "normal":
            if kind in ("primary", "destructive"):
                return width, height, INPUT_DISABLED, BORDER_SOFT, FAINT, False
            return width, height, _parent_bg(self), "", FAINT, False
        if kind == "primary":
            if self._pressed:
                face = ACCENT_DOWN
            elif self._hover:
                face = ACCENT_HOVER
            else:
                face = ACCENT
            return width, height, face, "", ACCENT_INK, True
        if kind == "destructive":
            face = "#b4553f" if self._pressed else ("#e58976" if self._hover else DANGER)
            return width, height, face, "", "#1b0b07", True
        if kind == "danger":
            face = "#2a1714" if self._pressed else ("#251512" if self._hover else _parent_bg(self))
            return width, height, face, "", DANGER, False
        if kind == "quiet":
            face = "#221f18" if self._hover else _parent_bg(self)
            return width, height, face, "", TEXT if self._hover else MUTED, False
        face = "#1f1c16" if self._pressed else (INPUT if not self._hover else "#2f2a21")
        return width, height, face, BORDER if not self._hover else "#4b4435", TEXT, False

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        width, height, face, border, ink, primary = self._geometry()
        if primary:
            self.create_rectangle(0, 3, width, height - 1, fill="#080705", outline="")
            offset = 2 if self._pressed else 0
            self.create_rectangle(0, offset, width - 1, height - 4 + offset,
                                  fill=face, outline="")
            center_y = (height - 4 + offset) / 2
        else:
            self.create_rectangle(0, 0, width - 1, height - 1, fill=face,
                                  outline=border or "")
            center_y = height / 2
        self.create_text(width // 2, center_y, text=self._text, fill=ink,
                         font=self._font)


class Input(tk.Frame):
    def __init__(self, parent, textvariable=None, width: int | None = None,
                 font=None, justify="left", show=None):
        bg = _parent_bg(parent)
        super().__init__(parent, bg=bg, highlightbackground=BORDER,
                         highlightcolor=ACCENT, highlightthickness=1, bd=0)
        self.entry = tk.Entry(self, textvariable=textvariable, bg=INPUT, fg=TEXT,
                              insertbackground=TEXT, relief="flat", bd=0,
                              font=font or (FONT, 10), justify=justify,
                              show=show or "", highlightthickness=0,
                              selectbackground="#4b3a1a",
                              selectforeground=TEXT, width=width or 20)
        self.entry.pack(fill="both", expand=True, padx=8, pady=6)
        self.entry.bind("<FocusIn>", lambda _event: self.configure(
            highlightbackground=ACCENT))
        self.entry.bind("<FocusOut>", lambda _event: self.configure(
            highlightbackground=BORDER))

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            state = kw.pop("state")
            self.entry.configure(state=state)
            if state == "disabled":
                self.entry.configure(bg=INPUT_DISABLED, fg=FAINT)
                self.configure(highlightbackground=BORDER_SOFT)
            else:
                self.entry.configure(bg=INPUT, fg=TEXT)
                self.configure(highlightbackground=BORDER)
        if "textvariable" in kw:
            self.entry.configure(textvariable=kw.pop("textvariable"))
        if cnf:
            kw.update(cnf)
        if kw:
            super().configure(**kw)

    def get(self) -> str:
        return self.entry.get()

    def set(self, value: str) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, value)

    def focus_set(self) -> None:
        self.entry.focus_set()


class Select(tk.Canvas):
    def __init__(self, parent, values=(), textvariable=None, height: int = 40,
                 width: int | None = None, placeholder: str = "", big: bool = False):
        self._values = list(values)
        self._placeholder = placeholder
        self._variable = textvariable or tk.StringVar()
        self._trace = self._variable.trace_add("write", lambda *_: self._draw())
        self._state = "readonly"
        self._hover = False
        self._popup = None
        self._outside_bind = None
        self._big = big
        super().__init__(parent, width=width or 1, height=height,
                         bg=_parent_bg(parent), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<Button-1>", self._on_click)

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def configure(self, cnf=None, **kw):
        if "values" in kw:
            self._values = list(kw.pop("values"))
            self._draw()
        if "state" in kw:
            state = kw.pop("state")
            self._state = "disabled" if state == "disabled" else "readonly"
            self.configure(cursor="hand2" if self._state != "disabled" else "arrow")
            self._draw()
        if cnf:
            kw.update(cnf)
        if kw:
            super().configure(**kw)

    def get(self) -> str:
        return self._variable.get()

    def set(self, value: str) -> None:
        self._variable.set(value)

    def current(self, index: int) -> None:
        if 0 <= index < len(self._values):
            self._variable.set(self._values[index])

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        width = max(self.winfo_width(), 2)
        height = max(self.winfo_height(), 2)
        disabled = self._state == "disabled"
        face = INPUT_DISABLED if disabled else (INPUT if not self._hover else "#2f2a21")
        border = BORDER_SOFT if disabled else (BORDER if not self._hover else "#4b4435")
        self.create_rectangle(0, 0, width - 1, height - 1, fill=face, outline=border)
        value = self._variable.get()
        color = FAINT if disabled else (TEXT if value else FAINT)
        font = (FONT, 12) if self._big else (FONT, 10)
        self.create_text(12, height // 2, text=value or self._placeholder,
                         fill=color, font=font, anchor="w")
        arrow = MUTED if not disabled else FAINT
        x = width - 19
        y = height // 2 - 2
        self.create_line(x, y, x + 5, y + 5, fill=arrow, width=1)
        self.create_line(x + 5, y + 5, x + 10, y, fill=arrow, width=1)

    def _on_click(self, _event=None) -> None:
        if self._state == "disabled":
            return
        if self._popup is not None and self._popup.winfo_exists():
            self._close_popup()
            return
        self._open_popup()

    def _open_popup(self) -> None:
        if not self._values:
            return
        top = self.winfo_toplevel()
        search = len(self._values) > 12
        rows = min(11, len(self._values))
        popup = tk.Frame(top, bg=BORDER, bd=0)
        inner = tk.Frame(popup, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        entry = None
        if search:
            search_box = tk.Frame(inner, bg=PANEL)
            search_box.pack(fill="x", padx=8, pady=(8, 4))
            entry = tk.Entry(search_box, bg=INPUT, fg=FAINT, insertbackground=TEXT,
                             relief="flat", bd=0, font=(FONT, 9),
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT)
            entry.pack(fill="x", ipady=5, padx=1)
            entry.insert(0, "Buscar versión")
            entry.placeholder = "Buscar versión"

            def focus_in(_event):
                if entry.get() == entry.placeholder:
                    entry.delete(0, "end")
                    entry.configure(fg=TEXT)

            def focus_out(_event):
                if not entry.get():
                    entry.insert(0, entry.placeholder)
                    entry.configure(fg=FAINT)

            entry.bind("<FocusIn>", focus_in)
            entry.bind("<FocusOut>", focus_out)

        list_wrap = tk.Frame(inner, bg=PANEL)
        list_wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8) if search else (8, 8))
        scroll = ThinScroll(list_wrap, command=None, bg=PANEL, width=7)
        box = tk.Listbox(list_wrap, bg=PANEL, fg=TEXT, selectbackground=ACCENT,
                         selectforeground=ACCENT_INK, borderwidth=0,
                         highlightthickness=0, activestyle="none", relief="flat",
                         font=(FONT, 9), height=rows, exportselection=False)
        scroll.attach(box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(4, 0))
        box.pack(side="left", fill="both", expand=True)

        filtered = list(self._values)

        def fill(values):
            nonlocal filtered
            filtered = list(values)
            box.delete(0, "end")
            for value in filtered:
                box.insert("end", value)
            if self._variable.get() in filtered:
                index = filtered.index(self._variable.get())
                box.selection_set(index)
                box.see(index)

        fill(filtered)

        def choose(_event=None):
            selection = box.curselection()
            if not selection:
                return
            value = filtered[selection[0]]
            self._close_popup()
            self._variable.set(value)
            self.event_generate("<<ComboboxSelected>>")

        box.bind("<ButtonRelease-1>", choose)
        box.bind("<Return>", choose)
        box.bind("<Escape>", lambda _event: self._close_popup())
        box.bind("<MouseWheel>", lambda event: box.yview_scroll(
            int(-event.delta / 120), "units"))

        if entry is not None:
            def filter_values(*_args):
                needle = entry.get()
                if needle == entry.placeholder:
                    needle = ""
                needle = needle.strip().lower()
                fill([value for value in self._values if needle in value.lower()])
            entry.bind("<KeyRelease>", filter_values)
            entry.bind("<Return>", lambda _event: (
                box.selection_set(0), choose()))
            entry.bind("<Escape>", lambda _event: self._close_popup())
            entry.bind("<Down>", lambda _event: (box.focus_set(), "break")[1])

        popup.update_idletasks()
        width = max(self.winfo_width(), 180)
        screen_w = top.winfo_screenwidth()
        screen_h = top.winfo_screenheight()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        height = popup.winfo_reqheight()
        if y + height > screen_h - 8:
            y = self.winfo_rooty() - height - 2
        x = max(4, min(x, screen_w - width - 4))
        popup.place(x=x - top.winfo_rootx(), y=y - top.winfo_rooty(), width=width)
        popup.lift()
        self._popup = popup
        self._outside_bind = top.bind("<Button-1>", self._outside_click, add="+")
        box.focus_set()

    def _outside_click(self, event) -> None:
        popup = self._popup
        if popup is None or not popup.winfo_exists():
            return
        widget = event.widget
        while widget is not None:
            if widget is popup or widget is self:
                return
            widget = getattr(widget, "master", None)
        self._close_popup()

    def _close_popup(self) -> None:
        popup = self._popup
        self._popup = None
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass
        if self._outside_bind is not None:
            try:
                self.winfo_toplevel().unbind("<Button-1>", self._outside_bind)
            except tk.TclError:
                pass
            self._outside_bind = None


class Slider(tk.Canvas):
    def __init__(self, parent, from_: float = 0, to: float = 100,
                 variable=None, command=None, step: float = 0, height: int = 30):
        self._from = from_
        self._to = to
        self._variable = variable or tk.DoubleVar()
        self._command = command
        self._step = step
        self._hover = False
        self._trace = self._variable.trace_add("write", lambda *_: self._draw())
        super().__init__(parent, height=height, bg=_parent_bg(parent),
                         highlightthickness=0, bd=0, cursor="hand2", width=1)
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._on_drag)
        self.bind("<B1-Motion>", self._on_drag)

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def _ratio(self) -> float:
        try:
            value = float(self._variable.get())
        except (TypeError, ValueError, tk.TclError):
            value = self._from
        span = self._to - self._from or 1
        return min(max((value - self._from) / span, 0.0), 1.0)

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        width = max(self.winfo_width(), 2)
        height = max(self.winfo_height(), 2)
        pad = 5
        middle = height // 2
        left = pad
        right = width - pad
        self.create_line(left, middle, right, middle, fill=BORDER_SOFT, width=3)
        thumb_x = left + (right - left) * self._ratio()
        self.create_line(left, middle, thumb_x, middle, fill=ACCENT, width=3)
        for step in range(1, 8):
            x = left + (right - left) * step / 8
            self.create_line(x, middle + 6, x, middle + 9, fill=BORDER_SOFT)
        fill = ACCENT_HOVER if self._hover else ACCENT
        self.create_rectangle(thumb_x - 5, middle - 9, thumb_x + 5, middle + 9,
                              fill=fill, outline="#f6e0ad")

    def _on_drag(self, event) -> None:
        width = max(self.winfo_width(), 2)
        pad = 5
        ratio = min(max((event.x - pad) / max(width - 2 * pad, 1), 0.0), 1.0)
        value = self._from + (self._to - self._from) * ratio
        if self._step:
            value = round(value / self._step) * self._step
        if isinstance(self._variable, tk.IntVar):
            self._variable.set(int(round(value)))
        else:
            self._variable.set(round(value))
        if self._command:
            self._command(str(value))


class Progress(tk.Canvas):
    def __init__(self, parent, maximum: float = 100, value: float = 0,
                 height: int = 8):
        self._maximum = maximum
        self._value = value
        super().__init__(parent, height=height, bg=_parent_bg(parent),
                         highlightthickness=0, bd=0, width=1)
        self.bind("<Configure>", lambda _event: self._draw())

    def __setitem__(self, key, value):
        if key == "value":
            self._value = float(value)
            self._draw()
        elif key == "maximum":
            self._maximum = float(value) or 1
            self._draw()
        else:
            tk.Canvas.__setitem__(self, key, value)

    def __getitem__(self, key):
        if key == "value":
            return self._value
        if key == "maximum":
            return self._maximum
        return tk.Canvas.__getitem__(self, key)

    def configure(self, cnf=None, **kw):
        if "value" in kw:
            self._value = float(kw.pop("value"))
        if "maximum" in kw:
            self._maximum = float(kw.pop("maximum"))
        if cnf:
            kw.update(cnf)
        if kw:
            super().configure(**kw)
        self._draw()

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        width = max(self.winfo_width(), 2)
        height = max(self.winfo_height(), 2)
        ratio = 0.0 if not self._maximum else self._value / self._maximum
        ratio = min(max(ratio, 0.0), 1.0)
        gap = 2
        segments = max(1, (width + gap) // 8)
        seg_width = max((width - gap * (segments - 1)) / segments, 1)
        filled = ratio * segments
        for index in range(segments):
            x = index * (seg_width + gap)
            color = ACCENT if index + 0.5 <= filled else BORDER_SOFT
            self.create_rectangle(x, 0, x + seg_width, height - 1,
                                  fill=color, outline="")


class Check(tk.Canvas):
    def __init__(self, parent, text: str, variable, command=None, bg=None):
        self._variable = variable
        self._command = command
        font = (FONT, 9)
        measure = tkfont.Font(parent, font=font)
        self._text = text
        width = measure.measure(text) + 28
        self._hover = False
        super().__init__(parent, width=width, height=24, bg=bg or _parent_bg(parent),
                         highlightthickness=0, bd=0, cursor="hand2")
        self._trace = self._variable.trace_add("write", lambda *_: self._draw())
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self._draw()

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def _toggle(self, _event=None) -> None:
        self._variable.set(not self._variable.get())
        if self._command:
            self._command()

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        checked = bool(self._variable.get())
        height = max(self.winfo_height(), 2)
        top = height // 2 - 8
        border = ACCENT if checked else ("#5c5446" if self._hover else "#4a4336")
        self.create_rectangle(0, top, 16, top + 16,
                              fill=ACCENT if checked else INPUT, outline=border)
        if checked:
            self.create_line(4, top + 8, 7, top + 12, fill=ACCENT_INK, width=2)
            self.create_line(7, top + 12, 13, top + 4, fill=ACCENT_INK, width=2)
        self.create_text(24, height // 2, text=self._text,
                         fill=TEXT if self._hover or checked else MUTED,
                         font=(FONT, 9), anchor="w")


class Radio(tk.Canvas):
    def __init__(self, parent, text: str, variable, value, command=None, bg=None):
        self._variable = variable
        self._value = value
        self._command = command
        measure = tkfont.Font(parent, font=(FONT, 9))
        self._text = text
        width = measure.measure(text) + 28
        self._hover = False
        super().__init__(parent, width=width, height=24, bg=bg or _parent_bg(parent),
                         highlightthickness=0, bd=0, cursor="hand2")
        self._trace = self._variable.trace_add("write", lambda *_: self._draw())
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self._draw()

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def _toggle(self, _event=None) -> None:
        self._variable.set(self._value)
        if self._command:
            self._command()

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        selected = self._variable.get() == self._value
        height = max(self.winfo_height(), 2)
        top = height // 2 - 8
        border = ACCENT if selected else ("#5c5446" if self._hover else "#4a4336")
        self.create_rectangle(0, top, 16, top + 16, fill=INPUT, outline=border)
        if selected:
            self.create_rectangle(4, top + 4, 12, top + 12, fill=ACCENT, outline="")
        self.create_text(24, height // 2, text=self._text,
                         fill=TEXT if (selected or self._hover) else MUTED,
                         font=(FONT, 9), anchor="w")


class ThinScroll(tk.Canvas):
    def __init__(self, parent, command=None, bg=None, width: int = 8):
        super().__init__(parent, width=width, height=1,
                         bg=bg or _parent_bg(parent),
                         highlightthickness=0, bd=0)
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._hover = False
        self._drag = None
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda _event: setattr(self, "_drag", None))

    def attach(self, command) -> None:
        self._command = command

    def set(self, first, last) -> None:
        self._first = float(first)
        self._last = float(last)
        self._draw()

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def _geometry(self):
        height = max(self.winfo_height(), 2)
        if self._last - self._first >= 0.999:
            return height, 0, height
        top = self._first * height
        bottom = self._last * height
        if bottom - top < 24:
            extra = (24 - (bottom - top)) / 2
            top -= extra
            bottom += extra
        return height, max(0, top), min(height, bottom)

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        width = max(self.winfo_width(), 2)
        height, top, bottom = self._geometry()
        if self._last - self._first >= 0.999 or bottom - top < 0.5:
            return
        color = "#5c5444" if self._hover else "#4a4436"
        self.create_rectangle(1, top, width - 1, bottom, fill=color, outline="")

    def _on_press(self, event) -> None:
        height, top, bottom = self._geometry()
        if top <= event.y <= bottom:
            self._drag = event.y - top
            return
        self._drag = (bottom - top) / 2
        if self._command:
            direction = -1 if event.y < top else 1
            self._command("scroll", direction, "pages")

    def _on_drag(self, event) -> None:
        height = max(self.winfo_height(), 2)
        if self._drag is None or not self._command:
            return
        fraction = max(0.0, min(1.0, (event.y - self._drag) / height))
        self._command("moveto", fraction)


class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg=None):
        bg = bg or _parent_bg(parent)
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, width=1)
        self.bar = ThinScroll(self, command=self.canvas.yview, bg=bg)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y", padx=(10, 0))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.content,
                                                 anchor="nw")
        self.content.bind("<Configure>", lambda _event: self._sync())
        self.canvas.bind("<Configure>", self._on_configure)

    def _sync(self) -> None:
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)

    def _on_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync()

    def scroll(self, event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if isinstance(widget, (tk.Listbox, tk.Text)):
                return
            widget = getattr(widget, "master", None)
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


@lru_cache(maxsize=10)
def _stage_background(width: int, height: int) -> Image.Image:
    stage = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(stage)
    top = (39, 35, 27)
    bottom = (22, 20, 16)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color + (255,))

    grid = Image.new("RGBA", (width, height))
    grid_draw = ImageDraw.Draw(grid)
    for x in range(0, width, 24):
        grid_draw.line([(x, 0), (x, height)], fill=(255, 240, 210, 6))
    for y in range(0, height, 24):
        grid_draw.line([(0, y), (width, y)], fill=(255, 240, 210, 6))
    stage.alpha_composite(grid)

    glow = Image.new("RGBA", (width, height))
    glow_draw = ImageDraw.Draw(glow)
    cx = width // 2
    cy = height - 96
    for radius in range(120, 0, -6):
        alpha = int(30 * (1 - radius / 120) ** 1.4) + 1
        glow_draw.ellipse([cx - radius, cy - radius * 0.85,
                           cx + radius, cy + radius * 0.85],
                          fill=(226, 178, 90, alpha))
    stage.alpha_composite(glow)

    shadow = Image.new("RGBA", (width, height))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse([cx - 62, height - 42, cx + 62, height - 18],
                        fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    stage.alpha_composite(shadow)

    stage.alpha_composite(_corner_marks(width, height))
    draw = ImageDraw.Draw(stage)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(58, 53, 43, 255))
    return stage


def _corner_marks(width: int, height: int) -> Image.Image:
    marks = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(marks)
    color = (241, 234, 217, 46)
    inset = 7
    length = 9
    for x, y, dx, dy in ((inset, inset, 1, 1),
                         (width - inset - 1, inset, -1, 1),
                         (inset, height - inset - 1, 1, -1),
                         (width - inset - 1, height - inset - 1, -1, -1)):
        draw.line([(x, y), (x + dx * length, y)], fill=color)
        draw.line([(x, y), (x, y + dy * length)], fill=color)
    return marks


def skin_stage(body: Image.Image, width: int, height: int) -> Image.Image:
    stage = _stage_background(width, height).copy()
    if body.width > width - 16:
        scale = (width - 16) / body.width
        body = body.resize((int(body.width * scale), int(body.height * scale)),
                           Image.NEAREST)
    x = (width - body.width) // 2
    y = height - 16 - body.height
    stage.alpha_composite(body, (x, y))
    return stage


class MessageDialog(tk.Toplevel):
    def __init__(self, parent, title: str, message: str, *, initial: str | None = None,
                 ok_text: str = "Aceptar", cancel_text: str | None = None,
                 danger: bool = False, tone: str = "info"):
        super().__init__(parent)
        self.result = None
        self._variable = tk.StringVar(value=initial or "")
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=26, pady=22)
        colors = {"info": TEXT, "warn": WARN, "error": DANGER}
        tk.Label(body, text=title, bg=BG, fg=colors.get(tone, TEXT),
                 font=(DISPLAY, 15), anchor="w").pack(fill="x")
        tk.Frame(body, bg=BORDER_SOFT, height=1).pack(fill="x", pady=(9, 13))
        tk.Label(body, text=message, bg=BG, fg=MUTED, font=(FONT, 9),
                 wraplength=396, justify="left", anchor="w").pack(fill="x")

        self.input = None
        if initial is not None:
            self.input = Input(body, textvariable=self._variable)
            self.input.pack(fill="x", pady=(13, 0))

        buttons = tk.Frame(body, bg=BG)
        buttons.pack(fill="x", pady=(20, 0))
        accept = Button(buttons, ok_text,
                        kind="destructive" if danger else "primary",
                        command=self._accept, width=132, height=36,
                        font=(DISPLAY, 10))
        accept.pack(side="right")
        if cancel_text:
            Button(buttons, cancel_text, command=self._cancel, width=112,
                   height=36).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._accept())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        width = 470
        height = max(self.winfo_reqheight(), 150)
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        set_app_icon(self)
        self.after(60, lambda: enable_dark_titlebar(self))
        if self.input is not None:
            self.after(80, self._focus_input)
        else:
            accept.focus_set()
        self.grab_set()
        self.wait_window()

    def _focus_input(self) -> None:
        if self.input is None or not self.input.winfo_exists():
            return
        self.input.focus_set()
        self.input.entry.select_range(0, "end")

    def _accept(self) -> None:
        self.result = self._variable.get() if self.input is not None else True
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def ask_text(parent, title: str, message: str, initial: str = "") -> str | None:
    dialog = MessageDialog(parent, title, message, initial=initial,
                           cancel_text="Cancelar")
    value = (dialog.result or "").strip()
    return value or None


def ask_confirm(parent, title: str, message: str, ok_text: str = "Continuar",
                danger: bool = True) -> bool:
    dialog = MessageDialog(parent, title, message, ok_text=ok_text,
                           cancel_text="Cancelar", danger=danger)
    return dialog.result is True


def show_info(parent, title: str, message: str) -> None:
    MessageDialog(parent, title, message)


def show_warning(parent, title: str, message: str) -> None:
    MessageDialog(parent, title, message, tone="warn")


def show_error(parent, title: str, message: str) -> None:
    MessageDialog(parent, title, message, tone="error", ok_text="Entendido")


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.settings = dict(app.settings)
        self._queue: queue.Queue = queue.Queue()
        self._installing = False
        self._java_cells: dict[int, tuple[tk.Canvas, tk.Label]] = {}

        self.title("Ajustes · Blockys")
        area_x, area_y, area_w, area_h = work_area_rect()
        width = min(700, area_w - 60)
        height = min(700, area_h - 70)
        self.geometry(
            f"{width}x{height}"
            f"+{area_x + (area_w - width) // 2}"
            f"+{area_y + max(0, (area_h - height - 40) // 2)}")
        self.minsize(min(660, area_w - 80), min(520, height))
        self.configure(bg=BG)
        self.transient(app)
        self.grab_set()
        self._poll_job = None

        self.client_var = tk.StringVar(value=self.settings.get("client_id", ""))
        self.java_mode = tk.StringVar(value=self.settings.get("java_mode", "temurin"))
        self.java_path_var = tk.StringVar(value=self.settings.get("java_path", ""))
        self.game_dir_var = tk.StringVar(value=self.settings.get("game_dir", ""))
        self.copy_var = tk.BooleanVar(value=bool(self.settings.get("copy_skin_mod", True)))
        self.status_var = tk.StringVar(value="")

        self._build()
        self._refresh_java_status()
        self._poll_job = self.after(100, self._poll)
        self.bind("<MouseWheel>", self._on_wheel)
        set_app_icon(self)
        self.after(80, lambda: enable_dark_titlebar(self))

    def _on_wheel(self, event) -> None:
        self._scroll.scroll(event)

    def destroy(self) -> None:
        if getattr(self.app, "_settings_window", None) is self:
            self.app._settings_window = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        super().destroy()

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 14))
        label(header, "Ajustes", size=22, color=TEXT, font=(DISPLAY, 22)).pack(
            side="left", anchor="s")
        label(header, f"v{__version__}", size=9,
              color=FAINT, font=(MONO, 9)).pack(side="right", anchor="s")
        divider(self, top=0, bottom=0)

        footer = tk.Frame(self, bg=BG)
        footer.pack(side="bottom", fill="x", padx=28, pady=(12, 18))
        tk.Frame(footer, bg=BORDER_SOFT, height=1).pack(fill="x", pady=(0, 14))
        row = tk.Frame(footer, bg=BG)
        row.pack(fill="x")
        Button(row, "Guardar", kind="primary", command=self._save,
               width=150, height=38).pack(side="right")
        Button(row, "Cancelar", command=self.destroy, width=110,
               height=38).pack(side="right", padx=(0, 10))

        self._scroll = ScrollFrame(self, bg=BG)
        self._scroll.pack(fill="both", expand=True, padx=(28, 18), pady=(18, 0))
        content = self._scroll.content

        label(content, "Java, cuenta premium y carpeta del juego", size=9,
              color=MUTED).pack(fill="x", pady=(0, 4))

        self._build_microsoft(content)
        divider(content, top=22, bottom=20)
        self._build_java(content)
        divider(content, top=22, bottom=20)
        self._build_game(content)

        tk.Frame(content, bg=BG, height=10).pack(fill="x")

    def _build_microsoft(self, parent) -> None:
        section(parent, "Cuenta Microsoft").pack(fill="x")
        label(parent, "Client ID de Azure", size=9, color=TEXT).pack(
            fill="x", pady=(10, 5))
        Input(parent, textvariable=self.client_var).pack(fill="x")
        label(parent,
              "Solo se necesita para cuentas premium. Las cuentas offline "
              "funcionan sin esto.", size=8, color=MUTED, wrap=600).pack(
            fill="x", pady=(6, 0))

    def _build_java(self, parent) -> None:
        section(parent, "Java").pack(fill="x")
        Radio(parent, "Temurin automático (recomendado)", self.java_mode,
              "temurin", command=self._toggle_java_path,
              bg=BG).pack(anchor="w", pady=(9, 0))
        label(parent, "Descarga el runtime que pida cada versión de Minecraft.",
              size=8, color=MUTED).pack(fill="x", padx=(24, 0))
        Radio(parent, "Usar una ruta de Java personalizada", self.java_mode,
              "custom", command=self._toggle_java_path,
              bg=BG).pack(anchor="w", pady=(6, 6))

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=(24, 0))
        self.java_entry = Input(row, textvariable=self.java_path_var)
        self.java_entry.pack(side="left", fill="x", expand=True)
        Button(row, "Elegir", command=self._browse_java, width=88,
               height=36).pack(side="left", padx=(8, 0))
        label(parent,
              "Adoptium publica Temurin 8, 11 y 17 a 27. Las versiones 9, 10 "
              "y 12 a 16 no tienen JRE.", size=8, color=MUTED, wrap=600).pack(
            fill="x", padx=(24, 0), pady=(6, 0))

        runtimes = tk.Frame(parent, bg=BG)
        runtimes.pack(fill="x", padx=(24, 0), pady=(12, 0))
        for column in range(4):
            runtimes.grid_columnconfigure(column, weight=1, uniform="java")
        for index, major in enumerate(java.JAVA_MAJORS):
            cell = tk.Frame(runtimes, bg=BG)
            cell.grid(row=index // 4, column=index % 4, sticky="w",
                      padx=(0, 10), pady=2)
            dot = tk.Canvas(cell, width=8, height=8, bg=BG,
                            highlightthickness=0, bd=0)
            dot.create_rectangle(0, 0, 7, 7, fill=BORDER, outline="")
            dot.pack(side="left")
            label(cell, f"{major}", size=8, color=FAINT,
                  font=(MONO, 8)).pack(side="left", padx=(6, 6))
            value = label(cell, "...", size=8, color=MUTED, font=(MONO, 8))
            value.pack(side="left")
            self._java_cells[major] = (dot, value)

        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill="x", padx=(24, 0), pady=(12, 0))
        self.install_btn = Button(actions, "Instalar faltantes",
                                  command=self._install_missing, width=170,
                                  height=34)
        self.install_btn.pack(side="left")
        tk.Label(actions, textvariable=self.status_var, bg=BG, fg=MUTED,
                 font=(FONT, 8), anchor="w").pack(side="left", padx=(12, 0))
        self.progress = Progress(parent, maximum=100)
        self.progress.pack(fill="x", padx=(24, 0), pady=(10, 0))

    def _build_game(self, parent) -> None:
        section(parent, "Juego").pack(fill="x")
        label(parent, "Carpeta .minecraft (partidas, mods, recursos)", size=9,
              color=TEXT).pack(fill="x", pady=(10, 5))
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x")
        Input(row, textvariable=self.game_dir_var).pack(
            side="left", fill="x", expand=True)
        Button(row, "Elegir", command=self._browse_game, width=88,
               height=36).pack(side="left", padx=(8, 0))
        Check(parent, "Copiar skins a CustomSkinLoader al iniciar (skins offline)",
              self.copy_var, bg=BG).pack(anchor="w", pady=(12, 0))

    def _toggle_java_path(self) -> None:
        state = "normal" if self.java_mode.get() == "custom" else "disabled"
        self.java_entry.configure(state=state)

    def _browse_java(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Selecciona java.exe",
            filetypes=[("Java", "java.exe"), ("Todos", "*.*")])
        if path:
            self.java_path_var.set(path)
            self.java_mode.set("custom")
            self._toggle_java_path()

    def _browse_game(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Carpeta del juego")
        if path:
            self.game_dir_var.set(path)

    def _refresh_java_status(self) -> None:
        for dot, value in self._java_cells.values():
            value.configure(text="...", fg=MUTED)

        def work():
            statuses = {major: java.installed_runtime(major)
                        for major in java.JAVA_MAJORS}
            self._queue.put(("statuses", statuses))

        threading.Thread(target=work, daemon=True).start()

    def _apply_statuses(self, statuses: dict) -> None:
        for major, result in statuses.items():
            cell = self._java_cells.get(major)
            if not cell:
                continue
            dot, value = cell
            dot.delete("all")
            if result:
                dot.create_rectangle(0, 0, 7, 7, fill=GRASS, outline="")
                value.configure(text=str(result[1]), fg=TEXT)
            else:
                dot.create_rectangle(0, 0, 7, 7, fill=BORDER, outline="")
                value.configure(text="—", fg=FAINT)

    def _install_missing(self) -> None:
        if self._installing:
            return
        self._installing = True
        self.install_btn.configure(state="disabled")
        self.progress["maximum"] = 100
        self.progress["value"] = 0
        self.status_var.set("Comprobando runtimes...")

        def scan():
            try:
                majors = [major for major in java.JAVA_MAJORS
                          if not java.installed_runtime(major)]
            except Exception as exc:
                self._queue.put(("jscan", (None, str(exc))))
            else:
                self._queue.put(("jscan", (majors, None)))

        threading.Thread(target=scan, daemon=True).start()

    def _reset_install(self, message: str) -> None:
        self._installing = False
        self.install_btn.configure(state="normal")
        self.progress["value"] = 0
        self.status_var.set(message)

    def _start_install(self, majors: list[int]) -> None:
        self.progress["maximum"] = len(majors) * 100
        self.progress["value"] = 0
        self.status_var.set("Instalando runtimes...")

        def work():
            try:
                for index, major in enumerate(majors):
                    if java.installed_runtime(major):
                        self._queue.put(("installed", major))
                        self._queue.put(("jprogress", ((index + 1) * 100,
                                                       f"Temurin {major} ya instalado")))
                        continue

                    def on_progress(fraction, _text, index=index, major=major):
                        self._queue.put(("jprogress",
                                         (int((index + fraction) * 100),
                                          f"Temurin {major}")))

                    def on_status(text):
                        self._queue.put(("jstatus", text))

                    try:
                        java.ensure_temurin(major, on_progress=on_progress,
                                            on_status=on_status)
                    except Exception as exc:
                        self._queue.put(("jerror", f"Temurin {major}: {exc}"))
                    self._queue.put(("installed", major))
            except Exception as exc:
                self._queue.put(("jerror", str(exc)))
            finally:
                self._queue.put(("jdone", None))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "statuses":
                    self._apply_statuses(payload)
                elif kind == "jscan":
                    majors, error = payload
                    if error:
                        self._reset_install(f"Error al comprobar Java: {error}")
                    elif not majors:
                        self._reset_install(
                            "Todos los runtimes ya están instalados")
                    elif ask_confirm(
                            self, "Instalar Java Temurin",
                            "Se instalarán los runtimes que faltan: "
                            + ", ".join(str(major) for major in majors)
                            + ".\n\nPuede tardar varios minutos y ocupar "
                            "cientos de MB.",
                            ok_text="Instalar", danger=False):
                        self._start_install(majors)
                    else:
                        self._reset_install("Instalación cancelada")
                elif kind == "jprogress":
                    value, text = payload
                    self.progress["value"] = value
                    self.status_var.set(text)
                elif kind == "jstatus":
                    self.status_var.set(str(payload))
                elif kind == "installed":
                    cell = self._java_cells.get(payload)
                    if cell:
                        dot, value = cell
                        dot.delete("all")
                        dot.create_rectangle(0, 0, 7, 7, fill=GRASS, outline="")
                        value.configure(text="Instalado", fg=TEXT)
                elif kind == "jerror":
                    self.status_var.set(f"Error: {payload}")
                elif kind == "jdone":
                    self._installing = False
                    self.install_btn.configure(state="normal")
                    self.progress["value"] = 0
                    self._refresh_java_status()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._poll_job = self.after(120, self._poll)

    def _save(self) -> None:
        if self.java_mode.get() == "custom":
            java_path = self.java_path_var.get().strip()
            if not java_path or not Path(java_path).exists():
                show_warning(
                    self, "Java",
                    "Elige un java.exe válido o vuelve a Temurin automático.")
                return
        self.settings["client_id"] = self.client_var.get().strip()
        self.settings["java_mode"] = self.java_mode.get()
        self.settings["java_path"] = self.java_path_var.get().strip()
        game_dir = self.game_dir_var.get().strip()
        self.settings["game_dir"] = game_dir or str(paths.default_game_dir())
        self.settings["copy_skin_mod"] = bool(self.copy_var.get())
        self.app.apply_settings(self.settings)
        self.destroy()
