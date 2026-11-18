from __future__ import annotations

import os
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog

from . import diagnostics, instances, modrinth, servers
from .ui import (ACCENT, BG, BORDER, BORDER_SOFT, CARD, DANGER, DISPLAY,
                 FAINT, FONT, GRASS, INPUT, LOG_BG, MONO, MUTED, PANEL, TEXT,
                 WARN, Button, Check, Input, Progress, ScrollFrame, Select,
                 Slider, ThinScroll, divider, enable_dark_titlebar, label,
                 section, set_app_icon, show_error, show_info, show_warning,
                 work_area_rect)


LOADER_LABELS = ["Vanilla", "Fabric", "Quilt", "Forge", "NeoForge"]
LOADER_BY_LABEL = {label.lower(): key for key, label in instances.LOADERS.items()}
JAVA_LABELS = ["Global (Ajustes)", "Temurin automático", "Ruta personalizada"]
JAVA_MODES = {"Global (Ajustes)": "inherit",
              "Temurin automático": "temurin",
              "Ruta personalizada": "custom"}


def _open_path(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


def _size_text(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


CATEGORY_ORDER = ("all", "release", "snapshot", "old_beta", "old_alpha")
CATEGORY_LABELS = {"all": "Todas", "release": "Lanzamientos",
                   "snapshot": "Experimentales", "old_beta": "Betas",
                   "old_alpha": "Alphas"}
PRETTY_TYPE = {"release": "Lanzamiento", "snapshot": "Snapshot",
               "old_beta": "Beta clásica", "old_alpha": "Alpha clásica"}


def _int_or(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class VersionPicker(tk.Frame):
    def __init__(self, parent, manifest: dict | None, initial: str = "",
                 height: int = 38, on_select=None):
        super().__init__(parent, bg=parent.cget("bg"))
        self.manifest = manifest or {}
        self.initial = initial
        self.on_select = on_select
        self.category = "release"
        self._selected_id = initial
        self._map: dict[str, dict] = {}
        self._buttons: dict[str, Button] = {}
        self._extra: dict | None = None
        entries = self.manifest.get("versions") or []
        initial_entry = next((entry for entry in entries
                              if entry.get("id") == initial), None)
        if initial_entry:
            self.category = initial_entry.get("type") or "release"
        if initial and not initial_entry:
            self._extra = {"id": initial, "type": "actual",
                           "releaseTime": ""}
            self.category = "all"

        label(self, "Categoría", size=8, color=FAINT).pack(
            fill="x", pady=(0, 4))
        row = tk.Frame(self, bg=self.cget("bg"))
        row.pack(fill="x", pady=(0, 5))
        for column in range(3):
            row.grid_columnconfigure(column, weight=1, uniform="category")
        for index, key in enumerate(CATEGORY_ORDER):
            button = Button(row, CATEGORY_LABELS[key], kind="quiet",
                            command=lambda value=key: self._choose(value),
                            height=26, font=(FONT, 8))
            button.grid(row=index // 3, column=index % 3, sticky="ew",
                        padx=(0, 4) if index % 3 != 2 else (0, 0),
                        pady=(0, 4))
            self._buttons[key] = button

        self.combo = Select(self, values=[], height=height,
                            placeholder="Versión de Minecraft")
        self.combo.pack(fill="x")
        self.combo.bind("<<ComboboxSelected>>", self._picked)
        self.info = label(self, "", size=8, color=FAINT)
        self.info.pack(fill="x", pady=(4, 0))
        self._refresh()

    def _choose(self, category: str) -> None:
        self.category = category
        self._refresh()

    def _refresh(self) -> None:
        for key, button in self._buttons.items():
            count = sum(1 for entry in self._entries()
                        if key == "all" or entry.get("type") == key)
            button.configure(text=f"{CATEGORY_LABELS[key]} {count}".strip(),
                             kind="secondary" if key == self.category else "quiet")
        items = [entry for entry in self._entries()
                 if self.category == "all" or entry.get("type") == self.category]
        self._map = {}
        labels = []
        for entry in items:
            installed = (self._installed(entry["id"]))
            prefix = "● " if installed else ""
            pretty = PRETTY_TYPE.get(entry.get("type"), "Actual")
            text = f"{prefix}{entry['id']}   ·   {pretty}"
            labels.append(text)
            self._map[text] = entry
        self.combo.configure(values=labels)
        selected = next((text for text, entry in self._map.items()
                         if entry.get("id") == self._selected_id), None)
        if selected is None:
            selected = next((text for text, entry in self._map.items()
                             if entry.get("id") == self.initial), None)
        if selected is None and not self._selected_id and labels:
            selected = labels[0]
        if selected:
            self.combo.set(selected)
            self._selected_id = str(self._map[selected].get("id") or "")
        else:
            self.combo.set("")
        self.info.configure(text=f"{len(items)} versión(es) en esta categoría")

    def _entries(self) -> list[dict]:
        items = list(self.manifest.get("versions") or [])
        if self._extra is not None:
            items.insert(0, self._extra)
        return items

    @staticmethod
    def _installed(version_id: str) -> bool:
        from . import paths
        return (paths.VERSIONS_DIR / version_id
                / f"{version_id}.jar").is_file()

    def _picked(self, _event=None) -> None:
        self._selected_id = self.selected_id()
        if self.on_select:
            self.on_select(self.selected_id())

    def selected_id(self) -> str:
        entry = self._map.get(self.combo.get())
        if entry is not None:
            return str(entry.get("id") or "")
        return self._selected_id

    def set_version(self, version_id: str) -> None:
        self.initial = version_id
        self._selected_id = version_id
        entries = self.manifest.get("versions") or []
        entry = next((item for item in entries
                      if item.get("id") == version_id), None)
        self._extra = None
        if version_id and not entry:
            self._extra = {"id": version_id, "type": "actual",
                           "releaseTime": ""}
        if entry:
            self.category = entry.get("type") or "release"
        elif self._extra:
            self.category = "all"
        self._refresh()

    def set_manifest(self, manifest: dict | None) -> None:
        self.manifest = manifest or {}
        self._extra = None
        entries = self.manifest.get("versions") or []
        entry = next((item for item in entries
                      if item.get("id") == self.initial), None)
        if self.initial and not entry:
            self._extra = {"id": self.initial, "type": "actual",
                           "releaseTime": ""}
        if entry:
            self.category = entry.get("type") or "release"
        elif self._extra:
            self.category = "all"
        self._refresh()


class PromptDialog(tk.Toplevel):
    def __init__(self, parent, title: str, caption: str, initial: str = ""):
        super().__init__(parent)
        self.result: str | None = None
        self.title(f"{title} · Blockys")
        width, height = 430, 190
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._accept())

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=20)
        label(body, caption, size=9, color=TEXT).pack(fill="x")
        self.var = tk.StringVar(value=initial)
        entry = Input(body, textvariable=self.var)
        entry.pack(fill="x", pady=(6, 0))
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(16, 0))
        Button(row, "Cancelar", command=self._cancel, width=96,
               height=34).pack(side="right", padx=(8, 0))
        Button(row, "Aceptar", kind="primary", command=self._accept,
               width=110, height=34).pack(side="right")
        set_app_icon(self)
        self.after(80, lambda: enable_dark_titlebar(self))
        entry.focus_set()
        entry.select_range(0, "end")

    def _accept(self) -> None:
        self.result = self.var.get()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class ServerDialog(tk.Toplevel):
    def __init__(self, parent, title: str, name: str = "", ip: str = ""):
        super().__init__(parent)
        self.result: tuple[str, str] | None = None
        self.title(f"{title} · Blockys")
        width, height = 440, 320
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._accept())

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=22, pady=(18, 10))
        label(header, title.upper(), color=TEXT, font=(DISPLAY, 16)).pack(
            anchor="w")
        label(header, "Se guarda en servers.dat de esta instancia.", size=8,
              color=FAINT).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        body.pack(fill="both", expand=True, padx=22)
        inner = tk.Frame(body, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        label(inner, "Nombre", size=9, color=TEXT).pack(fill="x")
        self.name_var = tk.StringVar(value=name)
        Input(inner, textvariable=self.name_var).pack(fill="x", pady=(5, 0))
        label(inner, "Dirección", size=9, color=TEXT).pack(fill="x",
                                                          pady=(12, 0))
        self.ip_var = tk.StringVar(value=ip)
        Input(inner, textvariable=self.ip_var).pack(fill="x", pady=(5, 0))
        label(inner, "Ej: play.ejemplo.net o 192.168.1.20:25565", size=8,
              color=FAINT).pack(fill="x", pady=(4, 0))
        self.error_var = tk.StringVar()
        tk.Label(inner, textvariable=self.error_var, bg=PANEL, fg=DANGER,
                 font=(FONT, 8), anchor="w").pack(fill="x", pady=(8, 0))

        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=22, pady=14)
        Button(footer, "Cancelar", command=self._cancel, width=96,
               height=36).pack(side="right", padx=(8, 0))
        Button(footer, "Guardar", kind="primary", command=self._accept,
               width=120, height=36).pack(side="right")
        set_app_icon(self)
        self.after(80, lambda: enable_dark_titlebar(self))
        self.name_var.set(name)
        self.ip_var.set(ip)

    def _accept(self) -> None:
        name = " ".join(self.name_var.get().split())
        ip = self.ip_var.get().strip()
        if not name or not ip:
            self.error_var.set("Completá el nombre y la dirección.")
            return
        self.result = (name[:64], ip[:190])
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class InstancesDialog(tk.Toplevel):
    def __init__(self, app, select_id: str | None = None,
                 tab: str = "general", create: bool = False):
        super().__init__(app)
        self.app = app
        self.store = app.instance_store
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._current: dict | None = None
        self._initial_id = select_id
        self._tab = tab if tab in ("general", "mods", "packs", "shaders",
                                   "worlds", "servers", "shots", "logs",
                                   "console", "advanced") else "general"
        self._console_job = None
        self._tab_buttons: dict[str, Button] = {}
        self._modrinth_window = None
        self._poll_job = None
        self._create_on_open = create

        self.title("Instancias · Blockys")
        area_x, area_y, area_w, area_h = work_area_rect()
        width = min(1080, area_w - 60)
        height = min(720, area_h - 70)
        self.geometry(f"{width}x{height}"
                      f"+{area_x + (area_w - width) // 2}"
                      f"+{area_y + max(0, (area_h - height - 40) // 2)}")
        self.minsize(min(940, area_w - 80), min(560, height))
        self.configure(bg=BG)
        self.transient(app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<MouseWheel>", self._on_wheel)
        self._build()
        self._select_initial()
        self._poll_job = self.after(100, self._poll)
        set_app_icon(self)
        self.after(80, lambda: enable_dark_titlebar(self))
        if create:
            self.after(100, self._new_instance)

    def _on_wheel(self, event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                widget.scroll(event)
                return
            widget = getattr(widget, "master", None)

    def destroy(self) -> None:
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        if self._console_job is not None:
            try:
                self.after_cancel(self._console_job)
            except tk.TclError:
                pass
            self._console_job = None
        super().destroy()

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=26, pady=(18, 12))
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left", anchor="s")
        label(title_box, "INSTANCIAS", color=TEXT, font=(DISPLAY, 20)).pack(
            anchor="w")
        label(title_box, "Perfiles aislados, mods, packs y cargadores",
              size=8, color=FAINT).pack(anchor="w", pady=(1, 0))
        Button(header, "Cerrar", command=self._close, width=96,
               height=34).pack(side="right", anchor="s")

        footer = tk.Frame(self, bg=BG)
        footer.pack(side="bottom", fill="x", padx=26, pady=(10, 16))
        tk.Frame(footer, bg=BORDER_SOFT, height=1).pack(fill="x", pady=(0, 12))
        row = tk.Frame(footer, bg=BG)
        row.pack(fill="x")
        self.status_var = tk.StringVar(value="Elegí una instancia o creá una nueva")
        tk.Label(row, textvariable=self.status_var, bg=BG, fg=MUTED,
                 font=(FONT, 8), anchor="w").pack(side="left", padx=(0, 14),
                                                 fill="x", expand=True)
        self.progress = Progress(row, maximum=100, height=6)
        self.progress.configure(width=120)
        self.progress.pack(side="left", padx=(0, 12))
        Button(row, "Nueva", kind="primary", command=self._new_instance,
               width=110, height=36).pack(side="right")
        Button(row, "Importar", command=self._import_instance, width=100,
               height=36).pack(side="right", padx=(8, 0))
        self.export_btn = Button(row, "Exportar", command=self._export_instance,
                                 width=100, height=36)
        self.export_btn.pack(side="right", padx=(8, 0))
        self.delete_btn = Button(row, "Eliminar", kind="danger",
                                 command=self._delete_instance, width=92,
                                 height=36)
        self.delete_btn.pack(side="right", padx=(8, 0))
        self.duplicate_btn = Button(row, "Duplicar",
                                    command=self._duplicate_instance, width=94,
                                    height=36)
        self.duplicate_btn.pack(side="right", padx=(8, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=26)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        left = tk.Frame(body, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew")
        left.configure(width=310)
        left.grid_propagate(False)
        left_head = tk.Frame(left, bg=PANEL)
        left_head.pack(fill="x", padx=14, pady=(12, 8))
        section(left_head, "Tus instancias").pack(side="left", fill="x",
                                                  expand=True)
        self.count_label = label(left_head, "", size=8, color=FAINT)
        self.count_label.pack(side="right")
        self.list_scroll = ScrollFrame(left, bg=PANEL)
        self.list_scroll.pack(fill="both", expand=True, padx=(10, 4),
                              pady=(0, 10))

        right = tk.Frame(body, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1)
        right.grid(row=0, column=1, sticky="nsew", padx=(16, 0))
        right_head = tk.Frame(right, bg=PANEL)
        right_head.pack(fill="x", padx=20, pady=(14, 8))
        self.name_label = label(right_head, "Instancia", color=TEXT,
                                font=(DISPLAY, 20))
        self.name_label.pack(side="left")
        self.open_btn = Button(right_head, "Abrir carpeta", kind="quiet",
                               command=self._open_instance_folder, width=110,
                               height=28, font=(FONT, 8))
        self.open_btn.pack(side="right")
        self.play_btn = Button(right_head, "Jugar", kind="primary",
                               command=self._play_current, width=104,
                               height=32, font=(DISPLAY, 10))
        self.play_btn.pack(side="right", padx=(0, 8))
        self.subtitle_label = label(right_head, "", size=8, color=FAINT)
        self.subtitle_label.pack(side="left", padx=(10, 0), anchor="s")

        tab_row = tk.Frame(right, bg=PANEL)
        tab_row.pack(fill="x", padx=20, pady=(2, 0))
        specs = (("general", "General"), ("mods", "Mods"),
                 ("packs", "Packs"), ("shaders", "Shaders"),
                 ("worlds", "Mundos"), ("servers", "Servidores"),
                 ("shots", "Capturas"), ("logs", "Logs"),
                 ("console", "Consola"), ("advanced", "Avanzado"))
        for column in range(5):
            tab_row.grid_columnconfigure(column, weight=1, uniform="tab")
        for index, (key, text) in enumerate(specs):
            button = Button(tab_row, text, kind="quiet",
                            command=lambda key=key: self._show_tab(key),
                            height=28, font=(FONT, 8))
            button.grid(row=index // 5, column=index % 5, sticky="ew",
                        padx=(0, 4 if index % 5 != 4 else 0),
                        pady=(0, 4))
            self._tab_buttons[key] = button
        divider(right, top=8, bottom=0)

        self.tab_content = tk.Frame(right, bg=PANEL)
        self.tab_content.pack(fill="both", expand=True, padx=20, pady=(10, 14))

    def _select_initial(self) -> None:
        if self._initial_id:
            instance = self.store.by_id(self._initial_id)
            if instance:
                self.store.select(instance["id"])
                self._current = instance
        if self._current is None:
            self._current = self.store.selected()
        self._refresh()

    def _refresh(self) -> None:
        self._refresh_list()
        self._refresh_header()
        if self._current:
            self._show_tab(self._tab, force=True)
        else:
            self._empty_state()

    def _refresh_list(self) -> None:
        for child in self.list_scroll.content.winfo_children():
            child.destroy()
        selected_id = self._current["id"] if self._current else ""
        for instance in self.store.instances:
            self._instance_row(self.list_scroll.content, instance,
                               instance["id"] == selected_id)
        self.count_label.configure(text=str(len(self.store.instances)))

    def _instance_row(self, parent, instance: dict, active: bool) -> None:
        bg = CARD if active else PANEL
        row = tk.Frame(parent, bg=bg,
                       highlightbackground=BORDER if active else BORDER_SOFT,
                       highlightthickness=1)
        row.pack(fill="x", pady=(0, 6), padx=(0, 4))
        strip = tk.Frame(row, bg=instance.get("icon") or ACCENT, width=4)
        strip.pack(side="left", fill="y")
        info = tk.Frame(row, bg=bg)
        info.pack(side="left", fill="x", expand=True, padx=10, pady=8)
        label(info, instance.get("name", "Instancia"), size=10,
              color=TEXT if active else MUTED, font=(FONT, 10, "bold")).pack(
            anchor="w")
        loader = instances.LOADERS.get(instance.get("loader"), "Vanilla")
        subtitle = f"{loader} · {instance.get('version', '')}"
        if instance.get("group"):
            subtitle = f"{instance['group']} · {subtitle}"
        label(info, subtitle, size=8, color=FAINT, wrap=240).pack(
            anchor="w", pady=(2, 0))
        for widget in (row, strip, info, *info.winfo_children()):
            widget.bind("<Button-1>",
                        lambda _event, iid=instance["id"]: self._select(iid))
        if active:
            self._status(f"{instance.get('name')} · {loader} "
                         f"{instance.get('version', '')}")

    def _refresh_header(self) -> None:
        if not self._current:
            self.name_label.configure(text="Sin instancias")
            self.subtitle_label.configure(text="")
            self.play_btn.configure(state="disabled")
            self.open_btn.configure(state="disabled")
            self.export_btn.configure(state="disabled")
            self.duplicate_btn.configure(state="disabled")
            self.delete_btn.configure(state="disabled")
            return
        self.name_label.configure(text=self._current.get("name", "Instancia"))
        loader = instances.LOADERS.get(self._current.get("loader"), "Vanilla")
        resolved = self._current.get("resolved_version") or ""
        state = "listo" if resolved else "se preparará al jugar"
        self.subtitle_label.configure(
            text=f"{loader} {self._current.get('version', '')} · {state}")
        self.play_btn.configure(state="normal")
        self.open_btn.configure(state="normal")
        self.export_btn.configure(state="normal")
        self.duplicate_btn.configure(state="normal")
        self.delete_btn.configure(state="normal")

    def _status(self, text: str) -> None:
        self.status_var.set(text)

    def _empty_state(self) -> None:
        for child in self.tab_content.winfo_children():
            child.destroy()
        holder = tk.Frame(self.tab_content, bg=PANEL)
        holder.place(relx=0.5, rely=0.4, anchor="center")
        label(holder, "Todavía no hay instancias", color=TEXT,
              font=(DISPLAY, 17)).pack()
        label(holder, "Creá una para separar versiones, mods y configuraciones.",
              size=9, color=MUTED).pack(pady=(6, 14))
        Button(holder, "Crear instancia", kind="primary",
               command=self._new_instance, width=190, height=40).pack()

    def _select(self, instance_id: str) -> None:
        instance = self.store.by_id(instance_id)
        if not instance:
            return
        self._current = instance
        self.store.select(instance_id)
        self._refresh_list()
        self._refresh_header()
        self._show_tab(self._tab, force=True)

    def _show_tab(self, key: str, force: bool = False) -> None:
        if not self._current:
            return
        if key == self._tab and not force and self.tab_content.winfo_children():
            return
        self._tab = key
        if self._console_job is not None:
            try:
                self.after_cancel(self._console_job)
            except tk.TclError:
                pass
            self._console_job = None
        for child in self.tab_content.winfo_children():
            child.destroy()
        for name, button in self._tab_buttons.items():
            button.configure(kind="secondary" if name == key else "quiet")
        builders = {
            "general": self._tab_general,
            "mods": self._tab_mods,
            "packs": lambda parent: self._tab_files(parent, "resourcepacks",
                                                    "Paquetes de recursos",
                                                    "resourcepack"),
            "shaders": lambda parent: self._tab_files(parent, "shaderpacks",
                                                     "Shaders", "shader",
                                                     folders=True),
            "worlds": self._tab_worlds,
            "servers": self._tab_servers,
            "shots": self._tab_screenshots,
            "logs": self._tab_logs,
            "console": self._tab_console,
            "advanced": self._tab_advanced,
        }
        builders[key](self.tab_content)

    def _general_scroll(self, parent) -> tk.Frame:
        scroll = ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        return scroll.content

    def _tab_general(self, parent) -> None:
        content = self._general_scroll(parent)
        instance = self._current

        label(content, "Nombre", size=9, color=TEXT).pack(fill="x", pady=(0, 5))
        name_var = tk.StringVar(value=instance.get("name", ""))
        Input(content, textvariable=name_var).pack(fill="x")

        label(content, "Grupo (opcional)", size=9, color=TEXT).pack(
            fill="x", pady=(12, 5))
        group_var = tk.StringVar(value=instance.get("group", ""))
        Input(content, textvariable=group_var).pack(fill="x")

        label(content, "Color de la instancia", size=9, color=TEXT).pack(
            fill="x", pady=(12, 5))
        icon_var = tk.StringVar(value=instance.get("icon") or instances.ICON_COLORS[0])
        icon_row = tk.Frame(content, bg=PANEL)
        icon_row.pack(fill="x")
        swatches: list[tk.Canvas] = []

        def pick_color(color: str) -> None:
            icon_var.set(color)
            for swatch in swatches:
                selected = swatch._color == color
                swatch.configure(highlightbackground=color if selected else BORDER_SOFT,
                                 highlightthickness=2 if selected else 1)

        for color in instances.ICON_COLORS:
            swatch = tk.Canvas(icon_row, width=24, height=24, bg=PANEL,
                               highlightbackground=BORDER_SOFT,
                               highlightthickness=1, bd=0, cursor="hand2")
            swatch._color = color
            swatch.create_rectangle(4, 4, 20, 20, fill=color, outline="")
            swatch.bind("<Button-1>", lambda _event, value=color: pick_color(value))
            swatch.pack(side="left", padx=(0, 6))
            swatches.append(swatch)
        pick_color(icon_var.get())

        label(content, "Versión de Minecraft", size=9, color=TEXT).pack(
            fill="x", pady=(12, 5))
        version_picker = VersionPicker(
            content, self.app.manifest,
            initial=str(instance.get("version") or ""), height=38)
        version_picker.pack(fill="x")

        label(content, "Cargador", size=9, color=TEXT).pack(fill="x",
                                                            pady=(12, 5))
        loader_combo = Select(content, values=LOADER_LABELS, height=36)
        loader_combo.pack(fill="x")
        loader_combo.set(instances.LOADERS.get(instance.get("loader"), "Vanilla"))

        loader_hint = label(
            content,
            "Dejá la versión del cargador vacía para usar la última estable.",
            size=8, color=FAINT, wrap=680)
        loader_hint.pack(fill="x", pady=(6, 0))
        loader_version_var = tk.StringVar(value=instance.get("loader_version", ""))
        Input(content, textvariable=loader_version_var).pack(fill="x",
                                                             pady=(5, 0))

        row = tk.Frame(content, bg=PANEL)
        row.pack(fill="x", pady=(14, 2))
        label(row, "Memoria RAM", size=9, color=TEXT).pack(side="left")
        memory_var = tk.IntVar(value=max(512, min(8192, _int_or(
            instance.get("memory_mb", 2048), 2048))))
        memory_label = label(row, f"{memory_var.get()} MB", size=9, color=ACCENT,
                             font=(MONO, 9), width=9, anchor="e")
        memory_label.pack(side="right")

        def on_memory(raw):
            try:
                value = int(float(raw))
            except (TypeError, ValueError):
                return
            memory_label.configure(text=f"{value} MB")

        Slider(row, from_=512, to=8192, variable=memory_var, step=256,
               command=on_memory).pack(side="left", fill="x", expand=True,
                                       padx=(12, 12))

        res_row = tk.Frame(content, bg=PANEL)
        res_row.pack(fill="x", pady=(10, 0))
        custom_var = tk.BooleanVar(value=bool(instance.get("custom_resolution")))
        width_var = tk.StringVar(value=str(instance.get("resolution_width", 1280)))
        height_var = tk.StringVar(value=str(instance.get("resolution_height", 720)))
        width_entry = Input(res_row, textvariable=width_var, width=6)
        height_entry = Input(res_row, textvariable=height_var, width=6)

        def toggle_res():
            state = "normal" if custom_var.get() else "disabled"
            width_entry.configure(state=state)
            height_entry.configure(state=state)

        Check(res_row, "Resolución personalizada", custom_var,
              command=toggle_res, bg=PANEL).pack(side="left")
        height_entry.pack(side="right")
        label(res_row, "×", color=FAINT).pack(side="right", padx=5)
        width_entry.pack(side="right")
        toggle_res()

        aikar_var = tk.BooleanVar(value=bool(instance.get("aikar_flags", True)))
        Check(content, "Flags de rendimiento (GC Aikar)", aikar_var,
              bg=PANEL).pack(anchor="w", pady=(12, 0))

        divider(content, top=14, bottom=12)
        label(content, "Java de la instancia", size=9, color=TEXT).pack(fill="x")
        java_mode = instance.get("java_mode", "inherit")
        java_label = next((key for key, value in JAVA_MODES.items()
                           if value == java_mode), JAVA_LABELS[0])
        java_var = tk.StringVar(value=java_label)
        java_combo = Select(content, values=JAVA_LABELS, height=36)
        java_combo.pack(fill="x", pady=(6, 0))
        java_combo.set(java_label)
        path_var = tk.StringVar(value=instance.get("java_path", ""))
        path_row = tk.Frame(content, bg=PANEL)
        path_row.pack(fill="x", pady=(6, 0))
        path_entry = Input(path_row, textvariable=path_var)
        path_entry.pack(side="left", fill="x", expand=True)

        def browse_java():
            chosen = filedialog.askopenfilename(
                parent=self, title="Selecciona java.exe",
                filetypes=[("Java", "java.exe"), ("Todos", "*.*")])
            if chosen:
                path_var.set(chosen)
                java_var.set("Ruta personalizada")
                java_combo.set("Ruta personalizada")
                toggle_java()

        Button(path_row, "Elegir", command=browse_java, width=78,
               height=33).pack(side="left", padx=(8, 0))

        def toggle_java():
            state = "normal" if JAVA_MODES.get(java_var.get()) == "custom" else "disabled"
            path_entry.configure(state=state)

        java_combo.bind("<<ComboboxSelected>>",
                        lambda _event: toggle_java())
        toggle_java()

        divider(content, top=14, bottom=12)
        label(content, "Notas", size=9, color=TEXT).pack(fill="x")
        notes_var = tk.StringVar(value=instance.get("notes", ""))
        Input(content, textvariable=notes_var).pack(fill="x", pady=(6, 0))
        label(content, "Solo para vos: recordatorios, semillas, contraseñas "
                       "de servidores, etc.", size=8, color=FAINT).pack(
            fill="x", pady=(4, 0))

        actions = tk.Frame(parent, bg=PANEL)
        actions.pack(fill="x", pady=(10, 0))
        Button(actions, "Guardar cambios", kind="primary",
               command=lambda: self._save_general(
                   name_var, group_var, icon_var, version_picker,
                   loader_combo, loader_version_var, memory_var, custom_var,
                   width_var, height_var, aikar_var, java_var, path_var,
                   notes_var),
               width=180, height=38).pack(side="right")
        tk.Frame(content, bg=PANEL, height=8).pack(fill="x")

    def _save_general(self, name_var, group_var, icon_var, version_picker,
                      loader_combo, loader_version_var,
                      memory_var, custom_var, width_var, height_var, aikar_var,
                      java_var, path_var, notes_var) -> None:
        instance = self._current
        if not instance:
            return
        if self._busy:
            self._status("Esperá a que termine la operación en curso...")
            return
        name = name_var.get().strip()
        if not name:
            show_warning(self, "Instancia", "El nombre no puede quedar vacío.")
            return
        version_id = version_picker.selected_id()
        if not version_id:
            show_warning(self, "Instancia", "Elegí una versión de Minecraft.")
            return
        loader = LOADER_BY_LABEL.get(loader_combo.get().strip().lower(),
                                     "vanilla")
        loader_version = loader_version_var.get().strip()
        game_changed = (instance.get("version") != version_id
                        or instance.get("loader") != loader)
        if game_changed:
            loader_version = ""
            if loader_version_var.get():
                loader_version_var.set("")
        changed = (instance.get("version") != version_id
                   or instance.get("loader") != loader
                   or instance.get("loader_version", "") != loader_version)
        try:
            width = max(320, int(width_var.get()))
            height = max(240, int(height_var.get()))
        except ValueError:
            show_warning(self, "Instancia", "La resolución debe ser numérica.")
            return
        java_mode = JAVA_MODES.get(java_var.get(), "inherit")
        java_path = path_var.get().strip()
        if java_mode == "custom" and (not java_path
                                      or not Path(java_path).is_file()):
            show_warning(self, "Java",
                         "Elegí un java.exe válido o usá Temurin automático.")
            return
        instance["name"] = name
        instance["group"] = group_var.get().strip()[:40]
        instance["icon"] = icon_var.get() or instances.ICON_COLORS[0]
        instance["version"] = version_id
        instance["loader"] = loader
        instance["loader_version"] = loader_version
        if changed:
            instance["resolved_version"] = ""
        instance["memory_mb"] = max(512, min(8192, _int_or(
            memory_var.get(), 2048)))
        instance["custom_resolution"] = bool(custom_var.get())
        instance["resolution_width"] = width
        instance["resolution_height"] = height
        instance["aikar_flags"] = bool(aikar_var.get())
        instance["java_mode"] = java_mode
        instance["java_path"] = java_path if java_mode == "custom" else ""
        instance["notes"] = notes_var.get().strip()[:500]
        self.store.save()
        self._status("Cambios guardados")
        self._refresh_list()
        self._refresh_header()
        if self.app._instance and self.app._instance.get("id") == instance["id"]:
            self.app._refresh_instances(select_id=instance["id"])
            self.app._apply_instance(instance)

    def _tab_advanced(self, parent) -> None:
        scroll = ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        content = scroll.content
        instance = self._current
        label(content, "Argumentos y automatización", size=9, color=TEXT).pack(
            fill="x")
        label(content, "Estos ajustes se aplican solo a esta instancia.",
              size=8, color=FAINT).pack(fill="x", pady=(2, 10))

        label(content, "Argumentos JVM", size=9, color=TEXT).pack(fill="x")
        jvm_var = tk.StringVar(value=instance.get("jvm_args", ""))
        Input(content, textvariable=jvm_var).pack(fill="x", pady=(5, 0))
        label(content, "Se agregan después de los flags de memoria. Ej: "
                       "-XX:+UseZGC -Dfile.encoding=UTF-8",
              size=8, color=FAINT).pack(fill="x", pady=(4, 0))

        label(content, "Argumentos del juego", size=9, color=TEXT).pack(
            fill="x", pady=(12, 0))
        game_var = tk.StringVar(value=instance.get("game_args", ""))
        Input(content, textvariable=game_var).pack(fill="x", pady=(5, 0))
        label(content, "Ej: --width 1920 --height 1080 --fullscreen",
              size=8, color=FAINT).pack(fill="x", pady=(4, 0))

        label(content, "Variables de entorno", size=9, color=TEXT).pack(
            fill="x", pady=(12, 0))
        env_var = tk.StringVar(value=instance.get("env_vars", ""))
        Input(content, textvariable=env_var).pack(fill="x", pady=(5, 0))
        label(content, "Formato CLAVE=VALOR, separadas por punto y coma. "
                       "Ej: MESA_GL_VERSION_OVERRIDE=4.6;LIBGL_ALWAYS_SOFTWARE=1",
              size=8, color=FAINT, wrap=640).pack(fill="x", pady=(4, 0))

        divider(content, top=14, bottom=12)
        label(content, "Comandos", size=9, color=TEXT).pack(fill="x")
        label(content, "Antes de lanzar", size=8, color=MUTED).pack(
            fill="x", pady=(8, 4))
        pre_var = tk.StringVar(value=instance.get("pre_launch", ""))
        Input(content, textvariable=pre_var).pack(fill="x")
        label(content, "Al cerrar el juego", size=8, color=MUTED).pack(
            fill="x", pady=(8, 4))
        post_var = tk.StringVar(value=instance.get("post_exit", ""))
        Input(content, textvariable=post_var).pack(fill="x")
        label(content, "Se ejecutan con el directorio de la instancia como "
                       "carpeta actual.", size=8, color=FAINT).pack(
            fill="x", pady=(4, 0))

        divider(content, top=14, bottom=12)
        label(content, "Inicio rápido (Quick Play)", size=9, color=TEXT).pack(
            fill="x")
        label(content, "Entra directo a un mundo o servidor al abrir el juego. "
                       "Requiere Minecraft 1.20 o superior.", size=8,
              color=FAINT, wrap=640).pack(fill="x", pady=(2, 8))
        quick_labels = ["No usar", "Mundo local", "Servidor", "Realms"]
        quick_values = {"No usar": "none", "Mundo local": "world",
                        "Servidor": "server", "Realms": "realms"}
        quick_reverse = {value: text for text, value in quick_values.items()}
        quick_var = tk.StringVar(
            value=quick_reverse.get(instance.get("quick_play_type", "none"),
                                    "No usar"))
        quick_target_var = tk.StringVar(
            value=instance.get("quick_play_target", ""))
        quick_combo = Select(content, values=quick_labels, height=36)
        quick_combo.pack(fill="x")
        quick_combo.set(quick_var.get())
        quick_target = Input(content, textvariable=quick_target_var)
        quick_target.pack(fill="x", pady=(6, 0))
        quick_hint = label(content, "", size=8, color=FAINT, wrap=640)
        quick_hint.pack(fill="x", pady=(4, 0))

        def sync_quick():
            kind = quick_values.get(quick_combo.get(), "none")
            quick_var.set(kind)
            if kind == "none":
                quick_target.configure(state="disabled")
                quick_hint.configure(
                    text="El juego abrirá el menú principal como siempre.")
            elif kind == "world":
                quick_target.configure(state="normal")
                quick_hint.configure(
                    text="Nombre exacto de la carpeta dentro de saves/.")
            elif kind == "server":
                quick_target.configure(state="normal")
                quick_hint.configure(
                    text="Dirección del servidor, por ejemplo play.ejemplo.net.")
            else:
                quick_target.configure(state="normal")
                quick_hint.configure(
                    text="ID o nombre del Realm al que pertenece la cuenta.")

        quick_combo.bind("<<ComboboxSelected>>",
                         lambda _event: sync_quick())
        sync_quick()

        actions = tk.Frame(parent, bg=PANEL)
        actions.pack(fill="x", pady=(10, 0))
        Button(actions, "Guardar cambios", kind="primary",
               command=lambda: self._save_advanced(
                   jvm_var, game_var, env_var, pre_var, post_var,
                   quick_combo.get(), quick_target_var),
               width=180, height=38).pack(side="right")
        tk.Frame(content, bg=PANEL, height=8).pack(fill="x")

    def _save_advanced(self, jvm_var, game_var, env_var, pre_var, post_var,
                       quick_label, quick_target_var) -> None:
        instance = self._current
        if not instance:
            return
        quick_map = {"No usar": "none", "Mundo local": "world",
                     "Servidor": "server", "Realms": "realms"}
        quick_type = quick_map.get(quick_label, "none")
        target = quick_target_var.get().strip()
        if quick_type != "none" and not target:
            show_warning(self, "Quick Play",
                         "Indicá el mundo, servidor o Realm de destino.")
            return
        instance["jvm_args"] = jvm_var.get().strip()[:2000]
        instance["game_args"] = game_var.get().strip()[:2000]
        instance["env_vars"] = env_var.get().strip()[:2000]
        instance["pre_launch"] = pre_var.get().strip()[:1000]
        instance["post_exit"] = post_var.get().strip()[:1000]
        instance["quick_play_type"] = quick_type
        instance["quick_play_target"] = target[:200] if quick_type != "none" else ""
        self.store.save()
        self._status("Ajustes avanzados guardados")
        self._refresh_header()
        if self.app._instance and self.app._instance.get("id") == instance["id"]:
            self.app._apply_instance(instance)

    def _tab_mods(self, parent) -> None:
        self._files_header(parent, "mods", "mod", include_modrinth=True,
                           add_folder=False)
        self._fill_entries(parent, "mods", mods=True)

    def _tab_files(self, parent, kind: str, title: str, project_type: str,
                   folders: bool = False) -> None:
        toolbar = tk.Frame(parent, bg=PANEL)
        toolbar.pack(fill="x", pady=(0, 8))
        section(toolbar, title).pack(side="left", fill="x", expand=True)
        Button(toolbar, "Abrir carpeta", kind="quiet",
               command=lambda: self._open_kind(kind), width=108, height=28,
               font=(FONT, 8)).pack(side="right")
        Button(toolbar, "Modrinth", command=lambda: self._open_modrinth(
            project_type), width=86, height=28, font=(FONT, 8)).pack(
            side="right", padx=(0, 6))
        Button(toolbar, "+ Archivos", command=lambda: self._add_files(kind),
               width=94, height=28, font=(FONT, 8)).pack(side="right",
                                                         padx=(0, 6))
        if folders:
            Button(toolbar, "+ Carpeta", command=lambda: self._add_folder(kind),
                   width=88, height=28, font=(FONT, 8)).pack(side="right",
                                                             padx=(0, 6))
        scroll = ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        items = self.store.list_simple(self._current, kind,
                                       (".zip", ".jar", ".7z", ".mrpack"))
        if not items:
            label(scroll.content, "No hay archivos todavía.", size=9,
                  color=FAINT).pack(anchor="w", pady=8)
            return
        for item in items:
            self._file_row(scroll.content, item, kind)

    def _files_header(self, parent, kind: str, project_type: str,
                      include_modrinth: bool, add_folder: bool) -> None:
        toolbar = tk.Frame(parent, bg=PANEL)
        toolbar.pack(fill="x", pady=(0, 8))
        section(toolbar, "Mods instalados").pack(side="left", fill="x",
                                                 expand=True)
        Button(toolbar, "Abrir carpeta", kind="quiet",
               command=lambda: self._open_kind(kind), width=108, height=28,
               font=(FONT, 8)).pack(side="right")
        if include_modrinth:
            Button(toolbar, "Modrinth", command=lambda: self._open_modrinth(
                project_type), width=86, height=28, font=(FONT, 8)).pack(
                side="right", padx=(0, 6))
            Button(toolbar, "Actualizar",
                   command=lambda: self._check_updates(project_type),
                   width=84, height=28, font=(FONT, 8)).pack(
                side="right", padx=(0, 6))
        Button(toolbar, "+ Archivos", command=lambda: self._add_files(kind),
               width=94, height=28, font=(FONT, 8)).pack(side="right",
                                                         padx=(0, 6))
        if add_folder:
            Button(toolbar, "+ Carpeta", command=lambda: self._add_folder(kind),
                   width=88, height=28, font=(FONT, 8)).pack(side="right",
                                                             padx=(0, 6))

    def _fill_entries(self, parent, kind: str, mods: bool = False) -> None:
        scroll = ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        items = (self.store.list_mods(self._current) if mods
                 else self.store.list_simple(self._current, kind))
        if not items:
            label(scroll.content, "No hay archivos todavía.", size=9,
                  color=FAINT).pack(anchor="w", pady=8)
            return
        if mods:
            for entry in items:
                self._mod_row(scroll.content, entry)
        else:
            for item in items:
                self._file_row(scroll.content, item, kind)

    def _mod_row(self, parent, entry: dict) -> None:
        row = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER_SOFT,
                       highlightthickness=1)
        row.pack(fill="x", pady=(0, 5))
        info = tk.Frame(row, bg=PANEL)
        info.pack(side="left", fill="x", expand=True, padx=10, pady=7)
        label(info, entry["name"], size=9,
              color=TEXT if entry["enabled"] else FAINT).pack(anchor="w")
        label(info, _size_text(entry["size"])
              + (" · activo" if entry["enabled"] else " · desactivado"),
              size=8, color=GRASS if entry["enabled"] else FAINT).pack(
            anchor="w", pady=(2, 0))
        Button(row, "Quitar", kind="danger",
               command=lambda path=entry["path"]: self._delete_entry(path),
               width=66, height=26, font=(FONT, 8)).pack(side="right",
                                                         padx=(0, 8))
        Button(row, "Desactivar" if entry["enabled"] else "Activar",
               command=lambda path=entry["path"]: self._toggle_mod(path),
               width=84, height=26, font=(FONT, 8)).pack(side="right",
                                                         padx=(4, 4))

    def _file_row(self, parent, path: Path, kind: str) -> None:
        row = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER_SOFT,
                       highlightthickness=1)
        row.pack(fill="x", pady=(0, 5))
        info = tk.Frame(row, bg=PANEL)
        info.pack(side="left", fill="x", expand=True, padx=10, pady=7)
        label(info, path.name, size=9, color=TEXT).pack(anchor="w")
        try:
            size = path.stat().st_size if path.is_file() else 0
        except OSError:
            size = 0
        label(info, ("Carpeta" if path.is_dir() else _size_text(size)),
              size=8, color=FAINT).pack(anchor="w", pady=(2, 0))
        Button(row, "Quitar", kind="danger",
               command=lambda: self._delete_entry(path), width=66, height=26,
               font=(FONT, 8)).pack(side="right", padx=(0, 8))
        if path.is_dir():
            Button(row, "Abrir", kind="quiet",
                   command=lambda: _open_path(path), width=62, height=26,
                   font=(FONT, 8)).pack(side="right", padx=(4, 4))

    def _add_files(self, kind: str) -> None:
        chosen = filedialog.askopenfilenames(
            parent=self, title="Agregar archivos",
            filetypes=[("Archivos", "*.zip *.jar *.7z"), ("Todos", "*.*")])
        if not chosen:
            return
        try:
            added = self.store.add_files(self._current, kind,
                                         [Path(item) for item in chosen])
        except instances.InstanceError as exc:
            show_error(self, "Archivos", str(exc))
            return
        self._status(f"{added} archivo(s) agregado(s)")
        self._show_tab(self._tab, force=True)

    def _add_folder(self, kind: str) -> None:
        chosen = filedialog.askdirectory(parent=self, title="Agregar carpeta")
        if not chosen:
            return
        try:
            self.store.add_folder(self._current, kind, Path(chosen))
        except instances.InstanceError as exc:
            show_error(self, "Carpeta", str(exc))
            return
        self._status("Carpeta agregada")
        self._show_tab(self._tab, force=True)

    def _toggle_mod(self, path: Path) -> None:
        try:
            enabled = self.store.toggle_mod(self._current, path)
        except instances.InstanceError as exc:
            show_error(self, "Mods", str(exc))
            return
        self._status("Mod activado" if enabled else "Mod desactivado")
        self._show_tab("mods", force=True)

    def _delete_entry(self, path: Path) -> None:
        if not show_confirm(self, "Quitar archivo",
                            f"¿Quitar {path.name} de esta instancia?",
                            "Quitar"):
            return
        try:
            self.store.delete_entry(self._current, path)
        except instances.InstanceError as exc:
            show_error(self, "Archivo", str(exc))
            return
        self._status("Archivo eliminado")
        self._show_tab(self._tab, force=True)

    def _open_kind(self, kind: str) -> None:
        folder = self.store.game_dir(self._current) / kind
        folder.mkdir(parents=True, exist_ok=True)
        _open_path(folder)

    def _open_instance_folder(self) -> None:
        if self._current:
            folder = self.store.game_dir(self._current)
            folder.mkdir(parents=True, exist_ok=True)
            _open_path(folder)

    def _check_updates(self, project_type: str) -> None:
        if not self._current or self._busy:
            return
        instance = self._current
        self._busy = True
        self._set_buttons(False)
        self._status("Buscando actualizaciones...")

        def work():
            try:
                updated = modrinth.check_updates(
                    instance, project_type,
                    on_status=lambda text: self._queue.put(("status", text)))
                self._queue.put(("update_result", [str(path) for path in updated]))
            except Exception as exc:
                self._queue.put(("update_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _open_modrinth(self, project_type: str) -> None:
        if self._modrinth_window is not None and self._modrinth_window.winfo_exists():
            self._modrinth_window.lift()
            return
        self._modrinth_window = ModrinthDialog(self, self._current,
                                               project_type,
                                               on_installed=self._modrinth_done)

    def _modrinth_done(self) -> None:
        window = self._modrinth_window
        if window is not None and not window.winfo_exists():
            self._modrinth_window = None
        self._status("Contenido instalado desde Modrinth")
        if self._current:
            self._show_tab(self._tab, force=True)

    def _tab_worlds(self, parent) -> None:
        toolbar = tk.Frame(parent, bg=PANEL)
        toolbar.pack(fill="x", pady=(0, 8))
        section(toolbar, "Mundos").pack(side="left", fill="x", expand=True)
        Button(toolbar, "Abrir saves", kind="quiet",
               command=lambda: self._open_kind("saves"), width=96, height=28,
               font=(FONT, 8)).pack(side="right")
        Button(toolbar, "Importar", command=self._import_world, width=84,
               height=28, font=(FONT, 8)).pack(side="right", padx=(0, 6))
        scroll = ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        worlds = self.store.worlds(self._current)
        if not worlds:
            label(scroll.content, "No hay mundos guardados todavía.", size=9,
                  color=FAINT).pack(anchor="w", pady=8)
            return
        for world in worlds:
            row = tk.Frame(scroll.content, bg=PANEL,
                           highlightbackground=BORDER_SOFT, highlightthickness=1)
            row.pack(fill="x", pady=(0, 5))
            info = tk.Frame(row, bg=PANEL)
            info.pack(side="left", fill="x", expand=True, padx=10, pady=7)
            label(info, world["name"], size=9, color=TEXT).pack(anchor="w")
            try:
                when = time.strftime("%Y-%m-%d %H:%M",
                                     time.localtime(world["modified"]))
            except (OverflowError, OSError, ValueError):
                when = ""
            label(info, when, size=8, color=FAINT).pack(anchor="w",
                                                        pady=(2, 0))
            Button(row, "Quitar", kind="danger",
                   command=lambda path=world["path"]: self._delete_world(path),
                   width=58, height=26, font=(FONT, 8)).pack(side="right",
                                                             padx=(0, 6))
            Button(row, "Renombrar", kind="quiet",
                   command=lambda path=world["path"]: self._rename_world(path),
                   width=78, height=26, font=(FONT, 8)).pack(side="right",
                                                             padx=(0, 4))
            Button(row, "Duplicar", kind="quiet",
                   command=lambda path=world["path"]: self._duplicate_world(path),
                   width=68, height=26, font=(FONT, 8)).pack(side="right",
                                                             padx=(0, 4))
            Button(row, "Exportar", kind="quiet",
                   command=lambda path=world["path"]: self._export_world(path),
                   width=68, height=26, font=(FONT, 8)).pack(side="right",
                                                             padx=(0, 4))
            Button(row, "Jugar", kind="secondary",
                   command=lambda name=world["name"]: self._play_world(name),
                   width=58, height=26, font=(FONT, 8)).pack(side="right",
                                                             padx=(0, 4))

    def _play_world(self, name: str) -> None:
        self.app._quick_play_override = ("world", name)
        self._play_current()

    def _import_world(self) -> None:
        chosen = filedialog.askdirectory(parent=self,
                                         title="Importar carpeta de mundo")
        if not chosen:
            return
        source = Path(chosen)
        saves = self.store.game_dir(self._current) / "saves"
        try:
            source_resolved = source.resolve()
            saves_resolved = saves.resolve()
        except OSError as exc:
            show_error(self, "Mundos", f"No se pudo leer la carpeta: {exc}")
            return
        if (source_resolved == saves_resolved
                or saves_resolved in source_resolved.parents
                or source_resolved in saves_resolved.parents):
            show_warning(self, "Mundos",
                         "Elegí una carpeta fuera de la instancia y de saves.")
            return
        saves.mkdir(parents=True, exist_ok=True)
        target = saves / source.name
        suffix = 2
        while target.exists():
            target = saves / f"{source.name} {suffix}"
            suffix += 1
        try:
            shutil.copytree(source, target)
        except OSError as exc:
            show_error(self, "Mundos", f"No se pudo importar: {exc}")
            return
        self._status("Mundo importado")
        self._show_tab("worlds", force=True)

    def _export_world(self, path: Path) -> None:
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Exportar mundo", defaultextension=".zip",
            initialfile=f"{path.name}.zip",
            filetypes=[("Paquete de mundo", "*.zip")])
        if not chosen:
            return
        try:
            with zipfile.ZipFile(chosen, "w", zipfile.ZIP_DEFLATED) as archive:
                for item in path.rglob("*"):
                    if item.is_file():
                        archive.write(item, item.relative_to(path).as_posix())
        except OSError as exc:
            show_error(self, "Mundos", f"No se pudo exportar: {exc}")
            return
        self._status("Mundo exportado")

    def _duplicate_world(self, path: Path) -> None:
        target = path.with_name(f"{path.name} copia")
        suffix = 2
        while target.exists():
            target = path.with_name(f"{path.name} copia {suffix}")
            suffix += 1
        try:
            shutil.copytree(path, target)
        except OSError as exc:
            show_error(self, "Mundos", f"No se pudo duplicar: {exc}")
            return
        self._status("Mundo duplicado")
        self._show_tab("worlds", force=True)

    def _rename_world(self, path: Path) -> None:
        dialog = PromptDialog(self, "Renombrar mundo", "Nuevo nombre",
                              path.name)
        self.wait_window(dialog)
        name = (dialog.result or "").strip()
        if not name or name == path.name:
            return
        if any(char in name for char in '\\/:*?"<>|'):
            show_warning(self, "Mundos", "El nombre tiene caracteres inválidos.")
            return
        target = path.with_name(name)
        if target.exists():
            show_warning(self, "Mundos", "Ya existe un mundo con ese nombre.")
            return
        try:
            path.rename(target)
        except OSError as exc:
            show_error(self, "Mundos", f"No se pudo renombrar: {exc}")
            return
        self._status("Mundo renombrado")
        self._show_tab("worlds", force=True)

    def _delete_world(self, path: Path) -> None:
        if self.app._game is not None:
            show_warning(self, "Mundos",
                         "Cerrá Minecraft antes de eliminar un mundo.")
            return
        if not show_confirm(
                self, "Eliminar mundo",
                f"¿Eliminar para siempre el mundo {path.name}?", "Eliminar"):
            return
        try:
            self.store.delete_entry(self._current, path)
        except instances.InstanceError as exc:
            show_error(self, "Mundo", str(exc))
            return
        self._status("Mundo eliminado")
        self._show_tab("worlds", force=True)

    def _tab_servers(self, parent) -> None:
        toolbar = tk.Frame(parent, bg=PANEL)
        toolbar.pack(fill="x", pady=(0, 8))
        section(toolbar, "Servidores guardados").pack(side="left", fill="x",
                                                      expand=True)
        Button(toolbar, "Abrir archivo", kind="quiet",
               command=self._open_servers_file, width=104, height=28,
               font=(FONT, 8)).pack(side="right")
        Button(toolbar, "Agregar", command=self._add_server, width=84,
               height=28, font=(FONT, 8)).pack(side="right", padx=(0, 6))
        scroll = ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        path = servers.servers_file(self.store.game_dir(self._current))
        try:
            entries = servers.list_servers(path)
        except servers.ServerError as exc:
            label(scroll.content, str(exc), size=9, color=DANGER).pack(
                anchor="w", pady=8)
            return
        if not entries:
            label(scroll.content, "No hay servidores guardados todavía.",
                  size=9, color=FAINT).pack(anchor="w", pady=8)
            label(scroll.content, "Minecraft los guarda en servers.dat.",
                  size=8, color=FAINT).pack(anchor="w")
            return
        for index, entry in enumerate(entries):
            row = tk.Frame(scroll.content, bg=PANEL,
                           highlightbackground=BORDER_SOFT, highlightthickness=1)
            row.pack(fill="x", pady=(0, 5))
            info = tk.Frame(row, bg=PANEL)
            info.pack(side="left", fill="x", expand=True, padx=10, pady=7)
            label(info, entry["name"], size=9, color=TEXT).pack(anchor="w")
            label(info, entry["ip"], size=8, color=FAINT).pack(
                anchor="w", pady=(2, 0))
            status = label(info, "", size=8, color=FAINT)
            status.pack(anchor="w", pady=(2, 0))
            Button(row, "Quitar", kind="danger",
                   command=lambda i=index: self._delete_server(i),
                   width=58, height=26, font=(FONT, 8)).pack(
                side="right", padx=(0, 6))
            Button(row, "Editar", kind="quiet",
                   command=lambda i=index: self._edit_server(i),
                   width=58, height=26, font=(FONT, 8)).pack(
                side="right", padx=(0, 4))
            Button(row, "Probar", kind="quiet",
                   command=lambda e=entry, s=status: self._ping_server(e, s),
                   width=62, height=26, font=(FONT, 8)).pack(
                side="right", padx=(0, 4))
            Button(row, "Conectar", kind="secondary",
                   command=lambda addr=entry["ip"]: self._connect_server(addr),
                   width=74, height=26, font=(FONT, 8)).pack(
                side="right", padx=(0, 4))

    def _open_servers_file(self) -> None:
        folder = self.store.game_dir(self._current)
        folder.mkdir(parents=True, exist_ok=True)
        _open_path(folder)

    def _ping_server(self, entry: dict, status_widget) -> None:
        try:
            status_widget.configure(text="Comprobando...", fg=FAINT)
        except tk.TclError:
            return
        self._status(f"Comprobando {entry.get('ip', '')}...")

        def work():
            try:
                result = servers.ping(entry.get("ip", ""))
            except Exception as exc:
                self._queue.put(("server_status",
                                 (status_widget, None, str(exc))))
            else:
                self._queue.put(("server_status",
                                 (status_widget, result, "")))

        threading.Thread(target=work, daemon=True).start()

    def _connect_server(self, address: str) -> None:
        self.app._quick_play_override = ("server", address)
        self._play_current()

    def _add_server(self) -> None:
        dialog = ServerDialog(self, "Agregar servidor")
        self.wait_window(dialog)
        if not dialog.result:
            return
        name, ip = dialog.result
        path = servers.servers_file(self.store.game_dir(self._current))
        try:
            servers.add_server(path, name, ip)
        except servers.ServerError as exc:
            show_error(self, "Servidores", str(exc))
            return
        self._status("Servidor agregado")
        self._show_tab("servers", force=True)

    def _edit_server(self, index: int) -> None:
        path = servers.servers_file(self.store.game_dir(self._current))
        try:
            entries = servers.list_servers(path)
        except servers.ServerError as exc:
            show_error(self, "Servidores", str(exc))
            return
        if not 0 <= index < len(entries):
            return
        entry = entries[index]
        dialog = ServerDialog(self, "Editar servidor", entry["name"], entry["ip"])
        self.wait_window(dialog)
        if not dialog.result:
            return
        name, ip = dialog.result
        try:
            servers.update_server(path, index, name, ip)
        except servers.ServerError as exc:
            show_error(self, "Servidores", str(exc))
            return
        self._status("Servidor actualizado")
        self._show_tab("servers", force=True)

    def _delete_server(self, index: int) -> None:
        if not show_confirm(self, "Quitar servidor",
                            "¿Quitar este servidor de la lista?", "Quitar"):
            return
        path = servers.servers_file(self.store.game_dir(self._current))
        try:
            servers.remove_server(path, index)
        except servers.ServerError as exc:
            show_error(self, "Servidores", str(exc))
            return
        self._status("Servidor eliminado")
        self._show_tab("servers", force=True)

    def _tab_screenshots(self, parent) -> None:
        toolbar = tk.Frame(parent, bg=PANEL)
        toolbar.pack(fill="x", pady=(0, 8))
        section(toolbar, "Capturas").pack(side="left", fill="x", expand=True)
        Button(toolbar, "Abrir carpeta", kind="quiet",
               command=lambda: self._open_kind("screenshots"), width=108,
               height=28, font=(FONT, 8)).pack(side="right")
        scroll = ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        folder = self.store.game_dir(self._current) / "screenshots"
        try:
            shots = sorted((p for p in folder.iterdir()
                            if p.is_file() and p.suffix.lower() in
                            (".png", ".jpg", ".jpeg")),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            shots = []
        if not shots:
            label(scroll.content, "No hay capturas todavía.", size=9,
                  color=FAINT).pack(anchor="w", pady=8)
            return
        for shot in shots:
            row = tk.Frame(scroll.content, bg=PANEL,
                           highlightbackground=BORDER_SOFT, highlightthickness=1)
            row.pack(fill="x", pady=(0, 5))
            info = tk.Frame(row, bg=PANEL)
            info.pack(side="left", fill="x", expand=True, padx=10, pady=7)
            label(info, shot.name, size=9, color=TEXT).pack(anchor="w")
            label(info, _size_text(shot.stat().st_size), size=8,
                  color=FAINT).pack(anchor="w", pady=(2, 0))
            Button(row, "Quitar", kind="danger",
                   command=lambda path=shot: self._delete_shot(path),
                   width=58, height=26, font=(FONT, 8)).pack(
                side="right", padx=(0, 6))
            Button(row, "Abrir", kind="quiet",
                   command=lambda path=shot: _open_path(path), width=62,
                   height=26, font=(FONT, 8)).pack(side="right", padx=(0, 4))

    def _delete_shot(self, path: Path) -> None:
        if not show_confirm(self, "Eliminar captura",
                            f"¿Eliminar {path.name}?", "Eliminar"):
            return
        try:
            path.unlink()
        except OSError as exc:
            show_error(self, "Capturas", f"No se pudo eliminar: {exc}")
            return
        self._status("Captura eliminada")
        self._show_tab("shots", force=True)

    def _tab_console(self, parent) -> None:
        toolbar = tk.Frame(parent, bg=PANEL)
        toolbar.pack(fill="x", pady=(0, 8))
        section(toolbar, "Consola del juego").pack(side="left", fill="x",
                                                   expand=True)
        Button(toolbar, "Diagnóstico", kind="quiet",
               command=self._diagnose_console, width=96, height=28,
               font=(FONT, 8)).pack(side="right", padx=(0, 6))
        Button(toolbar, "Abrir logs", kind="quiet",
               command=lambda: self._open_kind("logs"), width=90, height=28,
               font=(FONT, 8)).pack(side="right")
        Button(toolbar, "Recargar", kind="quiet",
               command=lambda: self._console_load(reset=True), width=82,
               height=28, font=(FONT, 8)).pack(side="right", padx=(0, 6))
        follow_var = tk.BooleanVar(value=True)
        Check(toolbar, "Seguir", follow_var, bg=PANEL).pack(
            side="right", padx=(0, 10))
        self._console_follow = follow_var

        holder = tk.Frame(parent, bg=LOG_BG, highlightbackground=BORDER,
                          highlightthickness=1)
        holder.pack(fill="both", expand=True)
        self._console_text = tk.Text(
            holder, bg=LOG_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
            bd=0, wrap="none", font=(MONO, 8), padx=10, pady=6,
            state="disabled", highlightthickness=0,
            selectbackground="#3c3325")
        scroll = ThinScroll(holder, command=self._console_text.yview,
                            bg=LOG_BG, width=8)
        self._console_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 4), pady=4)
        self._console_text.pack(side="left", fill="both", expand=True)
        for tag, color in (("err", DANGER), ("warn", WARN), ("dim", FAINT)):
            self._console_text.tag_configure(tag, foreground=color)

        self._console_lines: list[str] = []
        self._console_offset = 0
        self._console_partial = ""
        self._console_path = (self.store.game_dir(self._current) / "logs"
                              / "latest.log")
        self._console_load(reset=True)
        self._console_job = self.after(1000, self._console_tick)

    def _console_tick(self) -> None:
        self._console_job = None
        if not self._console_text.winfo_exists():
            return
        self._console_load()
        self._console_job = self.after(1000, self._console_tick)

    def _console_load(self, reset: bool = False) -> None:
        text = getattr(self, "_console_text", None)
        if text is None or not text.winfo_exists():
            return
        path = self._console_path
        if reset:
            self._console_lines = []
            self._console_offset = 0
            self._console_partial = ""
        if not path.is_file():
            if reset:
                self._console_render(["Todavía no hay logs. Abrí el juego "
                                      "para ver la salida en vivo."], dim=True)
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size < self._console_offset:
            self._console_lines = []
            self._console_offset = 0
            self._console_partial = ""
        if size == self._console_offset:
            return
        try:
            with open(path, "rb") as handle:
                handle.seek(self._console_offset)
                chunk = handle.read(262144)
        except OSError:
            return
        self._console_offset += len(chunk)
        decoded = self._console_partial + chunk.decode("utf-8", "replace")
        parts = decoded.split("\n")
        self._console_partial = parts.pop()
        self._console_lines.extend(parts)
        if len(self._console_lines) > 800:
            self._console_lines = self._console_lines[-800:]
        show = list(self._console_lines)
        if self._console_partial:
            show.append(self._console_partial)
        self._console_render(show)

    def _console_render(self, lines: list[str], dim: bool = False) -> None:
        text = self._console_text
        follow = bool(self._console_follow.get()) if hasattr(
            self, "_console_follow") else True
        at_bottom = False
        top = 0.0
        try:
            top, bottom = text.yview()
            at_bottom = bottom >= 0.999
        except tk.TclError:
            pass
        text.configure(state="normal")
        text.delete("1.0", "end")
        for line in lines:
            upper = line.upper()
            tag = "dim" if dim else ("err" if any(word in upper for word in (
                "ERROR", "SEVERE", "FATAL", "EXCEPTION")) else
                "warn" if "WARN" in upper else "")
            text.insert("end", line + "\n", tag or ())
        text.configure(state="disabled")
        if follow or at_bottom:
            text.see("end")
        else:
            text.yview_moveto(top)

    def _diagnose_console(self) -> None:
        path = getattr(self, "_console_path", None)
        if path is None or not path.is_file():
            show_info(self, "Diagnóstico",
                      "Todavía no hay un registro del juego para analizar.")
            return
        issues = diagnostics.analyze_log(path)
        if not issues:
            show_info(
                self, "Diagnóstico",
                "No se detectaron errores conocidos en el registro.\n\n"
                "Si Minecraft se cerró, revisá las últimas líneas de la "
                "consola o el crash report de la instancia.")
            return
        message = "\n\n".join(f"{item['title']}\n{item['hint']}"
                              for item in issues)
        show_warning(self, "Diagnóstico de Minecraft", message)

    def _tab_logs(self, parent) -> None:
        toolbar = tk.Frame(parent, bg=PANEL)
        toolbar.pack(fill="x", pady=(0, 8))
        section(toolbar, "Registros del juego").pack(side="left", fill="x",
                                                     expand=True)
        Button(toolbar, "Abrir carpeta", kind="quiet",
               command=lambda: self._open_kind("logs"), width=108, height=28,
               font=(FONT, 8)).pack(side="right")
        latest = self.store.latest_log(self._current)
        if latest:
            Button(toolbar, "Último log", command=lambda: _open_path(latest),
                   width=92, height=28, font=(FONT, 8)).pack(side="right",
                                                             padx=(0, 6))
        scroll = ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        folder = self.store.game_dir(self._current) / "logs"
        try:
            files = sorted((p for p in folder.glob("*.log") if p.is_file()),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            files = []
        if not files:
            label(scroll.content, "Todavía no hay registros del juego.", size=9,
                  color=FAINT).pack(anchor="w", pady=8)
            return
        for log in files[:40]:
            row = tk.Frame(scroll.content, bg=PANEL,
                           highlightbackground=BORDER_SOFT, highlightthickness=1)
            row.pack(fill="x", pady=(0, 5))
            info = tk.Frame(row, bg=PANEL)
            info.pack(side="left", fill="x", expand=True, padx=10, pady=7)
            label(info, log.name, size=9, color=TEXT).pack(anchor="w")
            try:
                when = time.strftime("%Y-%m-%d %H:%M",
                                     time.localtime(log.stat().st_mtime))
            except OSError:
                when = ""
            label(info, when, size=8, color=FAINT).pack(anchor="w", pady=(2, 0))
            Button(row, "Abrir", kind="quiet",
                   command=lambda path=log: _open_path(path), width=62,
                   height=26, font=(FONT, 8)).pack(side="right", padx=(0, 8))

    # Actions --------------------------------------------------------
    def _new_instance(self) -> None:
        if self._busy:
            return
        dialog = InstanceCreateDialog(self)
        self.wait_window(dialog)
        instance = dialog.result
        if not instance:
            return
        self._current = instance
        self._tab = "general"
        self._refresh()
        self._status(f"Instancia creada con Minecraft {instance['version']}")

    def _import_instance(self) -> None:
        if self._busy:
            return
        chosen = filedialog.askopenfilename(
            parent=self, title="Importar instancia o modpack",
            filetypes=[("Paquetes", "*.zip *.mrpack"),
                       ("Todos", "*.*")])
        if not chosen:
            return
        path = Path(chosen)
        self._busy = True
        self._set_buttons(False)
        self.progress["value"] = 0
        self._status("Importando...")

        def work():
            try:
                if modrinth.is_mrpack(path):
                    instance = modrinth.import_mrpack(
                        path, self.store,
                        on_status=lambda text: self._queue.put(("status", text)),
                        on_progress=lambda frac, text: self._queue.put(
                            ("progress", (frac * 100, text))),
                        cancel_event=None)
                else:
                    instance = self.store.import_zip(path)
                self._queue.put(("imported", instance))
            except Exception as exc:
                self._queue.put(("error", str(exc)))
            finally:
                self._queue.put(("busy_done", None))

        threading.Thread(target=work, daemon=True).start()

    def _export_instance(self) -> None:
        if not self._current or self._busy:
            return
        if self.app._game is not None:
            show_warning(self, "Instancia",
                         "Cerrá Minecraft antes de exportar una instancia.")
            return
        safe = "".join(ch for ch in self._current["name"]
                       if ch.isalnum() or ch in " -_") or "instancia"
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Exportar instancia", defaultextension=".zip",
            initialfile=f"{safe}.zip", filetypes=[("Instancia Blockys", "*.zip")])
        if not chosen:
            return
        instance = self._current
        target = Path(chosen)
        self._busy = True
        self._set_buttons(False)
        self._status("Exportando instancia...")

        def work():
            try:
                self.store.export(instance, target)
                self._queue.put(("exported", target.name))
            except (OSError, instances.InstanceError) as exc:
                self._queue.put(("export_error", str(exc)))
            except Exception as exc:
                self._queue.put(("export_error", f"Error inesperado: {exc}"))
            finally:
                self._queue.put(("busy_done", None))

        threading.Thread(target=work, daemon=True).start()

    def _duplicate_instance(self) -> None:
        if not self._current or self._busy:
            return
        if self.app._game is not None:
            show_warning(self, "Instancia",
                         "Cerrá Minecraft antes de copiar una instancia.")
            return
        instance_id = self._current["id"]
        self._busy = True
        self._set_buttons(False)
        self._status("Copiando instancia...")

        def work():
            try:
                copy = self.store.duplicate(instance_id)
            except instances.InstanceError as exc:
                self._queue.put(("duplicate_error", str(exc)))
            except Exception as exc:
                self._queue.put(("duplicate_error",
                                 f"Error inesperado: {exc}"))
            else:
                self._queue.put(("duplicated", copy))
            finally:
                self._queue.put(("busy_done", None))

        threading.Thread(target=work, daemon=True).start()

    def _delete_instance(self) -> None:
        if not self._current or self._busy:
            return
        if self.app._game is not None:
            show_warning(self, "Instancia",
                         "Cerrá Minecraft antes de eliminar una instancia.")
            return
        if not show_confirm(
                self, "Eliminar instancia",
                f"¿Eliminar {self._current['name']} y todos sus archivos? "
                "Esta acción no se puede deshacer.", "Eliminar"):
            return
        deleted = self._current["name"]
        was_active = (self.app._instance
                      and self.app._instance.get("id") == self._current["id"])
        self.store.remove(self._current["id"])
        self._current = self.store.selected()
        if was_active:
            self.app._instance = None
            self.app._apply_instance(self._current)
            self.app._refresh_instances()
        self._refresh()
        self._status(f"Instancia eliminada: {deleted}")

    def _play_current(self) -> None:
        if not self._current or self._busy:
            return
        if self.app._game is not None or self.app._busy:
            show_warning(self, "Minecraft",
                         "Ya hay un inicio en curso. Esperá a que termine.")
            return
        instance = self._current
        self.store.select(instance["id"])
        self._close()
        self.app._refresh_instances(select_id=instance["id"])
        self.app._apply_instance(instance)
        self.app._play()

    def _set_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.play_btn, self.export_btn):
            button.configure(state=state)

    def _close(self) -> None:
        if self._busy:
            self._status("Esperá a que termine la importación...")
            return
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.app._refresh_after_instances()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "status":
                    self._status(str(payload))
                elif kind == "progress":
                    value, text = payload
                    self.progress["value"] = value
                    self._status(str(text))
                elif kind == "imported":
                    self._current = payload
                    self._tab = "general"
                    self._refresh()
                    self.progress["value"] = 100
                    self._status(f"Importada: {payload.get('name')}")
                    self.app._refresh_instances(select_id=payload["id"])
                elif kind == "error":
                    self.progress["value"] = 0
                    self._status("Error al importar")
                    show_error(self, "Importar", str(payload))
                elif kind == "update_result":
                    count = len(payload)
                    self._busy = False
                    self._set_buttons(True)
                    self._status("Sin actualizaciones disponibles" if not count
                                 else f"{count} archivo(s) actualizado(s)")
                    if count:
                        self._show_tab(self._tab, force=True)
                elif kind == "update_error":
                    self._busy = False
                    self._set_buttons(True)
                    self._status("No se pudieron revisar las actualizaciones")
                    show_error(self, "Actualizar", str(payload))
                elif kind == "exported":
                    self._status(f"Exportada a {payload}")
                    show_info(self, "Instancia exportada",
                              "La instancia se guardó con sus mods y "
                              "configuraciones.")
                elif kind == "export_error":
                    self._status("Error al exportar")
                    show_error(self, "Exportar",
                               f"No se pudo exportar: {payload}")
                elif kind == "duplicated":
                    if payload is not None:
                        self._current = payload
                        self._refresh()
                        self._status(f"Duplicada como {payload['name']}")
                elif kind == "duplicate_error":
                    self._status("Error al copiar")
                    show_error(self, "Duplicar instancia", str(payload))
                elif kind == "server_status":
                    widget, result, error = payload
                    try:
                        if result:
                            motd = result.get("motd") or ""
                            text = (f"En línea · {result['online']}/"
                                    f"{result['max']} · {result['latency']} ms")
                            if motd:
                                text += f" · {motd[:56]}"
                            widget.configure(text=text, fg=GRASS)
                            self._status(f"{result['online']} jugadores en "
                                         f"{result.get('version') or 'el servidor'}")
                        else:
                            widget.configure(text=f"Sin conexión · {error}",
                                             fg=DANGER)
                            self._status(str(error))
                    except tk.TclError:
                        pass
                elif kind == "busy_done":
                    self._busy = False
                    self._set_buttons(True)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._poll_job = self.after(100, self._poll)


class InstanceCreateDialog(tk.Toplevel):
    def __init__(self, manager: InstancesDialog):
        super().__init__(manager)
        self.manager = manager
        self.app = manager.app
        self.store = manager.store
        self.result: dict | None = None
        self._manifest_job = None
        self.title("Nueva instancia · Blockys")
        width, height = 580, 610
        x = manager.winfo_rootx() + max(0, (manager.winfo_width() - width) // 2)
        y = manager.winfo_rooty() + max(0, (manager.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.transient(manager)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self._build()
        set_app_icon(self)
        self.after(60, lambda: enable_dark_titlebar(self))

        def focus_name():
            try:
                self.name_entry.focus_set()
            except tk.TclError:
                pass

        self.after(80, focus_name)

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 12))
        label(header, "NUEVA INSTANCIA", color=TEXT,
              font=(DISPLAY, 19)).pack(anchor="w")
        label(header, "Elegí nombre, versión y cargador desde el principio.",
              size=8, color=FAINT).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        body.pack(fill="both", expand=True, padx=24)
        inner = tk.Frame(body, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=18, pady=16)

        label(inner, "Nombre", size=9, color=TEXT).pack(fill="x", pady=(0, 5))
        self.name_var = tk.StringVar(value="Nueva instancia")
        self.name_entry = Input(inner, textvariable=self.name_var)
        self.name_entry.pack(fill="x")

        label(inner, "Versión de Minecraft", size=9, color=TEXT).pack(
            fill="x", pady=(14, 5))
        self.version_picker = VersionPicker(
            inner, self.app.manifest,
            initial=self.app.settings.get("selected_version", ""),
            height=40)
        self.version_picker.pack(fill="x")

        row = tk.Frame(inner, bg=PANEL)
        row.pack(fill="x", pady=(14, 0))
        left = tk.Frame(row, bg=PANEL)
        left.pack(side="left", fill="x", expand=True)
        right = tk.Frame(row, bg=PANEL)
        right.pack(side="left", fill="x", expand=True, padx=(14, 0))
        label(left, "Cargador", size=9, color=TEXT).pack(fill="x", pady=(0, 5))
        self.loader_combo = Select(left, values=LOADER_LABELS, height=38)
        self.loader_combo.pack(fill="x")
        self.loader_combo.set("Vanilla")
        label(right, "Versión del cargador", size=9, color=TEXT).pack(
            fill="x", pady=(0, 5))
        self.loader_version_var = tk.StringVar()
        self.loader_version_entry = Input(right,
                                          textvariable=self.loader_version_var)
        self.loader_version_entry.pack(fill="x")

        self.loader_hint = label(
            inner,
            "El cargador usa su última versión estable si dejás este campo vacío.",
            size=8, color=FAINT, wrap=500)
        self.loader_hint.pack(fill="x", pady=(6, 0))
        self.loader_combo.bind("<<ComboboxSelected>>",
                               lambda _event: self._toggle_loader_version())
        self._toggle_loader_version()

        self.error_var = tk.StringVar()
        tk.Label(inner, textvariable=self.error_var, bg=PANEL, fg=DANGER,
                 font=(FONT, 8), anchor="w").pack(fill="x", pady=(10, 0))

        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=24, pady=14)
        Button(footer, "Cancelar", command=self._cancel, width=104,
               height=38).pack(side="right", padx=(8, 0))
        self.create_btn = Button(footer, "Crear instancia", kind="primary",
                                 command=self._create, width=170, height=38)
        self.create_btn.pack(side="right")
        if not (self.app.manifest or {}).get("versions"):
            self.create_btn.configure(state="disabled")
            self.error_var.set(
                "Todavía no se cargaron las versiones. Esperá unos segundos.")
            self._manifest_job = self.after(700, self._wait_manifest)

    def _wait_manifest(self) -> None:
        self._manifest_job = None
        if not self.winfo_exists():
            return
        manifest = self.app.manifest
        if not (manifest or {}).get("versions"):
            self._manifest_job = self.after(700, self._wait_manifest)
            return
        self.version_picker.set_manifest(manifest)
        self.create_btn.configure(state="normal")
        self.error_var.set("")

    def _toggle_loader_version(self) -> None:
        vanilla = self.loader_combo.get().strip().lower() == "vanilla"
        self.loader_version_entry.configure(state="disabled" if vanilla else "normal")
        self.loader_hint.configure(
            text=("Vanilla no necesita una versión de cargador."
                  if vanilla else
                  "El cargador usa su última versión estable si dejás este campo vacío."))

    def _create(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            self.error_var.set("Escribí un nombre para la instancia.")
            return
        version_id = self.version_picker.selected_id()
        if not version_id:
            self.error_var.set("Elegí una versión de Minecraft.")
            return
        loader = LOADER_BY_LABEL.get(self.loader_combo.get().strip().lower(),
                                     "vanilla")
        loader_version = (self.loader_version_var.get().strip()
                          if loader != "vanilla" else "")
        try:
            instance = self.store.create(name, version_id, loader,
                                         self.app.settings)
        except instances.InstanceError as exc:
            self.error_var.set(str(exc))
            return
        instance["loader_version"] = loader_version
        instance["resolved_version"] = ""
        self.store.save()
        self.result = instance
        self._finish()

    def _cancel(self) -> None:
        self.result = None
        self._finish()

    def _finish(self) -> None:
        manager = self.manager
        if self._manifest_job is not None:
            try:
                self.after_cancel(self._manifest_job)
            except tk.TclError:
                pass
            self._manifest_job = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        try:
            manager.grab_set()
            manager.lift()
        except tk.TclError:
            pass


class ModrinthDialog(tk.Toplevel):
    def __init__(self, parent: InstancesDialog, instance: dict,
                 project_type: str, on_installed=None):
        super().__init__(parent)
        self.parent_dialog = parent
        self.instance = instance
        self.project_type = project_type
        self.on_installed = on_installed
        self._queue: queue.Queue = queue.Queue()
        self._poll_job = None
        self._installing: set[str] = set()
        self._installed_any = False
        self._query = ""
        self._page = 0
        self._page_size = 20
        self._sort_index = "relevance"
        self._search_token = 0
        self._total_hits = 0
        titles = {"mod": "Mods en Modrinth", "resourcepack": "Paquetes en Modrinth",
                  "shader": "Shaders en Modrinth"}
        self.title(f"{titles.get(project_type, 'Modrinth')} · Blockys")
        area_x, area_y, area_w, area_h = work_area_rect()
        width = min(800, area_w - 80)
        height = min(650, area_h - 80)
        self.geometry(f"{width}x{height}"
                      f"+{area_x + (area_w - width) // 2}"
                      f"+{area_y + max(0, (area_h - height - 40) // 2)}")
        self.minsize(620, 460)
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<MouseWheel>", self._on_wheel)
        self._build()
        self._poll_job = self.after(80, self._poll)
        set_app_icon(self)
        self.after(60, lambda: enable_dark_titlebar(self))
        self.after(120, lambda: self._search(""))

    def _on_wheel(self, event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                widget.scroll(event)
                return
            widget = getattr(widget, "master", None)

    def destroy(self) -> None:
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
        super().destroy()

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(18, 12))
        section(header, "Modrinth").pack(side="left", fill="x", expand=True)
        Button(header, "Cerrar", command=self._close, width=90,
               height=32).pack(side="right")
        context = tk.Frame(self, bg=BG)
        context.pack(fill="x", padx=24)
        loader = instances.LOADERS.get(self.instance.get("loader"), "Vanilla")
        text = f"{loader} · Minecraft {self.instance.get('version')}"
        if self.project_type == "mod" and self.instance.get("loader") == "vanilla":
            text += " · sin cargador: el mod no se cargará"
        label(context, text, size=8,
              color=WARN if self.instance.get("loader") == "vanilla" else MUTED).pack(
            anchor="w")
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=24, pady=(10, 10))
        self.query_var = tk.StringVar()
        entry = Input(row, textvariable=self.query_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>",
                   lambda _event: self._search(self.query_var.get(), 0))
        self.sort_labels = {"Relevancia": "relevance", "Descargas": "downloads",
                            "Seguidos": "follows", "Recientes": "newest",
                            "Actualizados": "updated"}
        self.sort_combo = Select(row, values=list(self.sort_labels),
                                 height=34, width=124)
        self.sort_combo.pack(side="left", padx=(8, 0))
        self.sort_combo.set("Relevancia")
        self.sort_combo.bind("<<ComboboxSelected>>",
                             lambda _event: self._on_sort())
        self.search_btn = Button(row, "Buscar", kind="primary",
                                 command=lambda: self._search(
                                     self.query_var.get(), 0),
                                 width=96, height=34).pack(side="left",
                                                           padx=(8, 0))
        self.status_var = tk.StringVar(value="Cargando Modrinth...")
        tk.Label(self, textvariable=self.status_var, bg=BG, fg=MUTED,
                 font=(FONT, 8), anchor="w").pack(fill="x", padx=24)
        self.results = ScrollFrame(self, bg=BG)
        self.results.pack(fill="both", expand=True, padx=(24, 10), pady=(8, 8))
        self.pager = tk.Frame(self, bg=BG)
        self.pager.pack(fill="x", padx=24, pady=(0, 14))
        self.page_label = tk.Label(self.pager, text="", bg=BG, fg=FAINT,
                                   font=(MONO, 8))
        self.page_label.pack(side="left")
        self.next_btn = Button(self.pager, "Siguiente", kind="quiet",
                               command=lambda: self._change_page(1), width=92,
                               height=28, font=(FONT, 8))
        self.next_btn.pack(side="right")
        self.prev_btn = Button(self.pager, "Anterior", kind="quiet",
                               command=lambda: self._change_page(-1), width=86,
                               height=28, font=(FONT, 8))
        self.prev_btn.pack(side="right", padx=(0, 6))
        self.query_var.set("")
        self._update_pager()

    def _on_sort(self) -> None:
        value = self.sort_labels.get(self.sort_combo.get(), "relevance")
        if value == self._sort_index:
            return
        self._sort_index = value
        self._search(self._query, 0)

    def _change_page(self, delta: int) -> None:
        pages = max(1, (self._total_hits + self._page_size - 1)
                    // self._page_size)
        target = max(0, min(pages - 1, self._page + delta))
        if target != self._page:
            self._search(self._query, target)

    def _update_pager(self) -> None:
        pages = max(1, (self._total_hits + self._page_size - 1)
                    // self._page_size)
        self.page_label.configure(
            text=f"Página {self._page + 1} de {pages} · {self._total_hits} resultados")
        self.prev_btn.configure(
            state="normal" if self._page > 0 else "disabled")
        self.next_btn.configure(
            state="normal" if self._page + 1 < pages else "disabled")

    def _search(self, query: str, page: int = 0) -> None:
        if not self.winfo_exists():
            return
        self._query = (query or "").strip()
        self._page = max(0, page)
        self.status_var.set("Buscando...")
        for child in self.results.content.winfo_children():
            child.destroy()
        loader = self.instance.get("loader", "vanilla")
        version = str(self.instance.get("version") or "")
        self._search_token += 1
        token = self._search_token
        sort = self._sort_index
        offset = self._page * self._page_size

        def work():
            try:
                data = modrinth.search(
                    self._query, self.project_type,
                    loader=loader if self.project_type == "mod" else "",
                    game_version=version, limit=self._page_size,
                    offset=offset, index=sort)
                self._queue.put(("results", {"data": data, "token": token,
                                             "page": self._page}))
            except Exception as exc:
                self._queue.put(("search_error", {"msg": str(exc),
                                                  "token": token}))

        threading.Thread(target=work, daemon=True).start()

    def _result_row(self, hit: dict) -> None:
        row = tk.Frame(self.results.content, bg=PANEL,
                       highlightbackground=BORDER_SOFT, highlightthickness=1)
        row.pack(fill="x", pady=(0, 7))
        info = tk.Frame(row, bg=PANEL)
        info.pack(side="left", fill="x", expand=True, padx=12, pady=9)
        title = hit.get("title") or hit.get("slug") or "Proyecto"
        label(info, title, size=10, color=TEXT,
              font=(DISPLAY, 11)).pack(anchor="w")
        downloads = hit.get("downloads") or 0
        author = hit.get("author") or ""
        label(info, f"{author} · {downloads:,} descargas".replace(",", "."),
              size=8, color=ACCENT).pack(anchor="w", pady=(2, 0))
        description = (hit.get("description") or "").strip()
        if description:
            label(info, description[:180], size=8, color=MUTED, wrap=500).pack(
                anchor="w", pady=(4, 0))
        project_id = hit.get("project_id") or hit.get("slug")
        if project_id:
            Button(row, "Instalar", kind="primary",
                   command=lambda pid=project_id, name=title: self._install(
                       pid, name), width=92, height=30, font=(DISPLAY, 9)).pack(
                side="right", padx=(6, 10))

    def _install(self, project_id: str, title: str) -> None:
        if project_id in self._installing:
            return
        self._installing.add(project_id)
        self.status_var.set(f"Instalando {title}...")

        def work():
            try:
                path = modrinth.install(project_id, self.instance,
                                        self.project_type,
                                        on_status=lambda text: self._queue.put(
                                            ("status", text)))
                self._queue.put(("installed", (title, str(path))))
            except Exception as exc:
                self._queue.put(("install_error", str(exc)))
            finally:
                self._queue.put(("install_done", project_id))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "results":
                    payload = payload if isinstance(payload, dict) else {}
                    if payload.get("token") != self._search_token:
                        continue
                    data = payload.get("data") or {}
                    self._page = int(payload.get("page", self._page))
                    for child in self.results.content.winfo_children():
                        child.destroy()
                    hits = data.get("hits") or []
                    self._total_hits = int(data.get("total_hits")
                                           or len(hits))
                    self.status_var.set(f"{self._total_hits} resultados")
                    if not hits:
                        label(self.results.content, "Sin resultados.",
                              size=9, color=FAINT).pack(anchor="w", pady=8)
                    for hit in hits:
                        self._result_row(hit)
                    self._update_pager()
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "search_error":
                    payload = payload if isinstance(payload, dict) else {}
                    if payload.get("token") != self._search_token:
                        continue
                    self.status_var.set("Error al buscar")
                    show_error(self, "Modrinth",
                               str(payload.get("msg") or payload))
                elif kind == "installed":
                    title, path = payload
                    self.status_var.set(f"{title} instalado")
                    self._installed_any = True
                    if self.on_installed:
                        self.on_installed()
                elif kind == "install_error":
                    self.status_var.set("Error al instalar")
                    show_error(self, "Modrinth", str(payload))
                elif kind == "install_done":
                    self._installing.discard(payload)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._poll_job = self.after(90, self._poll)

    def _close(self) -> None:
        if self._installing:
            self.status_var.set("Esperá a que termine la instalación...")
            return
        parent = self.parent_dialog
        if parent._modrinth_window is self:
            parent._modrinth_window = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if self._installed_any and self.on_installed:
            self.on_installed()
        try:
            parent.grab_set()
            parent.lift()
        except tk.TclError:
            pass


def show_confirm(parent, title: str, message: str, ok_text: str) -> bool:
    from . import ui
    return ui.ask_confirm(parent, title, message, ok_text=ok_text)
