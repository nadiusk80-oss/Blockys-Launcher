from __future__ import annotations

import os
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog

from PIL import Image, ImageTk

from . import (
    APP_TITLE,
    __version__,
    accounts,
    backups,
    diagnostics,
    instances,
    launch,
    loaders,
    net,
    paths,
    skins,
    ui,
    updates,
    versions,
)
from .accounts import AuthError, ProfileStore
from .ui import (
    ACCENT,
    ACCENT_INK,
    BG,
    BORDER,
    BORDER_SOFT,
    CARD,
    DANGER,
    DISPLAY,
    FAINT,
    FONT,
    GRASS,
    LOG_BG,
    MONO,
    MUTED,
    PANEL,
    TEXT,
    WARN,
)

CATEGORY_ORDER = ("all", "release", "snapshot", "old_beta", "old_alpha")
CATEGORY_SHORT = {"all": "Todas", "release": "Lanzamientos",
                  "snapshot": "Experimentales", "old_beta": "Betas",
                  "old_alpha": "Alphas"}
PRETTY_TYPE = {"release": "Lanzamiento", "snapshot": "Snapshot",
               "old_beta": "Beta clásica", "old_alpha": "Alpha clásica"}
TYPE_COLOR = {"release": FAINT, "snapshot": WARN, "old_beta": ACCENT,
              "old_alpha": MUTED}


def _int_value(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self._settings_existed = paths.SETTINGS_FILE.is_file()
        self.settings = paths.load_settings()
        net.configure_proxy(self.settings)
        self.store = ProfileStore()
        self.instance_store = instances.InstanceStore()
        self._instance: dict | None = None
        self.manifest: dict | None = None
        self._version_map: dict[str, dict] = {}
        self._profile_ids: list[str] = []
        self._stage_photo = None
        self._busy = False
        self._loading_versions = False
        self._pending_force_reload = False
        self._game = None
        self._game_log = None
        self._auth_cancel: threading.Event | None = None
        self._auth_window: tk.Toplevel | None = None
        self._auth_status: tk.StringVar | None = None
        self._cancel = threading.Event()
        self._stage_key = None
        self._stage_job = None
        self._accounts_window: tk.Toplevel | None = None
        self._help_window: tk.Toplevel | None = None
        self._welcome_window: tk.Toplevel | None = None
        self._settings_window: tk.Toplevel | None = None
        self._settings_job = None
        self._crash_reported = False
        self._grid_cols = 0
        self._grid_signature = None
        self._grid_job = None
        self._selected_tile = None
        self._quick_play_override: tuple[str, str] | None = None
        self._version_category = self.settings.get("version_type", "release")
        if self._version_category not in CATEGORY_ORDER:
            self._version_category = "release"
        self._instance_search = ""
        self._instance_sort = self.settings.get("instance_sort", "name")
        if self._instance_sort not in ("name", "recent", "version", "group"):
            self._instance_sort = "name"
        collapsed = self.settings.get("collapsed_groups", [])
        self._collapsed_groups = set(collapsed) if isinstance(collapsed, list) else set()
        self._icon_cache: dict[tuple[str, int, int], object] = {}
        self.events: queue.Queue = queue.Queue()
        self._update_check_started = False
        self._update_downloading = False
        self._update_cancel: threading.Event | None = None

        self.title(f"{APP_TITLE} · Minecraft Java")
        area_x, area_y, area_w, area_h = ui.work_area_rect()
        width = min(1180, area_w - 60)
        height = min(700, area_h - 70)
        x = area_x + (area_w - width) // 2
        y = area_y + max(0, (area_h - height - 40) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(1060, area_w - 80), min(560, height))
        self.configure(bg=BG)
        ui.apply_theme(self)
        ui.set_app_icon(self)
        self.after(120, lambda: ui.enable_dark_titlebar(self))
        self._pump_job = None
        self._build()
        for var in (self.width_var, self.height_var, self.game_dir_var):
            var.trace_add("write", lambda *_args: self._queue_settings_save())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(80, self._pump)
        self.bind("<F5>", lambda _event: self._load_versions(force=True))
        self.bind("<F1>", lambda _event: self._show_help())
        self.bind("<Control-n>", lambda _event: self._add_instance())
        self.bind("<Control-comma>", lambda _event: self._open_settings())
        self._refresh_accounts()
        self._refresh_instances()
        selected_instance = self.instance_store.selected()
        if selected_instance is not None:
            self._apply_instance(selected_instance)
        self._load_versions()
        if self.settings.get("check_updates", True):
            self.after(3200, self._auto_check_updates)
        if (not self._settings_existed
                and not self.settings.get("onboarding_done")
                and not self.instance_store.instances):
            self.after(450, self._maybe_welcome)

    def _build(self) -> None:
        with Image.open(Path(__file__).with_name("assets") / "icon.png") as source:
            icon = source.convert("RGBA")

        def photo(size: int):
            copy = icon.copy()
            copy.thumbnail((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(copy)

        self._logo_photo = photo(52)
        self._tile_photo = photo(82)
        self._detail_photo = photo(96)
        self._account_head_photo = ImageTk.PhotoImage(
            skins.placeholder_head(30))

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=28, pady=(14, 10))

        logo = tk.Frame(header, bg=BG, width=52, height=52)
        logo.pack(side="left")
        logo.pack_propagate(False)
        tk.Label(logo, image=self._logo_photo, bg=BG, bd=0).pack(expand=True)

        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", padx=(14, 0), anchor="s")
        tk.Label(titles, text="BLOCKYS", bg=BG, fg=TEXT,
                 font=(DISPLAY, 23)).pack(anchor="w")
        tk.Label(titles, text=ui.tracked("MINECRAFT JAVA"), bg=BG, fg=FAINT,
                 font=(DISPLAY, 7)).pack(anchor="w", pady=(1, 0))

        account = tk.Frame(header, bg=BG)
        account.pack(side="right", anchor="s")
        head = tk.Frame(account, bg=CARD, width=34, height=34,
                        highlightbackground=BORDER_SOFT, highlightthickness=1)
        head.pack(side="left")
        head.pack_propagate(False)
        self.account_head = tk.Label(head, image=self._account_head_photo,
                                     bg=CARD, bd=0)
        self.account_head.pack(expand=True)
        self.header_profile_combo = ui.Select(
            account, values=[], height=34, width=172,
            placeholder="Sin cuenta")
        self.header_profile_combo.pack(side="left", padx=(8, 0))
        self.header_profile_combo.bind("<<ComboboxSelected>>",
                                       self._on_header_profile_change)
        ui.Button(account, "Cuentas", kind="quiet", command=self._open_accounts,
                  width=76, height=34, font=(FONT, 8)).pack(
            side="left", padx=(6, 0))

        toolbar = tk.Frame(header, bg=BG)
        toolbar.pack(side="left", padx=(20, 0), anchor="s")
        for text, command, width in (
                ("Añadir instancia", self._add_instance, 112),
                ("Carpetas", self._open_instances_folder, 76),
                ("Ajustes", self._open_settings, 70),
                ("Ayuda", self._show_help, 54),
                ("Actualizar", self._toolbar_update, 76)):
            ui.Button(toolbar, text, command=command, width=width, height=34,
                      font=(FONT, 8)).pack(side="left", padx=(0, 6))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=28, pady=(0, 14))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, minsize=344)

        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew")
        right_panel = tk.Frame(body, bg=PANEL, width=344,
                               highlightbackground=BORDER, highlightthickness=1)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(18, 0))
        right_panel.grid_propagate(False)

        self._build_instance_area(left)
        self._build_right(right_panel)
        self.bind("<MouseWheel>", self._on_main_wheel)
        self._set_version_category(self._version_category, persist=False)
        self._toggle_resolution()
        self._log("Listo. Elegí una instancia y pulsá JUGAR.", "dim")

    def _build_instance_area(self, parent) -> None:
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", pady=(2, 8))
        ui.section(head, "Instancias").pack(side="left", fill="x", expand=True)
        self.instances_count = tk.Label(head, text="", bg=BG, fg=FAINT,
                                        font=(FONT, 8))
        self.instances_count.pack(side="right")

        tools = tk.Frame(parent, bg=BG)
        tools.pack(fill="x", pady=(0, 8))
        self.search_var = tk.StringVar()
        self.search_box = ui.Input(tools, textvariable=self.search_var)
        self.search_box.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_box.entry.insert(0, "Buscar instancia...")
        self.search_box.entry.configure(fg=FAINT)
        self.search_box.entry.bind("<FocusIn>", self._search_focus)
        self.search_box.entry.bind("<FocusOut>", self._search_blur)
        self.search_box.entry.bind("<KeyRelease>",
                                   lambda _event: self._on_instance_search())
        sort_labels = {"name": "Nombre", "recent": "Reciente",
                       "version": "Versión", "group": "Grupo"}
        self.sort_combo = ui.Select(tools, values=list(sort_labels.values()),
                                    height=32, width=118)
        self.sort_combo.pack(side="right")
        self.sort_combo.set(sort_labels.get(self._instance_sort, "Nombre"))
        self.sort_combo.bind("<<ComboboxSelected>>",
                             lambda _event: self._on_sort_change())

        self.status_bar = tk.Frame(parent, bg=BG)
        self.status_bar.pack(side="bottom", fill="x", pady=(10, 0))
        self.progress = ui.Progress(self.status_bar, maximum=100, height=6)
        self.progress.configure(width=110)
        self.progress.pack(side="left", padx=(0, 10))
        self.status_var = tk.StringVar(value="Listo para jugar")
        tk.Label(self.status_bar, textvariable=self.status_var, bg=BG, fg=MUTED,
                 font=(FONT, 9), anchor="w").pack(side="left", fill="x",
                                                 expand=True)
        self.log_toggle = ui.Button(self.status_bar, "Registro", kind="quiet",
                                    command=self._toggle_log, width=76,
                                    height=26, font=(FONT, 8))
        self.log_toggle.pack(side="right")
        self.cancel_btn = ui.Button(self.status_bar, "Cancelar", kind="quiet",
                                    command=self._cancel_launch, width=74,
                                    height=26, font=(FONT, 8))

        self.log_frame = tk.Frame(parent, bg=LOG_BG,
                                  highlightbackground=BORDER,
                                  highlightthickness=1)
        self.log_text = tk.Text(self.log_frame, bg=LOG_BG, fg=TEXT,
                                insertbackground=TEXT, relief="flat", bd=0,
                                height=5, wrap="word", font=(MONO, 9),
                                padx=12, pady=6, state="disabled",
                                highlightthickness=0,
                                selectbackground="#3c3325")
        log_scroll = ui.ThinScroll(self.log_frame, command=self.log_text.yview,
                                   bg=LOG_BG, width=8)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y", padx=(0, 4), pady=4)
        self.log_text.pack(side="left", fill="both", expand=True)
        for tag, color in (("err", DANGER), ("ok", GRASS), ("dim", FAINT),
                           ("warn", WARN)):
            self.log_text.tag_configure(tag, foreground=color)

        self.grid_scroll = ui.ScrollFrame(parent, bg=BG)
        self.grid_scroll.pack(fill="both", expand=True)
        self.grid_scroll.canvas.bind("<Configure>", self._on_grid_resize)

    def _on_main_wheel(self, event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if isinstance(widget, ui.ScrollFrame):
                widget.scroll(event)
                return
            widget = getattr(widget, "master", None)

    def _on_grid_resize(self, _event=None) -> None:
        if self._grid_job is not None:
            try:
                self.after_cancel(self._grid_job)
            except tk.TclError:
                pass
        self._grid_job = self.after(90, self._render_instance_grid)

    def _build_left(self, parent) -> None:
        inner = tk.Frame(parent, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=20, pady=14)

        head = tk.Frame(inner, bg=PANEL)
        head.pack(fill="x")
        ui.section(head, "Cuenta").pack(side="left", fill="x", expand=True)
        self.delete_btn = ui.Button(head, "Eliminar", kind="danger",
                                    command=self._delete_account, width=68,
                                    height=20, font=(FONT, 8))
        self.delete_btn.pack(side="right")

        self.profile_combo = ui.Select(inner, values=[], height=40,
                                       placeholder="Sin cuenta")
        self.profile_combo.pack(fill="x", pady=(6, 8))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_change)

        row = tk.Frame(inner, bg=PANEL)
        row.pack(fill="x")
        ui.Button(row, "Cuenta local", command=self._add_offline, height=34).pack(
            side="left", fill="x", expand=True)
        ui.Button(row, "Microsoft", command=self._microsoft_login,
                  height=34).pack(side="left", fill="x", expand=True,
                                  padx=(8, 0))

        ui.divider(inner, top=12, bottom=8)

        self.stage_holder = tk.Frame(inner, bg=PANEL, height=216)
        self.stage_holder.pack(fill="x")
        self.stage_holder.pack_propagate(False)
        self.stage_holder.bind("<Configure>", self._on_stage_resize)
        self.stage_label = tk.Label(self.stage_holder, bg=PANEL, bd=0)
        self.stage_label.place(relx=0.5, rely=0.5, anchor="center")

        self.skin_name = tk.Label(inner, text="", bg=PANEL, fg=TEXT,
                                  font=(DISPLAY, 16))
        self.skin_name.pack(pady=(8, 0))
        self.skin_kind = tk.Label(inner, text="", bg=PANEL, fg=FAINT,
                                  font=(FONT, 8))
        self.skin_kind.pack()
        self.skin_hint = tk.Label(inner, text="", bg=PANEL, fg=MUTED,
                                  font=(FONT, 8), wraplength=310,
                                  justify="center")
        self.skin_hint.pack(pady=(3, 0))

        actions = tk.Frame(inner, bg=PANEL)
        actions.pack(fill="x", pady=(9, 0))
        self.import_btn = ui.Button(actions, "Importar skin",
                                    command=self._import_skin, height=34)
        self.import_btn.pack(side="left", fill="x", expand=True)
        self.remove_btn = ui.Button(actions, "Quitar", command=self._remove_skin,
                                    width=82, height=34)
        self.remove_btn.pack(side="left", padx=(8, 0))

        variant_row = tk.Frame(inner, bg=PANEL)
        variant_row.pack(fill="x", pady=(7, 2))
        tk.Label(variant_row, text="Variante", bg=PANEL, fg=FAINT,
                 font=(FONT, 8)).pack(side="left")
        self.variant_var = tk.StringVar(value="Clásica")
        self.variant_combo = ui.Select(variant_row, values=["Clásica", "Slim"],
                                       textvariable=self.variant_var, width=106,
                                       height=30)
        self.variant_combo.pack(side="left", padx=(8, 8))
        self.variant_combo.bind("<<ComboboxSelected>>", self._on_variant_change)
        self.upload_btn = ui.Button(variant_row, "Subir", kind="quiet",
                                    command=self._upload_skin, width=64,
                                    height=30)
        self.upload_btn.pack(side="left")

    def _build_right(self, parent) -> None:
        scroll = ui.ScrollFrame(parent, bg=PANEL)
        scroll.pack(fill="both", expand=True)
        wrap = tk.Frame(scroll.content, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=18, pady=14)

        ui.section(wrap, "Instancia").pack(fill="x")
        self.detail_holder = tk.Frame(
            wrap, bg=CARD, width=110, height=110,
            highlightbackground=BORDER_SOFT, highlightthickness=2)
        self.detail_holder.pack(anchor="w", pady=(6, 6))
        self.detail_holder.pack_propagate(False)
        self.detail_icon = tk.Label(self.detail_holder, image=self._detail_photo,
                                    bg=CARD, bd=0)
        self.detail_icon.pack(expand=True)

        self.detail_name = tk.Label(wrap, text="Sin instancia", bg=PANEL,
                                    fg=TEXT, font=(DISPLAY, 18), anchor="w",
                                    justify="left", wraplength=286)
        self.detail_name.pack(fill="x")
        self.detail_meta = tk.Label(wrap, text="Elegí una instancia del panel",
                                    bg=PANEL, fg=FAINT, font=(FONT, 8),
                                    anchor="w", justify="left", wraplength=286)
        self.detail_meta.pack(fill="x", pady=(3, 0))
        self.detail_stats = tk.Label(wrap, text="", bg=PANEL, fg=MUTED,
                                     font=(FONT, 8), anchor="w")
        self.detail_stats.pack(fill="x", pady=(3, 0))

        self.play_btn = ui.Button(wrap, "JUGAR", kind="primary",
                                  command=self._play, height=42,
                                  font=(DISPLAY, 16))
        self.play_btn.pack(fill="x", pady=(8, 4))
        self.play_btn.configure(state="disabled")

        ui.divider(wrap, top=8, bottom=6)
        ui.section(wrap, "Acciones").pack(fill="x")
        actions = tk.Frame(wrap, bg=PANEL)
        actions.pack(fill="x", pady=(7, 0))
        actions.grid_columnconfigure(0, weight=1, uniform="actions")
        actions.grid_columnconfigure(1, weight=1, uniform="actions")
        self._instance_actions = []
        specs = (
            ("Editar", self._edit_selected, "secondary"),
            ("Mods", lambda: self._open_selected_tab("mods"), "secondary"),
            ("Paquetes", lambda: self._open_selected_tab("packs"), "secondary"),
            ("Mundos", lambda: self._open_selected_tab("worlds"), "secondary"),
            ("Carpeta", self._open_instance_folder, "secondary"),
            ("Exportar", self._export_instance, "secondary"),
            ("Copiar", self._duplicate_instance, "secondary"),
            ("Borrar", self._delete_instance, "danger"),
        )
        for index, (text, command, kind) in enumerate(specs):
            button = ui.Button(actions, text, command=command, kind=kind,
                               width=1, height=28, font=(FONT, 8))
            button.grid(row=index // 2, column=index % 2, sticky="ew",
                        padx=(0, 6) if index % 2 == 0 else (0, 0),
                        pady=(0, 4))
            self._instance_actions.append(button)
            button.configure(state="disabled")

        ui.divider(wrap, top=6, bottom=6)
        head = tk.Frame(wrap, bg=PANEL)
        head.pack(fill="x")
        ui.section(head, "Juego").pack(side="left", fill="x", expand=True)
        self.version_count = tk.Label(head, text="", bg=PANEL, fg=FAINT,
                                      font=(MONO, 8))
        self.version_count.pack(side="right")

        self.version_categories = tk.Frame(wrap, bg=PANEL)
        self.version_categories.pack(fill="x", pady=(6, 6))
        for column in range(3):
            self.version_categories.grid_columnconfigure(
                column, weight=1, uniform="version_category")
        self._category_buttons: dict[str, ui.Button] = {}
        for index, key in enumerate(CATEGORY_ORDER):
            button = ui.Button(
                self.version_categories, CATEGORY_SHORT[key], kind="quiet",
                command=lambda value=key: self._set_version_category(value),
                height=24, font=(FONT, 7))
            button.grid(row=index // 3, column=index % 3, sticky="ew",
                        padx=(0, 4) if index % 3 != 2 else (0, 0),
                        pady=(0, 4))
            self._category_buttons[key] = button

        self.version_combo = ui.Select(wrap, values=[], height=36,
                                       placeholder="Cargando versiones...")
        self.version_combo.pack(fill="x", pady=(2, 4))
        self.version_combo.bind("<<ComboboxSelected>>", self._on_version_change)
        self.version_info = tk.Label(wrap, text="Leyendo el manifiesto de Mojang...",
                                     bg=PANEL, fg=FAINT, font=(FONT, 8),
                                     anchor="w", justify="left", wraplength=286)
        self.version_info.pack(fill="x")

        mem_row = tk.Frame(wrap, bg=PANEL)
        mem_row.pack(fill="x", pady=(8, 0))
        tk.Label(mem_row, text="Memoria", bg=PANEL, fg=TEXT,
                 font=(FONT, 9), width=8, anchor="w").pack(side="left")
        self.memory_var = tk.IntVar(value=int(self.settings.get("memory_mb", 2048)))
        self.memory_scale = ui.Slider(mem_row, from_=512, to=8192,
                                      variable=self.memory_var,
                                      command=self._on_memory, step=256)
        self.memory_scale.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.memory_label = tk.Label(mem_row,
                                     text=f"{int(self.memory_var.get())} MB",
                                     bg=PANEL, fg=ACCENT, font=(MONO, 8),
                                     width=7, anchor="e")
        self.memory_label.pack(side="left")

        self.resolution_var = tk.BooleanVar(
            value=bool(self.settings.get("custom_resolution")))
        ui.Check(wrap, "Resolución personalizada", self.resolution_var,
                 command=self._toggle_resolution, bg=PANEL).pack(
            anchor="w", pady=(5, 2))
        self.width_var = tk.StringVar(
            value=str(self.settings.get("resolution_width", 1280)))
        self.height_var = tk.StringVar(
            value=str(self.settings.get("resolution_height", 720)))
        res_row = tk.Frame(wrap, bg=PANEL)
        res_row.pack(fill="x")
        self.width_entry = ui.Input(res_row, textvariable=self.width_var,
                                    width=5)
        self.width_entry.pack(side="right")
        tk.Label(res_row, text="×", bg=PANEL, fg=FAINT).pack(side="right",
                                                             padx=4)
        self.height_entry = ui.Input(res_row, textvariable=self.height_var,
                                     width=5)
        self.height_entry.pack(side="right")

        dir_row = tk.Frame(wrap, bg=PANEL)
        dir_row.pack(fill="x", pady=(6, 0))
        tk.Label(dir_row, text="Carpeta", bg=PANEL, fg=TEXT, font=(FONT, 9),
                 width=7, anchor="w").pack(side="left")
        self.game_dir_var = tk.StringVar(value=self.settings.get("game_dir", ""))
        self.game_dir_entry = ui.Input(dir_row, textvariable=self.game_dir_var)
        self.game_dir_entry.pack(side="left", fill="x", expand=True)
        ui.Button(dir_row, "Abrir", kind="quiet",
                  command=self._open_game_dir, width=48, height=29,
                  font=(FONT, 8)).pack(side="left", padx=(6, 0))
        self.dir_browse_btn = ui.Button(dir_row, "...",
                                        command=self._browse_game_dir, width=34,
                                        height=29)
        self.dir_browse_btn.pack(side="left", padx=(4, 0))
        tk.Frame(wrap, bg=PANEL, height=6).pack(fill="x")

    def _post(self, kind: str, **payload) -> None:
        self.events.put((kind, payload))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                try:
                    self._handle_event(kind, payload)
                except Exception:
                    traceback.print_exc()
                    self._handle_unexpected_error(sys.exc_info(), "evento")
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._pump_job = self.after(80, self._pump)

    def _handle_event(self, kind: str, payload: dict) -> None:
        if kind == "status":
            self.status_var.set(payload["text"])
        elif kind == "update_ready":
            self._offer_update(payload["info"])
        elif kind == "update_progress":
            self.progress["value"] = max(0.0, min(100.0, payload["pct"]))
            self.status_var.set(
                f"Descargando Blockys {payload['tag']}... {payload['pct']}%")
        elif kind == "update_error":
            self._update_downloading = False
            self.progress["value"] = 0
            self.status_var.set("No se pudo actualizar Blockys")
            self._log(f"Actualización: {payload['msg']}", "err")
            ui.show_error(self, "Actualización", payload["msg"])
        elif kind == "update_ready_to_install":
            self._update_downloading = False
            self.progress["value"] = 100
            self.status_var.set("Reiniciando Blockys para actualizar...")
            self._log(f"Instalador descargado: {payload['name']}", "ok")
            self.after(500, self._quit_for_update)
        elif kind == "progress":
            self.progress["value"] = max(0.0, min(100.0, payload["frac"] * 100))
            if payload.get("text"):
                self.status_var.set(payload["text"])
        elif kind == "log":
            self._log(payload["text"], payload.get("tag", "info"))
        elif kind == "versions":
            self.manifest = payload["manifest"]
            self._populate_versions()
            self.status_var.set("Listo para jugar")
            self._log(f"{len(self.manifest.get('versions', []))} versiones disponibles", "dim")
        elif kind == "versions_loaded":
            self._loading_versions = False
            if self._pending_force_reload:
                self._pending_force_reload = False
                self.status_var.set("Actualizando versiones...")
                self._load_versions(force=True)
        elif kind == "versions_error":
            self._loading_versions = False
            self.version_info.configure(
                text="No se pudieron cargar las versiones", fg=DANGER)
            self._log(f"No se pudo cargar el manifiesto: {payload['msg']}", "err")
        elif kind == "profiles":
            self._refresh_accounts()
        elif kind == "ms_code":
            self._show_device_window(payload["flow"])
        elif kind == "ms_status":
            if self._auth_status is not None:
                self._auth_status.set(payload["text"])
        elif kind == "ms_done":
            self._auth_cancel = None
            self._close_auth_window()
            profile = self.store.upsert_microsoft(payload["data"])
            self._refresh_accounts()
            self._log(f"Sesión iniciada como {profile['name']}", "ok")
            self.status_var.set("Cuenta Microsoft conectada")
        elif kind == "ms_error":
            self._auth_cancel = None
            self._close_auth_window()
            self._log(payload["msg"], "err")
            ui.show_error(self, "Microsoft", payload["msg"])
        elif kind == "skin_uploaded":
            self._update_skin_view()
            self._log(f"Skin subida a Mojang para {payload['name']}", "ok")
            self.status_var.set("Skin subida")
            ui.show_info(self, "Skin", "Skin subida a Mojang correctamente.")
        elif kind == "skin_upload_error":
            self._update_skin_view()
            self._log(payload["msg"], "err")
            ui.show_error(self, "Skin", payload["msg"])
        elif kind == "instance_duplicated":
            self._busy = False
            copy = payload.get("instance")
            if copy:
                self._apply_instance(copy)
                self.status_var.set(f"Instancia copiada: {copy['name']}")
                self._log(f"Instancia duplicada como {copy['name']}", "ok")
            else:
                self._update_instance_sidebar()
        elif kind == "instance_duplicate_error":
            self._busy = False
            self._update_instance_sidebar()
            self.status_var.set("No se pudo copiar la instancia")
            self._log(payload["msg"], "err")
            ui.show_error(self, "Copiar instancia", payload["msg"])
        elif kind == "instance_deleted":
            self._busy = False
            if payload.get("active"):
                self._instance = None
                self._apply_instance(self.instance_store.selected())
            else:
                self._refresh_instance_views()
            name = payload.get("name")
            self.status_var.set(f"Instancia eliminada: {name}")
            self._log(f"Instancia eliminada: {name}", "dim")
        elif kind == "instance_delete_error":
            self._busy = False
            self._update_instance_sidebar()
            self.status_var.set("No se pudo eliminar la instancia")
            self._log(payload["msg"], "err")
            ui.show_error(self, "Eliminar instancia", payload["msg"])
        elif kind == "instance_exported":
            self._busy = False
            self._update_instance_sidebar()
            self.status_var.set(f"Instancia exportada: {payload['name']}")
            self._log(f"Instancia exportada a {payload['name']}", "ok")
            ui.show_info(self, "Instancia exportada",
                         "La instancia se guardó con sus mods y configuraciones.")
        elif kind == "instance_export_error":
            self._busy = False
            self._update_instance_sidebar()
            self.status_var.set("No se pudo exportar la instancia")
            self._log(payload["msg"], "err")
            ui.show_error(self, "Exportar",
                          f"No se pudo exportar: {payload['msg']}")
        elif kind == "instance_ready":
            instance = self.instance_store.by_id(payload.get("id", ""))
            if instance:
                instance["resolved_version"] = payload.get("resolved_version", "")
                instance["loader_version"] = payload.get("loader_version", "")
                self.instance_store.save()
                if self._instance and self._instance.get("id") == instance["id"]:
                    entry = (versions.find_entry(self.manifest, instance["version"])
                             if self.manifest else None)
                    if entry:
                        self._set_version_info(entry)
                self._log(
                    f"{instance.get('loader', '').title()} listo para "
                    f"{instance.get('name')}", "dim")
        elif kind == "game_started":
            self._game = payload["proc"]
            self._game_log = payload["handle"]
            self._busy = False
            self.progress["value"] = 100
            self.status_var.set("Minecraft está abierto")
            self._hide_cancel()
            self._populate_versions()
            self.play_btn.configure(text="JUGANDO...")
            target = (self.instance_store.by_id(payload.get("id", ""))
                      if payload.get("id") else self._instance)
            if target:
                self.instance_store.touch(target)
            self._log(f"Minecraft iniciado. Registro: {payload['log']}", "ok")
        elif kind == "game_exit":
            code = payload.get("code")
            self._game = None
            self._game_log = None
            self._busy = False
            self.play_btn.configure(state="normal", text="JUGAR")
            self._hide_cancel()
            self.progress["value"] = 0
            if code in (0, None):
                self.status_var.set("Minecraft se cerró")
                self._log("Minecraft se cerró", "dim")
            else:
                self.status_var.set(f"Minecraft terminó con código {code}")
                self._log(f"Minecraft terminó con código {code}", "warn")
            for line in payload.get("tail", []):
                self._log(line, "dim")
            if code not in (0, None):
                target = payload.get("log")
                self._analyze_game_log(Path(target) if target else None)
        elif kind == "launch_cancelled":
            self._busy = False
            self.play_btn.configure(state="normal", text="JUGAR")
            self._hide_cancel()
            self.progress["value"] = 0
            self.status_var.set("Inicio cancelado")
            self._log("Inicio cancelado por el usuario", "warn")
            self._populate_versions()
        elif kind == "launch_error":
            self._busy = False
            self.play_btn.configure(state="normal", text="JUGAR")
            self._hide_cancel()
            self.progress["value"] = 0
            self.status_var.set("No se pudo iniciar Minecraft")
            self._log(payload["msg"], "err")
            if payload.get("detail"):
                self._log(payload["detail"].strip().splitlines()[-1], "dim")
            self._show_log()
            ui.show_error(self, "No se pudo iniciar Minecraft", payload["msg"])
        elif kind == "diagnostics_ready":
            self._diagnostics_ready(Path(payload["path"]))
        elif kind == "diagnostics_failed":
            self._diagnostics_failed(payload["msg"])
        elif kind == "log_issues":
            self._show_log_issues(payload.get("issues") or [])

    def _handle_unexpected_error(self, info, context: str = "") -> None:
        path = diagnostics.record_crash(*info, context=context)
        location = str(path) if path else "no disponible"
        self._log(f"Error inesperado. Registro: {location}", "err")
        if self._crash_reported:
            return
        self._crash_reported = True
        message = ("Blockys encontró un error inesperado, pero sigue abierto.\n\n"
                   f"Se guardó un registro en:\n{location}\n\n"
                   "Podés exportar un diagnóstico desde Ayuda.")
        try:
            ui.show_error(self, "Error inesperado", message)
        except Exception:
            pass

    def _log(self, message: str, tag: str = "info") -> None:
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n", tag)
        try:
            if int(self.log_text.index("end-1c").split(".")[0]) > 400:
                self.log_text.delete("1.0", "100.0")
        except (tk.TclError, ValueError):
            pass
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _toggle_log(self) -> None:
        if self.log_frame.winfo_ismapped():
            self.log_frame.pack_forget()
            self.log_toggle.configure(text="Registro")
        else:
            self.log_frame.pack(side="bottom", fill="x", after=self.status_bar,
                                pady=(8, 0))
            self.log_toggle.configure(text="Ocultar")
            self.log_text.see("end")

    def _show_log(self) -> None:
        if not self.log_frame.winfo_ismapped():
            self._toggle_log()

    def _sort_items(self, items: list[dict]) -> list[dict]:
        if self._instance_sort == "recent":
            return sorted(items, key=lambda item: item.get("last_played", 0),
                          reverse=True)
        if self._instance_sort == "version":
            return sorted(items, key=lambda item: (
                str(item.get("version", "")).casefold(),
                str(item.get("name", "")).casefold()), reverse=True)
        return sorted(items,
                      key=lambda item: str(item.get("name", "")).casefold())

    def _instance_groups(self, items: list[dict] | None = None
                         ) -> list[tuple[str, list[dict]]]:
        groups: dict[str, list[dict]] = {}
        for instance in (items if items is not None
                         else self.instance_store.instances):
            key = (instance.get("group") or "").strip()
            groups.setdefault(key, []).append(instance)
        keys = sorted((key for key in groups if key), key=str.casefold)
        if "" in groups:
            keys.insert(0, "")
        return [(key, self._sort_items(groups[key])) for key in keys]

    def _short_name(self, instance: dict) -> str:
        name = instance.get("name", "Instancia")
        return name if len(name) <= 15 else name[:14] + "…"

    def _search_focus(self, _event=None) -> None:
        if self.search_box.entry.get() == "Buscar instancia...":
            self.search_box.entry.delete(0, "end")
            self.search_box.entry.configure(fg=TEXT)

    def _search_blur(self, _event=None) -> None:
        if not self.search_box.entry.get().strip():
            self.search_box.entry.delete(0, "end")
            self.search_box.entry.insert(0, "Buscar instancia...")
            self.search_box.entry.configure(fg=FAINT)

    def _on_instance_search(self) -> None:
        value = self.search_box.entry.get()
        if value == "Buscar instancia...":
            value = ""
        if value == self._instance_search:
            return
        self._instance_search = value
        self._render_instance_grid(force=True)

    def _clear_instance_search(self) -> None:
        self.search_box.entry.delete(0, "end")
        self.search_box.entry.insert(0, "Buscar instancia...")
        self.search_box.entry.configure(fg=FAINT)
        self._instance_search = ""
        self._render_instance_grid(force=True)

    def _on_sort_change(self) -> None:
        reverse = {"Nombre": "name", "Reciente": "recent",
                   "Versión": "version", "Grupo": "group"}
        value = reverse.get(self.sort_combo.get(), "name")
        if value == self._instance_sort:
            return
        self._instance_sort = value
        self.settings["instance_sort"] = value
        try:
            paths.save_settings(self.settings)
        except OSError:
            pass
        self._render_instance_grid(force=True)

    def _toggle_group(self, group: str) -> None:
        if group in self._collapsed_groups:
            self._collapsed_groups.discard(group)
        else:
            self._collapsed_groups.add(group)
        self.settings["collapsed_groups"] = sorted(self._collapsed_groups)
        try:
            paths.save_settings(self.settings)
        except OSError:
            pass
        self._render_instance_grid(force=True)

    def _filtered_instances(self) -> list[dict]:
        query = self._instance_search.strip().casefold()
        items = self.instance_store.instances
        if query:
            items = [item for item in items
                     if query in str(item.get("name", "")).casefold()
                     or query in str(item.get("group", "")).casefold()
                     or query in str(item.get("version", "")).casefold()
                     or query in str(item.get("loader", "")).casefold()]
        if self._instance_sort == "recent":
            return sorted(items, key=lambda item: item.get("last_played", 0),
                          reverse=True)
        if self._instance_sort == "version":
            return sorted(items, key=lambda item: (
                str(item.get("version", "")).casefold(),
                str(item.get("name", "")).casefold()), reverse=True)
        if self._instance_sort == "group":
            return sorted(items, key=lambda item: (
                str(item.get("group", "")).casefold(),
                str(item.get("name", "")).casefold()))
        return sorted(items, key=lambda item: str(item.get("name", "")).casefold())

    def _render_instance_grid(self, force: bool = False) -> None:
        if not hasattr(self, "grid_scroll"):
            return
        width = self.grid_scroll.canvas.winfo_width()
        if width <= 40:
            width = max(400, self.winfo_width() - 56 - 344 - 18 - 16)
        cols = max(1, (width - 4) // 126)
        selected_id = self._instance.get("id") if self._instance else ""
        signature = (tuple(
            (item.get("id"), item.get("name"), item.get("version"),
             item.get("loader"), item.get("group"), item.get("icon"),
             item.get("icon_path"), item.get("last_played"))
            for item in self.instance_store.instances), selected_id,
            self._instance_search, self._instance_sort,
            tuple(sorted(self._collapsed_groups)))
        content = self.grid_scroll.content
        if (not force and cols == self._grid_cols
                and signature == self._grid_signature
                and content.winfo_children()):
            return
        self._grid_cols = cols
        self._grid_signature = signature
        self._selected_tile = None
        self._tiles = {}
        for child in content.winfo_children():
            child.destroy()

        total = len(self.instance_store.instances)
        visible = self._filtered_instances()
        if self._instance_search.strip():
            self.instances_count.configure(
                text=f"{len(visible)} de {total}")
        else:
            self.instances_count.configure(
                text=f"{total} instancia{'s' if total != 1 else ''}")
        if not total:
            holder = tk.Frame(content, bg=BG)
            holder.pack(pady=54)
            tk.Label(holder, image=self._tile_photo, bg=BG, bd=0).pack()
            tk.Label(holder, text="Todavía no hay instancias", bg=BG, fg=TEXT,
                     font=(DISPLAY, 18)).pack(pady=(12, 4))
            tk.Label(holder, text="Creá una para separar versiones, mods y "
                                  "configuraciones.", bg=BG, fg=MUTED,
                     font=(FONT, 9)).pack()
            ui.Button(holder, "Crear instancia", kind="primary",
                      command=self._add_instance, width=184, height=38).pack(
                pady=(16, 0))
            return
        if not visible:
            holder = tk.Frame(content, bg=BG)
            holder.pack(pady=48)
            tk.Label(holder, text="Sin resultados", bg=BG, fg=TEXT,
                     font=(DISPLAY, 17)).pack()
            tk.Label(holder, text="Probá con otro nombre, grupo o versión.",
                     bg=BG, fg=MUTED, font=(FONT, 9)).pack(pady=(4, 12))
            ui.Button(holder, "Limpiar búsqueda",
                      command=self._clear_instance_search, width=150,
                      height=34).pack()
            return

        for group, items in self._instance_groups(visible):
            collapsed = group in self._collapsed_groups and not self._instance_search.strip()
            head = tk.Frame(content, bg=BG)
            head.pack(fill="x", pady=(4, 5))
            title = tk.Label(
                head, text=f"{'▸' if collapsed else '▾'} "
                           f"{group or 'Sin grupo'}", bg=BG, fg=MUTED,
                font=(FONT, 10, "bold"), cursor="hand2")
            title.pack(side="left")
            tk.Label(head, text=str(len(items)), bg=BG, fg=FAINT,
                     font=(MONO, 8)).pack(side="left", padx=(7, 0))
            for widget in (head, title):
                widget.bind("<Button-1>",
                            lambda _event, key=group: self._toggle_group(key))
            tk.Frame(content, bg=BORDER_SOFT, height=1).pack(
                fill="x", pady=(0, 9))
            if collapsed:
                continue

            tiles = tk.Frame(content, bg=BG)
            tiles.pack(fill="x")
            for column in range(cols):
                tiles.grid_columnconfigure(column, minsize=126)
            for index, instance in enumerate(items):
                tile = self._instance_tile(tiles, instance)
                tile.grid(row=index // cols, column=index % cols,
                          sticky="nw", padx=(0, 10), pady=(0, 12))
        tk.Frame(content, bg=BG, height=8).pack(fill="x")
        if selected_id:
            self.after(120, self._reveal_selected_tile)

    def _reveal_selected_tile(self) -> None:
        tile = self._selected_tile
        if tile is None or not tile.winfo_exists():
            return
        try:
            self.update_idletasks()
            canvas = self.grid_scroll.canvas
            content = self.grid_scroll.content
            y = tile.winfo_rooty() - content.winfo_rooty()
            height = tile.winfo_height()
            top = canvas.canvasy(0)
            view_height = canvas.winfo_height()
            if y < top:
                target = y - 8
            elif y + height > top + view_height:
                target = y + height + 8 - view_height
            else:
                return
            total = max(content.winfo_height(), 1)
            canvas.yview_moveto(max(0.0, min(1.0, target / total)))
        except tk.TclError:
            pass

    def _instance_tile(self, parent, instance: dict) -> tk.Frame:
        selected = bool(self._instance
                        and self._instance.get("id") == instance.get("id"))
        color = instance.get("icon") or ACCENT
        outer = tk.Frame(parent, bg=BG)
        card = tk.Frame(outer, bg=CARD, width=116, height=148,
                        highlightbackground=color if selected else BORDER_SOFT,
                        highlightthickness=2)
        card.pack()
        card.pack_propagate(False)
        icon = tk.Label(card, bg=CARD, bd=0,
                        image=self._instance_icon_photo(instance, 66)
                        or self._tile_photo)
        icon.pack(pady=(9, 3))
        name = tk.Label(card, text=self._short_name(instance),
                        bg=color if selected else CARD,
                        fg=ACCENT_INK if selected else MUTED,
                        font=(FONT, 9, "bold"), anchor="center", padx=3,
                        pady=4)
        name.pack(side="bottom", fill="x")
        loader = instances.LOADERS.get(instance.get("loader"), "Vanilla")
        version = str(instance.get("version", ""))
        if len(version) > 9:
            version = version[:8] + "…"
        sub = tk.Label(card, text=f"{loader} {version}", bg=CARD, fg=FAINT,
                       font=(FONT, 7), anchor="center")
        sub.pack(side="bottom", pady=(0, 1))

        def select(_event=None, item=instance):
            self._select_instance(item)

        def launch(_event=None, item=instance):
            self._launch_instance(item)

        for widget in (outer, card, icon, name, sub):
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", select)
            widget.bind("<Double-Button-1>", launch)
            widget.bind("<Button-3>",
                        lambda event, item=instance: self._instance_menu(
                            event, item))
        if instance.get("id"):
            self._tiles[instance["id"]] = {
                "outer": outer, "card": card, "name": name, "color": color}
        if selected:
            self._selected_tile = outer
        return outer

    def _instance_icon_photo(self, instance: dict, size: int):
        path = str(instance.get("icon_path") or "")
        if not path:
            return None
        try:
            stamp = int(os.stat(path).st_mtime)
        except OSError:
            return None
        key = (path, stamp, size)
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
            image.thumbnail((size, size), Image.LANCZOS)
            photo = ImageTk.PhotoImage(image)
        except Exception:
            return None
        if len(self._icon_cache) > 80:
            self._icon_cache.clear()
        self._icon_cache[key] = photo
        return photo

    def _change_instance_icon(self, instance: dict) -> None:
        chosen = filedialog.askopenfilename(
            parent=self, title="Icono de la instancia",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp"),
                       ("Todos", "*.*")])
        if not chosen:
            return
        try:
            folder = self.instance_store.ensure_dirs(instance)
            target = folder / "blockys-icon.png"
            with Image.open(chosen) as source:
                image = source.convert("RGBA")
                image.thumbnail((256, 256), Image.LANCZOS)
                image.save(target, "PNG")
        except (OSError, ValueError, instances.InstanceError) as exc:
            ui.show_error(self, "Icono",
                          f"No se pudo usar esa imagen:\n{exc}")
            return
        instance["icon_path"] = str(target)
        self.instance_store.save()
        self._icon_cache.clear()
        if self._instance and self._instance.get("id") == instance.get("id"):
            self._update_instance_sidebar()
        self._render_instance_grid(force=True)
        self.status_var.set(f"Icono actualizado: {instance.get('name')}")

    def _instance_menu(self, event, instance: dict) -> None:
        previous = getattr(self, "_context_menu", None)
        if previous is not None:
            try:
                previous.destroy()
            except tk.TclError:
                pass
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT, bd=0,
                       activebackground=ACCENT, activeforeground=ACCENT_INK,
                       activeborderwidth=0, font=(FONT, 9))
        menu.add_command(label="Jugar",
                         command=lambda: self._launch_instance(instance))
        menu.add_command(
            label="Editar",
            command=lambda: self._open_instances(select_id=instance["id"],
                                                 tab="general"))
        menu.add_separator()
        menu.add_command(
            label="Abrir carpeta",
            command=lambda: self._open_folder_for(instance))
        menu.add_command(label="Cambiar icono",
                         command=lambda: self._change_instance_icon(instance))
        if instance.get("icon_path"):
            menu.add_command(
                label="Quitar icono",
                command=lambda: self._clear_instance_icon(instance))
        menu.add_separator()
        menu.add_command(label="Duplicar",
                         command=lambda: self._duplicate_for(instance))
        menu.add_command(label="Eliminar",
                         command=lambda: self._delete_for(instance))
        self._context_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_folder_for(self, instance: dict) -> None:
        try:
            folder = self.instance_store.ensure_dirs(instance)
            os.startfile(str(folder))
        except (OSError, instances.InstanceError) as exc:
            self._log(f"No se pudo abrir la carpeta: {exc}", "err")

    def _clear_instance_icon(self, instance: dict) -> None:
        old = str(instance.get("icon_path") or "")
        instance["icon_path"] = ""
        self.instance_store.save()
        self._icon_cache.clear()
        if old:
            path = Path(old)
            try:
                if path.name == "blockys-icon.png" and path.parent.resolve() == (
                        self.instance_store.game_dir(instance).resolve()):
                    path.unlink()
            except OSError:
                pass
        if self._instance and self._instance.get("id") == instance.get("id"):
            self._update_instance_sidebar()
        self._render_instance_grid(force=True)

    def _duplicate_for(self, instance: dict) -> None:
        self._duplicate_instance(instance)

    def _delete_for(self, instance: dict) -> None:
        self._delete_instance(instance)

    def _select_instance(self, instance: dict) -> None:
        if self._busy:
            return
        if self._instance and self._instance.get("id") == instance.get("id"):
            return
        self._apply_instance(instance, rebuild=False)

    def _update_tile_selection(self) -> None:
        selected_id = self._instance.get("id") if self._instance else ""
        self._selected_tile = None
        for key, widgets in getattr(self, "_tiles", {}).items():
            selected = key == selected_id
            widgets["card"].configure(
                highlightbackground=widgets["color"] if selected else BORDER_SOFT)
            widgets["name"].configure(
                bg=widgets["color"] if selected else CARD,
                fg=ACCENT_INK if selected else MUTED)
            if selected:
                self._selected_tile = widgets["outer"]
        signature = getattr(self, "_grid_signature", None)
        if signature:
            self._grid_signature = (signature[0], selected_id, *signature[2:])

    def _launch_instance(self, instance: dict) -> None:
        if self._busy or self._game is not None:
            return
        if not self._instance or self._instance.get("id") != instance.get("id"):
            self._apply_instance(instance)
        self._play()

    def _set_instance_actions(self, state: str) -> None:
        for button in getattr(self, "_instance_actions", []):
            button.configure(state=state)

    def _update_instance_sidebar(self) -> None:
        instance = self._instance
        if instance is None:
            self.detail_holder.configure(bg=CARD,
                                         highlightbackground=BORDER_SOFT)
            self.detail_icon.configure(bg=CARD, image=self._detail_photo)
            self.detail_name.configure(text="Sin instancia")
            self.detail_meta.configure(
                text="Elegí una instancia del panel para jugar.")
            self.detail_stats.configure(text="")
            self.play_btn.configure(state="disabled", text="JUGAR")
            for button in self._instance_actions:
                button.configure(state="disabled")
            return

        color = instance.get("icon") or ACCENT
        self.detail_holder.configure(bg=CARD, highlightbackground=color)
        self.detail_icon.configure(
            bg=CARD,
            image=self._instance_icon_photo(instance, 92) or self._detail_photo)
        self.detail_name.configure(text=instance.get("name", "Instancia"))
        loader = instances.LOADERS.get(instance.get("loader"), "Vanilla")
        resolved = instance.get("resolved_version") or ""
        meta = f"{loader} · Minecraft {instance.get('version', '')}"
        if resolved:
            meta += " · listo"
        if instance.get("account"):
            meta += f" · cuenta {instance['account']}"
        self.detail_meta.configure(text=meta)
        try:
            mods = len(self.instance_store.list_mods(instance))
            packs = len(self.instance_store.list_simple(instance, "resourcepacks"))
            shaders = len(self.instance_store.list_simple(instance, "shaderpacks"))
            worlds = len(self.instance_store.worlds(instance))
        except Exception:
            mods = packs = shaders = worlds = 0
        self.detail_stats.configure(
            text=f"{mods} mods · {packs} paq · {shaders} shaders · "
                 f"{worlds} mundos", wraplength=286, justify="left")
        if self._game is not None:
            self.play_btn.configure(state="disabled", text="JUGANDO...")
        elif self._busy:
            self.play_btn.configure(state="disabled", text="PREPARANDO...")
        else:
            self.play_btn.configure(state="normal", text="JUGAR")
        for button in self._instance_actions:
            button.configure(state="normal")

    def _refresh_instance_views(self) -> None:
        self._update_instance_sidebar()
        self._render_instance_grid(force=True)

    def _require_instance(self) -> dict | None:
        instance = self._instance
        if instance is None:
            ui.show_warning(self, "Instancia",
                            "Elegí o creá una instancia primero.")
        return instance

    def _add_instance(self) -> None:
        self._open_instances(create=True)

    def _edit_selected(self) -> None:
        instance = self._require_instance()
        if instance:
            self._open_instances(select_id=instance["id"], tab="general")

    def _open_selected_tab(self, tab: str) -> None:
        instance = self._require_instance()
        if instance:
            self._open_instances(select_id=instance["id"], tab=tab)

    def _open_accounts(self) -> None:
        window = self._accounts_window
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            self._refresh_accounts()
            return
        self._accounts_window = AccountsDialog(self)

    def _open_instances_folder(self) -> None:
        try:
            paths.INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(paths.INSTANCES_DIR))
        except OSError as exc:
            self._log(f"No se pudo abrir la carpeta: {exc}", "err")

    def _open_instance_folder(self) -> None:
        instance = self._require_instance()
        if not instance:
            return
        try:
            folder = self.instance_store.ensure_dirs(instance)
            os.startfile(str(folder))
        except (OSError, instances.InstanceError) as exc:
            self._log(f"No se pudo abrir la carpeta: {exc}", "err")

    def _export_instance(self) -> None:
        instance = self._require_instance()
        if not instance or self._busy:
            return
        if self._game is not None:
            ui.show_warning(self, "Instancia",
                            "Cerrá Minecraft antes de exportar una instancia.")
            return
        safe = "".join(ch for ch in instance.get("name", "")
                       if ch.isalnum() or ch in " -_") or "instancia"
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Exportar instancia", defaultextension=".zip",
            initialfile=f"{safe}.zip",
            filetypes=[("Instancia Blockys", "*.zip")])
        if not chosen:
            return
        target = Path(chosen)
        self._busy = True
        self._set_instance_actions("disabled")
        self.play_btn.configure(state="disabled", text="EXPORTANDO...")
        self.status_var.set("Exportando instancia...")
        self._log(f"Exportando instancia a {chosen}...", "dim")

        def work():
            try:
                self.instance_store.export(instance, target)
            except (OSError, instances.InstanceError) as exc:
                self._post("instance_export_error", msg=str(exc))
            except Exception as exc:
                self._post("instance_export_error",
                           msg=f"Error inesperado: {exc}")
            else:
                self._post("instance_exported", name=target.name)

        threading.Thread(target=work, daemon=True).start()

    def _duplicate_instance(self, instance: dict | None = None) -> None:
        instance = instance or self._require_instance()
        if not instance or self._busy:
            return
        if self._game is not None:
            ui.show_warning(self, "Instancia",
                            "Cerrá Minecraft antes de copiar una instancia.")
            return
        instance_id = instance["id"]
        self._busy = True
        self._set_instance_actions("disabled")
        self.play_btn.configure(state="disabled", text="COPIANDO...")
        self.status_var.set("Copiando instancia...")
        self._log(f"Copiando instancia {instance.get('name')}...", "dim")

        def work():
            try:
                copy = self.instance_store.duplicate(instance_id)
            except instances.InstanceError as exc:
                self._post("instance_duplicate_error", msg=str(exc))
            except Exception as exc:
                self._post("instance_duplicate_error",
                           msg=f"Error inesperado: {exc}")
            else:
                self._post("instance_duplicated", instance=copy)

        threading.Thread(target=work, daemon=True).start()

    def _delete_instance(self, instance: dict | None = None) -> None:
        instance = instance or self._require_instance()
        if not instance or self._busy:
            return
        if self._game is not None:
            ui.show_warning(self, "Instancia",
                            "Cerrá Minecraft antes de eliminar una instancia.")
            return
        if not ui.ask_confirm(
                self, "Eliminar instancia",
                f"¿Eliminar {instance.get('name')} y todos sus archivos? "
                "Esta acción no se puede deshacer.", ok_text="Eliminar"):
            return
        deleted = instance.get("name")
        instance_id = instance["id"]
        was_active = (self._instance is not None
                      and self._instance.get("id") == instance_id)
        self._busy = True
        self._set_instance_actions("disabled")
        self.play_btn.configure(state="disabled", text="ELIMINANDO...")
        self.status_var.set("Eliminando instancia...")
        self._log(f"Eliminando instancia {deleted}...", "dim")

        def work():
            try:
                self.instance_store.remove(instance_id)
            except Exception as exc:
                self._post("instance_delete_error", msg=str(exc))
            else:
                self._post("instance_deleted", name=deleted,
                           active=was_active)

        threading.Thread(target=work, daemon=True).start()

    def _show_help(self) -> None:
        window = self._help_window
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            return
        self._help_window = HelpDialog(self)

    def _maybe_welcome(self) -> None:
        window = self._welcome_window
        if window is not None and window.winfo_exists():
            return
        self._welcome_window = WelcomeDialog(self)

    def _analyze_game_log(self, path: Path | None = None) -> None:
        def work():
            target = path
            if target is None or not target.is_file():
                target = diagnostics.latest_game_log()
            if target is None or not target.is_file():
                return
            try:
                issues = diagnostics.analyze_log(target)
            except Exception:
                return
            if issues:
                self._post("log_issues", issues=issues)

        threading.Thread(target=work, daemon=True).start()

    def _show_log_issues(self, issues: list) -> None:
        if not self.winfo_exists():
            return
        for issue in issues:
            self._log(f"Diagnóstico: {issue['title']} — {issue['hint']}", "warn")
        message = "\n\n".join(f"{item['title']}\n{item['hint']}"
                              for item in issues[:3])
        ui.show_warning(
            self, "Diagnóstico de Minecraft",
            message + "\n\nPodés exportar el diagnóstico completo desde "
                      "Ayuda > Exportar diagnóstico.")

    def _open_data_folder(self) -> None:
        try:
            paths.APP_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(paths.APP_DIR))
        except OSError as exc:
            self._log(f"No se pudo abrir la carpeta de datos: {exc}", "err")

    def _open_logs_folder(self) -> None:
        try:
            paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(paths.LOGS_DIR))
        except OSError as exc:
            self._log(f"No se pudo abrir la carpeta de logs: {exc}", "err")

    def _export_diagnostics(self) -> None:
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Exportar diagnóstico", defaultextension=".zip",
            initialfile=time.strftime("Blockys-diagnostico-%Y%m%d-%H%M.zip"),
            filetypes=[("Diagnóstico Blockys", "*.zip")])
        if not chosen:
            return
        self.status_var.set("Creando diagnóstico...")

        def work():
            try:
                path = diagnostics.export_report(
                    Path(chosen), self.settings, self.instance_store,
                    self.manifest)
            except Exception as exc:
                message = str(exc) or type(exc).__name__
                self._post("diagnostics_failed", msg=message)
            else:
                self._post("diagnostics_ready", path=str(path))

        threading.Thread(target=work, daemon=True).start()

    def _diagnostics_failed(self, message: str) -> None:
        if not self.winfo_exists():
            return
        self.status_var.set("No se pudo exportar el diagnóstico")
        self._log(f"No se pudo exportar el diagnóstico: {message}", "err")
        ui.show_error(self, "Diagnóstico",
                      f"No se pudo crear el archivo:\n{message}")

    def _diagnostics_ready(self, path: Path) -> None:
        if not self.winfo_exists():
            return
        self.status_var.set("Diagnóstico exportado")
        self._log(f"Diagnóstico exportado: {path}", "ok")
        ui.show_info(
            self, "Diagnóstico exportado",
            f"Se guardó en:\n{path}\n\n"
            "No incluye cuentas, tokens ni contraseñas. Compartilo si "
            "necesitás ayuda para revisar un problema.")

    def _clear_cache(self) -> None:
        if not ui.ask_confirm(
                self, "Limpiar caché",
                "Se borrarán metadatos temporales del launcher. No se tocan "
                "instancias, cuentas, versiones ni mundos.",
                ok_text="Limpiar caché"):
            return
        removed = 0
        for child in paths.CACHE_DIR.iterdir() if paths.CACHE_DIR.is_dir() else ():
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                removed += 1
            except OSError:
                pass
        self.status_var.set("Caché limpiada")
        self._log(f"Caché limpiada ({removed} elementos)", "dim")

    def _toolbar_update(self) -> None:
        if self._loading_versions:
            self._pending_force_reload = True
            return
        self.status_var.set("Actualizando versiones...")
        self._log("Actualizando manifiesto de Mojang...", "dim")
        self._load_versions(force=True)
        self._refresh_instances()

    def _open_settings(self) -> None:
        window = self._settings_window
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            return
        self._settings_window = ui.SettingsDialog(self)

    def apply_settings(self, settings: dict) -> None:
        settings = dict(settings)
        if not self._instance:
            settings["memory_mb"] = int(self.memory_var.get())
            settings["custom_resolution"] = bool(self.resolution_var.get())
            try:
                settings["resolution_width"] = max(320, int(self.width_var.get()))
            except ValueError:
                settings["resolution_width"] = 1280
            try:
                settings["resolution_height"] = max(240, int(self.height_var.get()))
            except ValueError:
                settings["resolution_height"] = 720
        self.settings = settings
        try:
            paths.save_settings(settings)
        except OSError as exc:
            self._log(f"No se pudieron guardar los ajustes: {exc}", "err")
        net.configure_proxy(settings)
        if settings.get("check_updates", True) and not self._update_check_started:
            self.after(600, self._auto_check_updates)
        if self._instance:
            self._log("Ajustes guardados", "dim")
            return
        self.memory_var.set(int(settings["memory_mb"]))
        self.memory_label.configure(text=f"{int(self.memory_var.get())} MB")
        self.resolution_var.set(bool(settings["custom_resolution"]))
        self.width_var.set(str(settings["resolution_width"]))
        self.height_var.set(str(settings["resolution_height"]))
        self.game_dir_var.set(settings.get("game_dir", ""))
        self._toggle_resolution()
        self._log("Ajustes guardados", "dim")

    def _collect_settings(self, quick_override=None) -> dict:
        settings = dict(self.settings)
        settings["memory_mb"] = int(self.memory_var.get())
        settings["custom_resolution"] = bool(self.resolution_var.get())
        try:
            settings["resolution_width"] = max(320, int(self.width_var.get()))
        except ValueError:
            settings["resolution_width"] = 1280
        try:
            settings["resolution_height"] = max(240, int(self.height_var.get()))
        except ValueError:
            settings["resolution_height"] = 720
        if self._instance:
            self._sync_instance_controls()
            instance = self._instance
            settings["game_dir"] = str(self.instance_store.game_dir(instance))
            settings["memory_mb"] = max(512, min(8192, _int_value(
                instance.get("memory_mb", 2048), 2048)))
            settings["custom_resolution"] = bool(instance.get("custom_resolution"))
            settings["resolution_width"] = _int_value(
                instance.get("resolution_width", 1280), 1280)
            settings["resolution_height"] = _int_value(
                instance.get("resolution_height", 720), 720)
            java_mode = instance.get("java_mode", "inherit")
            if java_mode in ("temurin", "custom"):
                settings["java_mode"] = java_mode
                settings["java_path"] = instance.get("java_path", "")
            settings["aikar_flags"] = bool(instance.get("aikar_flags", True))
            for key in ("jvm_args", "game_args", "env_vars", "pre_launch",
                        "post_exit", "quick_play_type", "quick_play_target"):
                settings[key] = instance.get(key, "")
            override = quick_override or self._quick_play_override
            if override:
                settings["quick_play_type"], settings["quick_play_target"] = (
                    override)
            return settings
        settings["game_dir"] = (self.game_dir_var.get().strip()
                                or str(paths.default_game_dir()))
        self.settings = settings
        try:
            paths.save_settings(settings)
        except OSError:
            pass
        return settings

    def _on_memory(self, raw) -> None:
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            return
        self.memory_var.set(value)
        self.memory_label.configure(text=f"{value} MB")
        self._queue_settings_save()

    def _toggle_resolution(self) -> None:
        state = "normal" if self.resolution_var.get() else "disabled"
        self.width_entry.configure(state=state)
        self.height_entry.configure(state=state)
        self._queue_settings_save()

    def _queue_settings_save(self) -> None:
        if self._settings_job is not None:
            try:
                self.after_cancel(self._settings_job)
            except tk.TclError:
                pass
        self._settings_job = self.after(600, self._persist_ui_settings)

    def _persist_ui_settings(self) -> None:
        self._settings_job = None
        if self._instance:
            self._sync_instance_controls()
            return
        settings = dict(self.settings)
        settings["memory_mb"] = int(self.memory_var.get())
        settings["custom_resolution"] = bool(self.resolution_var.get())
        settings["resolution_width"] = max(
            320, _int_value(self.width_var.get(), 1280))
        settings["resolution_height"] = max(
            240, _int_value(self.height_var.get(), 720))
        settings["game_dir"] = (self.game_dir_var.get().strip()
                                or str(paths.default_game_dir()))
        self.settings = settings
        try:
            paths.save_settings(settings)
        except OSError as exc:
            self._log(f"No se pudieron guardar los ajustes: {exc}", "err")

    def _open_game_dir(self) -> None:
        folder = Path(self.game_dir_var.get() or self.settings.get("game_dir", ""))
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as exc:
            self._log(f"No se pudo abrir la carpeta: {exc}", "err")

    def _browse_game_dir(self) -> None:
        chosen = filedialog.askdirectory(parent=self, title="Carpeta del juego",
                                         initialdir=self.game_dir_var.get()
                                         or str(Path.home()))
        if chosen:
            self.game_dir_var.set(chosen)

    def _load_versions(self, force: bool = False) -> None:
        if self._loading_versions:
            return
        self._loading_versions = True
        self.version_info.configure(text="Cargando versiones...", fg=FAINT)

        def work():
            try:
                manifest = versions.load_manifest(force=force)
            except Exception as exc:
                self._post("versions_error", msg=str(exc))
            else:
                self._post("versions", manifest=manifest)
            finally:
                self._post("versions_loaded")

        threading.Thread(target=work, daemon=True).start()

    def _set_version_category(self, category: str, persist: bool = True) -> None:
        if category not in CATEGORY_ORDER:
            category = "release"
        self._version_category = category
        buttons = getattr(self, "_category_buttons", {})
        for key, button in buttons.items():
            button.configure(kind="secondary" if key == category else "quiet")
        if persist:
            self.settings["version_type"] = category
            try:
                paths.save_settings(self.settings)
            except OSError:
                pass
        self._populate_versions()

    def _populate_versions(self) -> None:
        if not self.manifest:
            return
        filter_type = self._version_category
        entries = self.manifest.get("versions", [])
        items = [entry for entry in entries
                 if filter_type == "all" or entry.get("type") == filter_type]
        self._version_map = {}
        labels = []
        for entry in items:
            installed = (paths.VERSIONS_DIR / entry["id"]
                         / f"{entry['id']}.jar").is_file()
            prefix = "● " if installed else ""
            pretty = PRETTY_TYPE.get(entry.get("type"), entry.get("type"))
            label = f"{prefix}{entry['id']}   ·   {pretty}"
            labels.append(label)
            self._version_map[label] = entry
        count_label = getattr(self, "version_count", None)
        if count_label is not None:
            count_label.configure(text=f"{len(items)} versiones")
        if not labels:
            self.version_combo.configure(values=[])
            self.version_combo.set("")
            message = ("No hay versiones para este filtro" if not self._instance
                       else "La versión de la instancia no está en el manifiesto")
            self.version_info.configure(text=message, fg=FAINT)
            return
        self.version_combo.configure(values=labels)
        desired = (self._instance.get("version", "") if self._instance
                   else self.settings.get("selected_version", ""))
        desired_label = next(
            (label for label, entry in self._version_map.items()
             if entry["id"] == desired), None)
        if desired_label:
            self.version_combo.set(desired_label)
            self._set_version_info(self._version_map[desired_label])
            return
        if self._instance and desired:
            self.version_combo.current(0)
            self.version_info.configure(
                text=(f"Filtro {CATEGORY_SHORT[filter_type].lower()} · la "
                      f"instancia usa {desired}"), fg=FAINT)
            return
        self.version_combo.current(0)
        self._set_version_info(self._version_map[labels[0]])

    def _set_version_info(self, entry: dict) -> None:
        date = (entry.get("releaseTime") or "")[:16].replace("T", " ")
        pretty = PRETTY_TYPE.get(entry.get("type"), entry.get("type"))
        color = TYPE_COLOR.get(entry.get("type"), FAINT)
        text = f"{pretty} · {date}"
        installed = (paths.VERSIONS_DIR / entry["id"]
                     / f"{entry['id']}.jar").is_file()
        if installed:
            text += " · ya instalada"
        instance = self._instance
        if instance:
            loader = instance.get("loader", "vanilla")
            if loader != "vanilla":
                label = instances.LOADERS.get(loader, loader.title())
                resolved = instance.get("resolved_version") or ""
                ready = bool(resolved and versions.read_version_json(resolved))
                text = (f"{label} · base {entry['id']} · "
                        + ("cargador listo" if ready else "se instalará al jugar"))
                color = ACCENT if ready else WARN
        self.version_info.configure(text=text, fg=color)
        if not instance:
            self.settings["selected_version"] = entry["id"]
            try:
                paths.save_settings(self.settings)
            except OSError:
                pass

    def _current_version_entry(self) -> dict | None:
        return self._version_map.get(self.version_combo.get())

    def _on_version_change(self, _event=None) -> None:
        entry = self._current_version_entry()
        if not entry:
            return
        if self._busy or self._game is not None:
            self._populate_versions()
            self.status_var.set("Esperá a que Minecraft termine para cambiar "
                                "la versión")
            return
        if self._instance:
            if entry["id"] != self._instance.get("version"):
                self._instance["version"] = entry["id"]
                self._instance["resolved_version"] = ""
                self._instance["loader_version"] = ""
                self.instance_store.save()
                self._refresh_instance_views()
            self._set_version_info(entry)
        else:
            self._set_version_info(entry)

    def _refresh_instances(self, select_id: str | None = None) -> None:
        if select_id:
            instance = self.instance_store.by_id(select_id)
            if instance is not None:
                self._apply_instance(instance)
                return
        self._refresh_instance_views()

    def _apply_instance(self, instance: dict | None,
                        rebuild: bool = True) -> None:
        if self._instance is not None and instance is not self._instance:
            self._sync_instance_controls()
        self._instance = instance
        if instance is None:
            self.instance_store.clear_selection()
            self.game_dir_entry.configure(state="normal")
            self.dir_browse_btn.configure(state="normal")
            self.game_dir_var.set(self.settings.get("game_dir", ""))
            self.memory_var.set(int(self.settings.get("memory_mb", 2048)))
            self._on_memory(self.memory_var.get())
            self.resolution_var.set(bool(self.settings.get("custom_resolution")))
            self.width_var.set(str(self.settings.get("resolution_width", 1280)))
            self.height_var.set(str(self.settings.get("resolution_height", 720)))
            self._toggle_resolution()
            version_type = self.settings.get("version_type", "release")
            self._set_version_category(version_type, persist=False)
            if rebuild:
                self._refresh_instance_views()
            else:
                self._update_instance_sidebar()
                self._update_tile_selection()
            return

        self.instance_store.select(instance["id"])
        try:
            folder = self.instance_store.ensure_dirs(instance)
        except instances.InstanceError as exc:
            self._log(str(exc), "err")
            folder = self.instance_store.game_dir(instance)
        self.game_dir_var.set(str(folder))
        self.game_dir_entry.configure(state="disabled")
        self.dir_browse_btn.configure(state="disabled")
        memory = max(512, min(8192, _int_value(
            instance.get("memory_mb", 2048), 2048)))
        self.memory_var.set(memory)
        self._on_memory(memory)
        self.resolution_var.set(bool(instance.get("custom_resolution")))
        self.width_var.set(str(_int_value(
            instance.get("resolution_width", 1280), 1280)))
        self.height_var.set(str(_int_value(
            instance.get("resolution_height", 720), 720)))
        self._toggle_resolution()
        entry = versions.find_entry(self.manifest, instance["version"]) \
            if self.manifest else None
        category = entry.get("type") if entry else self._version_category
        self._set_version_category(category, persist=False)
        self._log(f"Instancia activa: {instance.get('name')}", "dim")
        if rebuild:
            self._refresh_instance_views()
        else:
            self._update_instance_sidebar()
            self._update_tile_selection()

    def _sync_instance_controls(self) -> None:
        instance = self._instance
        if not instance:
            return
        try:
            instance["memory_mb"] = max(512, min(8192, int(self.memory_var.get())))
        except (TypeError, ValueError):
            pass
        instance["custom_resolution"] = bool(self.resolution_var.get())
        try:
            instance["resolution_width"] = max(320, int(self.width_var.get()))
        except ValueError:
            instance["resolution_width"] = 1280
        try:
            instance["resolution_height"] = max(240, int(self.height_var.get()))
        except ValueError:
            instance["resolution_height"] = 720
        self.instance_store.save()

    def _open_instances(self, select_id: str | None = None, tab: str = "general",
                        create: bool = False) -> None:
        if self._busy:
            return
        from .manager_gui import InstancesDialog
        window = getattr(self, "_instances_window", None)
        if window is not None and window.winfo_exists():
            if getattr(window, "_busy", False):
                window.lift()
                return
            if select_id:
                window._select(select_id)
            if tab and tab != getattr(window, "_tab", ""):
                window._show_tab(tab)
            window.lift()
            window.focus_set()
            if create:
                window._new_instance()
            return
        self._instances_window = InstancesDialog(self, select_id=select_id,
                                                 tab=tab, create=create)

    def _refresh_after_instances(self) -> None:
        self._instances_window = None
        selected = self.instance_store.selected()
        self._refresh_instances()
        self._apply_instance(selected)

    def _refresh_accounts(self) -> None:
        self._profile_ids = []
        self._profile_labels: dict[str, str] = {}
        labels = []
        for profile in self.store.profiles:
            label = profile.get("name", "")
            labels.append(label)
            self._profile_ids.append(profile["uuid"])
            self._profile_labels[label] = profile["uuid"]
        selected = self.store.selected()
        index = (self._profile_ids.index(selected["uuid"])
                 if selected and selected["uuid"] in self._profile_ids else None)
        for combo in (getattr(self, "header_profile_combo", None),
                      getattr(self, "profile_combo", None)):
            if combo is None:
                continue
            try:
                if not combo.winfo_exists():
                    continue
                combo.configure(values=labels)
                if index is None:
                    combo.set("")
                else:
                    combo.current(index)
            except tk.TclError:
                pass
        path = skins.skin_path(selected) if selected else None
        try:
            image = (skins.render_head(path, 30, (34, 31, 25, 255))
                     if path else skins.placeholder_head(30))
            self._account_head_photo = ImageTk.PhotoImage(image)
            self.account_head.configure(image=self._account_head_photo)
        except (OSError, ValueError, tk.TclError):
            pass
        self._update_skin_view()

    def _on_profile_change(self, _event=None) -> None:
        combo = getattr(self, "profile_combo", None)
        if combo is None:
            return
        profile_id = self._profile_labels.get(combo.get())
        if profile_id:
            self.store.select(profile_id)
            header = getattr(self, "header_profile_combo", None)
            if header is not None:
                label = next((text for text, pid in self._profile_labels.items()
                              if pid == profile_id), "")
                if label:
                    header.set(label)
            self._update_skin_view()

    def _on_header_profile_change(self, _event=None) -> None:
        profile_id = self._profile_labels.get(self.header_profile_combo.get())
        if profile_id:
            self.store.select(profile_id)
            self._refresh_accounts()

    def _add_offline(self) -> None:
        name = ui.ask_text(
            self, "Cuenta local",
            "Nombre de jugador (3-16 letras, números o _):")
        if not name:
            return
        try:
            profile = self.store.add_offline(name)
        except ValueError as exc:
            ui.show_error(self, "Cuenta local", str(exc))
            return
        self._refresh_accounts()
        self._log(f"Cuenta offline creada: {profile['name']}", "ok")

    def _delete_account(self) -> None:
        profile = self.store.selected()
        if not profile:
            return
        if not ui.ask_confirm(
                self, "Eliminar cuenta",
                f"¿Eliminar la cuenta {profile['name']} y su skin local?",
                ok_text="Eliminar"):
            return
        self.store.remove(profile["uuid"])
        self._refresh_accounts()
        self._log(f"Cuenta eliminada: {profile['name']}", "dim")

    def _update_skin_view(self) -> None:
        if not hasattr(self, "skin_name") or not self.skin_name.winfo_exists():
            return
        profile = self.store.selected()
        if profile:
            path = skins.skin_path(profile)
            if path:
                self.skin_hint.configure(
                    text=("Skin local. Súbela a Mojang para usarla online."
                          if profile.get("type") == "microsoft" else
                          "Skin importada. Se copiará a CustomSkinLoader al jugar."))
            else:
                self.skin_hint.configure(text="Importa un PNG de 64x64 o 64x32.")
            self.skin_name.configure(text=profile.get("name", ""))
            is_ms = profile.get("type") == "microsoft"
            self.skin_kind.configure(text="Cuenta Microsoft" if is_ms
                                     else "Cuenta local")
            self.variant_var.set("Slim" if profile.get("skin_variant") == "slim"
                                 else "Clásica")
            self.import_btn.configure(state="normal")
            self.remove_btn.configure(state="normal" if path else "disabled")
            self.delete_btn.configure(state="normal")
            self.upload_btn.configure(
                state="normal" if (is_ms and path) else "disabled")
            self.variant_combo.configure(state="readonly" if is_ms else "disabled")
        else:
            self.skin_name.configure(text="Sin cuenta")
            self.skin_kind.configure(text="")
            self.skin_hint.configure(
                text="Crea una cuenta local o inicia sesión con Microsoft.")
            for button in (self.import_btn, self.remove_btn, self.upload_btn,
                           self.delete_btn):
                button.configure(state="disabled")
            self.variant_combo.configure(state="disabled")
        self._refresh_stage()

    def _on_stage_resize(self, _event=None) -> None:
        if self._stage_job is not None:
            try:
                self.after_cancel(self._stage_job)
            except tk.TclError:
                pass
        self._stage_job = self.after(80, self._refresh_stage)

    def _refresh_stage(self) -> None:
        self._stage_job = None
        holder = getattr(self, "stage_holder", None)
        if holder is None or not holder.winfo_exists():
            return
        self.stage_holder = holder
        profile = self.store.selected()
        path = skins.skin_path(profile) if profile else None
        width = max(self.stage_holder.winfo_width() - 2, 140)
        height = max(self.stage_holder.winfo_height() - 2, 120)
        scale = max(2, min(8, min((height - 20) // 32, (width - 24) // 16)))
        stamp = path.stat().st_mtime_ns if path and path.exists() else 0
        key = (str(path), stamp, width, height, scale)
        if key == self._stage_key:
            return
        self._stage_key = key
        if path:
            body = skins.render_body(path, scale)
        else:
            body = skins.placeholder_body(scale, (0, 0, 0, 0))
        stage = ui.skin_stage(body, width, height)
        self._stage_photo = ImageTk.PhotoImage(stage)
        self.stage_label.configure(image=self._stage_photo, text="")

    def _import_skin(self) -> None:
        profile = self.store.selected()
        if not profile:
            return
        chosen = filedialog.askopenfilename(
            parent=self, title="Importar skin",
            filetypes=[("Skin PNG", "*.png")])
        if not chosen:
            return
        try:
            skins.import_skin(profile, Path(chosen))
        except skins.SkinError as exc:
            ui.show_error(self, "Skin no válida", str(exc))
            return
        self.store.save()
        self._refresh_accounts()
        self._log(f"Skin importada para {profile['name']}", "ok")

    def _remove_skin(self) -> None:
        profile = self.store.selected()
        if not profile:
            return
        path = skins.skin_path(profile)
        if not path:
            return
        if not ui.ask_confirm(self, "Quitar skin",
                              "¿Quitar la skin local de esta cuenta?",
                              ok_text="Quitar"):
            return
        try:
            path.unlink()
        except OSError:
            pass
        profile["skin"] = ""
        self.store.save()
        self._refresh_accounts()
        self._log("Skin eliminada", "dim")

    def _on_variant_change(self, _event=None) -> None:
        profile = self.store.selected()
        if not profile or profile.get("type") != "microsoft":
            return
        profile["skin_variant"] = ("slim" if self.variant_var.get() == "Slim"
                                   else "classic")
        self.store.save()

    def _upload_skin(self) -> None:
        profile = self.store.selected()
        if not profile or profile.get("type") != "microsoft":
            return
        path = skins.skin_path(profile)
        if not path:
            return
        variant = "slim" if self.variant_var.get() == "Slim" else "classic"
        self.upload_btn.configure(state="disabled")
        self._log("Subiendo skin a Mojang...", "dim")

        def work():
            try:
                accounts.ensure_access_token(
                    profile, self.settings.get("client_id", ""),
                    on_token=lambda _profile: self.store.save())
                self.store.save()
                skins.upload_skin(profile, variant)
            except (AuthError, skins.SkinError) as exc:
                self._post("skin_upload_error", msg=str(exc))
            except Exception as exc:
                self._post("skin_upload_error", msg=f"Error inesperado: {exc}")
            else:
                self._post("skin_uploaded", name=profile["name"])

        threading.Thread(target=work, daemon=True).start()

    def _microsoft_login(self) -> None:
        if self._auth_cancel is not None:
            return
        if not (self.settings.get("client_id") or "").strip():
            if ui.ask_confirm(
                    self, "Cuenta Microsoft",
                    "Para iniciar sesión con Microsoft necesitas un Client ID de "
                    "Azure configurado en Ajustes.\n\n"
                    "Las cuentas locales funcionan sin configurar nada.\n\n"
                    "¿Abrir Ajustes ahora?", ok_text="Abrir Ajustes",
                    danger=False):
                self._open_settings()
            return
        self._auth_cancel = threading.Event()
        client_id = self.settings["client_id"]
        self.status_var.set("Iniciando sesión con Microsoft...")
        self._log("Solicitando código de dispositivo a Microsoft...", "dim")

        def work():
            try:
                data = accounts.microsoft_login(
                    client_id, cancel_event=self._auth_cancel,
                    on_status=lambda text: self._post("ms_status", text=text),
                    on_code=lambda flow: self._post("ms_code", flow=flow))
            except AuthError as exc:
                self._post("ms_error", msg=str(exc))
            except Exception as exc:
                self._post("ms_error", msg=f"Error inesperado: {exc}")
            else:
                self._post("ms_done", data=data)

        threading.Thread(target=work, daemon=True).start()

    def _show_device_window(self, flow: dict) -> None:
        self._close_auth_window()
        win = tk.Toplevel(self)
        win.title("Microsoft · Blockys")
        win.configure(bg=BG)
        win.geometry("520x406")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        ui.set_app_icon(win)
        win.after(80, lambda: ui.enable_dark_titlebar(win))

        box = tk.Frame(win, bg=PANEL, highlightbackground=BORDER,
                       highlightthickness=1)
        box.pack(fill="both", expand=True, padx=20, pady=20)
        inner = tk.Frame(box, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=24, pady=22)

        tk.Label(inner, text="Iniciar sesión", bg=PANEL, fg=TEXT,
                 font=(DISPLAY, 20)).pack(anchor="w")
        url = flow.get("verification_uri") or "https://microsoft.com/link"
        tk.Label(inner, text=f"Abre {url} e introduce este código:",
                 bg=PANEL, fg=MUTED, font=(FONT, 9), wraplength=420,
                 justify="left").pack(anchor="w", pady=(5, 12))

        code = flow.get("user_code", "")
        code_frame = tk.Frame(inner, bg=CARD, highlightbackground=BORDER,
                              highlightthickness=1)
        code_frame.pack(fill="x")
        tk.Label(code_frame, text=code, bg=CARD, fg=ACCENT,
                 font=(MONO, 28), pady=12).pack()

        self._auth_status = tk.StringVar(value="Esperando autorización...")
        tk.Label(inner, textvariable=self._auth_status, bg=PANEL, fg=MUTED,
                 font=(FONT, 8), wraplength=420, justify="left").pack(
            anchor="w", pady=(10, 4))

        buttons = tk.Frame(inner, bg=PANEL)
        buttons.pack(fill="x", side="bottom")

        def copy_code():
            win.clipboard_clear()
            win.clipboard_append(code)
            self._auth_status.set("Código copiado al portapapeles")

        def open_page():
            webbrowser.open(url)

        def cancel():
            if self._auth_cancel is not None:
                self._auth_cancel.set()
            self._close_auth_window()

        ui.Button(buttons, "Copiar código", command=copy_code, width=136,
                  height=36).pack(side="left")
        ui.Button(buttons, "Abrir página", kind="primary", command=open_page,
                  width=148, height=36).pack(side="left", padx=8)
        ui.Button(buttons, "Cancelar", kind="quiet", command=cancel, width=100,
                  height=36).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", cancel)
        self._auth_window = win
        webbrowser.open(url)

    def _close_auth_window(self) -> None:
        if self._auth_window is not None:
            try:
                self._auth_window.destroy()
            except tk.TclError:
                pass
        self._auth_window = None
        self._auth_status = None

    def _play(self) -> None:
        if self._busy or self._game is not None:
            return
        override, self._quick_play_override = self._quick_play_override, None
        instance = self._instance
        profile = self.store.selected()
        wanted = (instance or {}).get("account", "")
        if wanted:
            match = next((item for item in self.store.profiles
                          if item.get("name") == wanted), None)
            if match:
                profile = match
            else:
                self._log(f"La cuenta {wanted} de la instancia ya no existe; "
                          "se usa la cuenta activa.", "warn")
        if not profile:
            ui.show_warning(self, "Cuenta",
                            "Crea una cuenta local o inicia sesión.")
            return
        if instance is not None:
            entry = (versions.find_entry(self.manifest, instance["version"])
                     if self.manifest else None)
            if not entry:
                ui.show_warning(
                    self, "Instancia",
                    "No se encontró la versión de la instancia en el manifiesto. "
                    "Actualizá las versiones o editá la instancia.")
                return
        else:
            entry = self._current_version_entry()
            if not entry:
                ui.show_warning(self, "Versión",
                                "Selecciona una versión de Minecraft.")
                return
        settings = self._collect_settings(override)
        folder = Path(settings["game_dir"])
        if folder.exists() and not folder.is_dir():
            ui.show_error(self, "Carpeta del juego",
                          "La ruta configurada no es una carpeta válida.")
            return
        self._busy = True
        self._cancel = threading.Event()
        self.play_btn.configure(state="disabled", text="PREPARANDO...")
        self.cancel_btn.configure(state="normal")
        self.cancel_btn.pack(side="right", padx=(8, 0))
        self.progress["value"] = 0
        self.status_var.set("Preparando...")
        self._log(f"Preparando Minecraft {entry['id']} para {profile['name']}...", "dim")
        threading.Thread(target=self._launch_worker,
                         args=(entry, profile, settings, instance),
                         daemon=True).start()

    def _launch_worker(self, entry: dict, profile: dict, settings: dict,
                       instance: dict | None = None) -> None:
        try:
            if instance and instance.get("backup_before_launch"):
                game_dir = Path(settings["game_dir"])
                if game_dir.is_dir():
                    self._post("status", text="Respaldando mundos...")
                    count = backups.auto_backup(
                        game_dir, int(instance.get("backup_keep", 5)),
                        on_status=lambda text: self._post("status", text=text),
                        cancel_event=self._cancel)
                    if count:
                        self._log(f"Respaldos automáticos: {count} mundo(s)",
                                  "dim")
            if profile.get("type") == "microsoft":
                self._post("status", text="Comprobando sesión de Microsoft...")
                accounts.ensure_access_token(
                    profile, settings.get("client_id", ""),
                    on_token=lambda _profile: self.store.save())
                self.store.save()
                self._post("profiles")
            self._post("status", text="Leyendo versión...")
            base_data = versions.get_version_json(entry)
            features = versions.default_features(settings)
            loader = (instance or {}).get("loader", "vanilla")
            has_loader = bool(instance) and loader != "vanilla"
            base_end = 0.45 if has_loader else 0.86
            last = [0.0]

            def base_progress(fraction, text):
                now = time.time()
                if fraction >= 1 or now - last[0] > 0.12:
                    last[0] = now
                    self._post("progress", frac=0.02 + fraction * (base_end - 0.02),
                               text=text)

            self._post("progress", frac=0.02, text="Descargando archivos...")
            plan = versions.install(
                entry, base_data, settings, features, on_progress=base_progress,
                on_status=lambda text: self._post("status", text=text),
                cancel_event=self._cancel)
            if self._cancel.is_set():
                raise net.Cancelled()

            if has_loader:
                resolved = (instance or {}).get("resolved_version", "")
                loader_version = (instance or {}).get("loader_version", "")
                resolved_data = versions.read_version_json(resolved) if resolved else None
                if resolved_data and resolved_data.get("inheritsFrom") != instance["version"]:
                    resolved_data = None
                if not (resolved_data and loader_version):
                    self._post("status", text=f"Preparando {loader.title()}...")

                    def loader_progress(fraction, text):
                        self._post("progress", frac=0.45 + fraction * 0.15,
                                   text=text)

                    info = loaders.ensure(
                        loader, instance["version"], settings, base_data,
                        loader_version=loader_version,
                        on_status=lambda text: self._post("status", text=text),
                        on_progress=loader_progress, cancel_event=self._cancel)
                    resolved = info["version_id"]
                    loader_version = info["loader_version"]
                    self._post("instance_ready", id=instance["id"],
                               resolved_version=resolved,
                               loader_version=loader_version)
                    self._post("status", text=f"{loader.title()} listo. Preparando archivos...")
                if not resolved:
                    raise RuntimeError("No se pudo resolver el cargador de la instancia")
                loader_entry = {"id": resolved}
                loader_data = versions.get_version_json(loader_entry)
                last[0] = 0.0

                def loader_files_progress(fraction, text):
                    now = time.time()
                    if fraction >= 1 or now - last[0] > 0.12:
                        last[0] = now
                        self._post("progress", frac=0.62 + fraction * 0.24,
                                   text=text)

                plan = versions.install(
                    loader_entry, loader_data, settings, features,
                    on_progress=loader_files_progress,
                    on_status=lambda text: self._post("status", text=text),
                    cancel_event=self._cancel)
                if self._cancel.is_set():
                    raise net.Cancelled()

            self._post("status", text=f"Preparando Java Temurin {plan.java_major}...")

            def java_progress(fraction, _text):
                self._post("progress", frac=0.88 + fraction * 0.08,
                           text=f"Java Temurin {plan.java_major}")

            from . import java as java_module
            java_exe = java_module.resolve_java(
                settings, plan.java_major, on_progress=java_progress,
                on_status=lambda text: self._post("status", text=text),
                cancel_event=self._cancel)
            if self._cancel.is_set():
                raise net.Cancelled()

            if settings.get("copy_skin_mod") and skins.skin_path(profile):
                try:
                    skins.copy_for_customskinloader(profile, Path(settings["game_dir"]))
                except OSError as exc:
                    self._post("log",
                               text=f"No se pudo copiar la skin local: {exc}",
                               tag="warn")

            hook = launch.run_hook(settings, "pre_launch",
                                   Path(settings["game_dir"]))
            if hook:
                code, output = hook
                self._post("log", text=f"Comando previo: código {code}",
                           tag="ok" if code == 0 else "warn")
                for line in output.splitlines()[-4:]:
                    self._post("log", text=line, tag="dim")

            if self._cancel.is_set():
                raise net.Cancelled()
            self._post("progress", frac=0.98, text="Iniciando Minecraft...")
            process, log_path, handle = launch.start_game(plan, profile, settings,
                                                          java_exe)
            self._post("game_started", proc=process, log=log_path, handle=handle,
                       id=(instance or {}).get("id", ""))
            code = process.wait()
            try:
                handle.close()
            except OSError:
                pass
            hook = launch.run_hook(settings, "post_exit",
                                   Path(settings["game_dir"]))
            if hook:
                hook_code, output = hook
                self._post("log", text=f"Comando posterior: código {hook_code}",
                           tag="ok" if hook_code == 0 else "warn")
                for line in output.splitlines()[-4:]:
                    self._post("log", text=line, tag="dim")
            tail: list[str] = []
            try:
                encoding = "mbcs" if sys.platform == "win32" else "utf-8"
                lines = log_path.read_text(encoding=encoding,
                                           errors="replace").splitlines()
                tail = [line for line in lines if line.strip()][-8:]
            except OSError:
                pass
            self._post("game_exit", code=code, tail=tail, log=str(log_path))
        except net.Cancelled:
            self._post("launch_cancelled")
        except AuthError as exc:
            self._post("launch_error", msg=str(exc))
        except Exception as exc:
            self._post("launch_error", msg=str(exc), detail=traceback.format_exc())

    def _cancel_launch(self) -> None:
        if not self._busy or self._game is not None:
            return
        self._cancel.set()
        self.cancel_btn.configure(state="disabled")
        self.status_var.set("Cancelando...")
        self._log("Cancelando inicio...", "dim")

    def _hide_cancel(self) -> None:
        try:
            self.cancel_btn.pack_forget()
        except tk.TclError:
            pass

    def _auto_check_updates(self) -> None:
        if self._update_check_started or self._update_downloading:
            return
        self._update_check_started = True
        if not updates.is_self_update_supported():
            return

        def work():
            try:
                info = updates.check_latest()
            except Exception:
                return
            if info.get("newer") and info.get("installer"):
                self._post("update_ready", info=info)

        threading.Thread(target=work, daemon=True).start()

    def _offer_update(self, info: dict) -> None:
        if not self.winfo_exists() or self._update_downloading:
            return
        if not updates.is_self_update_supported():
            if ui.ask_confirm(
                    self, "Actualización disponible",
                    f"Tenés la {info.get('current', __version__)} y la última "
                    f"publicada es {info.get('tag', '')}.\n\n¿Abrir la página "
                    "de descarga?",
                    ok_text="Abrir página", danger=False):
                webbrowser.open(info.get("url") or updates.RELEASES_URL)
            return
        if not info.get("installer"):
            if ui.ask_confirm(
                    self, "Actualización disponible",
                    f"Hay una versión nueva ({info.get('tag', '')}) pero la "
                    "publicación no incluye instalador.\n\n¿Abrir la página de "
                    "descarga?",
                    ok_text="Abrir página", danger=False):
                webbrowser.open(info.get("url") or updates.RELEASES_URL)
            return
        notes = []
        for line in str(info.get("notes") or "").splitlines():
            line = line.strip().lstrip("#").strip()
            if not line or line.startswith("!["):
                continue
            notes.append(f"· {line}")
            if len(notes) >= 5:
                break
        message = (f"Hay una versión nueva: Blockys {info.get('tag', '')} "
                   f"(tenés la {info.get('current', __version__)}).\n\n"
                   "¿Descargar el instalador y actualizar ahora? Blockys se "
                   "cerrará, se instalará la versión nueva y se abrirá de "
                   "nuevo solo.")
        if notes:
            message += "\n\nNovedades:\n" + "\n".join(notes)
        if not ui.ask_confirm(self, "Actualización disponible", message,
                              ok_text="Actualizar ahora", danger=False):
            return
        self._start_self_update(info)

    def _start_self_update(self, info: dict) -> None:
        if self._update_downloading:
            return
        if self._game is not None:
            ui.show_warning(self, "Minecraft está abierto",
                            "Cerrá el juego antes de actualizar Blockys.")
            return
        if self._busy:
            ui.show_warning(self, "Blockys está ocupado",
                            "Esperá a que termine la tarea actual.")
            return
        self._update_downloading = True
        tag = info.get("tag", "")
        self.progress["value"] = 0
        self.status_var.set(f"Descargando Blockys {tag}...")
        self._log(f"Descargando actualización {tag}", "dim")
        cancel_event = threading.Event()
        self._update_cancel = cancel_event

        def progress(done, total, _files_done, _files_total):
            pct = int(done * 100 / total) if total else 0
            self._post("update_progress", pct=pct, tag=tag)

        def work():
            try:
                setup = updates.download_update(
                    info, on_progress=progress, cancel_event=cancel_event)
                updates.apply_update(setup)
            except Exception as exc:
                self._post("update_error", msg=str(exc))
            else:
                self._post("update_ready_to_install", name=setup.name)

        threading.Thread(target=work, daemon=True).start()

    def _quit_for_update(self) -> None:
        if self._game is not None:
            return
        if self._settings_job is not None:
            try:
                self.after_cancel(self._settings_job)
            except tk.TclError:
                pass
            self._settings_job = None
            try:
                self._persist_ui_settings()
            except (OSError, tk.TclError, ValueError):
                pass
        if self._pump_job is not None:
            try:
                self.after_cancel(self._pump_job)
            except tk.TclError:
                pass
            self._pump_job = None
        self.destroy()

    def _on_close(self) -> None:
        if self._game is not None:
            if not ui.ask_confirm(
                    self, "Minecraft está abierto",
                    "El juego sigue en ejecución. ¿Cerrar el launcher de todos "
                    "modos?", ok_text="Cerrar launcher"):
                return
        if self._busy and self._game is None:
            try:
                self._cancel.set()
            except AttributeError:
                pass
        if self._settings_job is not None:
            try:
                self.after_cancel(self._settings_job)
            except tk.TclError:
                pass
            self._settings_job = None
            try:
                self._persist_ui_settings()
            except (OSError, tk.TclError, ValueError):
                pass
        if self._pump_job is not None:
            try:
                self.after_cancel(self._pump_job)
            except tk.TclError:
                pass
            self._pump_job = None
        self.destroy()


class HelpDialog(tk.Toplevel):
    def __init__(self, app: LauncherApp):
        super().__init__(app)
        self.app = app
        self.title("Ayuda · Blockys")
        area_x, area_y, area_w, area_h = ui.work_area_rect()
        width = min(660, area_w - 60)
        height = min(700, area_h - 70)
        self.geometry(f"{width}x{height}"
                      f"+{area_x + (area_w - width) // 2}"
                      f"+{area_y + max(0, (area_h - height - 40) // 2)}")
        self.minsize(min(580, area_w - 80), min(520, height))
        self.configure(bg=BG)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._close)
        ui.set_app_icon(self)
        self.after(80, lambda: ui.enable_dark_titlebar(self))

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=26, pady=(18, 10))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", anchor="s")
        tk.Label(titles, text="CENTRO DE AYUDA", bg=BG, fg=TEXT,
                 font=(DISPLAY, 20)).pack(anchor="w")
        tk.Label(titles, text=f"Blockys {__version__} · Minecraft Java",
                 bg=BG, fg=FAINT, font=(FONT, 8)).pack(anchor="w", pady=(1, 0))
        ui.Button(header, "Cerrar", command=self._close, width=88, height=32,
                  font=(FONT, 8)).pack(side="right", anchor="s")

        footer = tk.Frame(self, bg=BG)
        footer.pack(side="bottom", fill="x", padx=26, pady=(10, 18))
        tk.Frame(footer, bg=BORDER_SOFT, height=1).pack(fill="x", pady=(0, 12))
        actions = tk.Frame(footer, bg=BG)
        actions.pack(fill="x")
        ui.Button(actions, "Exportar diagnóstico", kind="primary",
                  command=app._export_diagnostics, width=172, height=36,
                  font=(FONT, 9)).pack(side="left")
        ui.Button(actions, "Abrir datos", command=app._open_data_folder,
                  width=104, height=36, font=(FONT, 8)).pack(
            side="right", padx=(6, 0))
        ui.Button(actions, "Abrir logs", command=app._open_logs_folder,
                  width=100, height=36, font=(FONT, 8)).pack(
            side="right", padx=(6, 0))
        ui.Button(actions, "Limpiar caché", command=app._clear_cache,
                  width=110, height=36, font=(FONT, 8)).pack(
            side="right", padx=(6, 0))

        body = tk.Frame(self, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        body.pack(fill="both", expand=True, padx=26)
        scroll = ui.ScrollFrame(body, bg=PANEL)
        scroll.pack(fill="both", expand=True, padx=(18, 10), pady=14)
        content = scroll.content

        def paragraph(text: str, color=MUTED, size=9, top=5) -> None:
            ui.label(content, text, size=size, color=color, wrap=560).pack(
                fill="x", pady=(top, 0))

        ui.section(content, "Primeros pasos").pack(fill="x")
        paragraph("1. Elegí una cuenta en la cabecera. Podés crear una cuenta "
                  "offline sin registrarte.")
        paragraph("2. Pulsá Añadir instancia, elegí versión de Minecraft y "
                  "cargador. Cada instancia tiene su propia carpeta, mods y "
                  "mundos.")
        paragraph("3. Pulsá JUGAR. La primera vez Blockys descarga las "
                  "librerías, assets y Java Temurin automáticamente.")

        ui.divider(content, top=18, bottom=14)
        ui.section(content, "Atajos").pack(fill="x")
        shortcuts = (
            ("F5", "Actualizar el catálogo de versiones"),
            ("F1", "Abrir este centro de ayuda"),
            ("Ctrl+N", "Crear una instancia nueva"),
            ("Ctrl+,", "Abrir Ajustes"),
            ("Doble clic", "Seleccionar y jugar una instancia"),
            ("Enter / Esc", "Confirmar o cancelar un diálogo"),
        )
        for key, text in shortcuts:
            row = tk.Frame(content, bg=PANEL)
            row.pack(fill="x", pady=(5, 0))
            tk.Label(row, text=key, bg=PANEL, fg=ACCENT, width=12, anchor="w",
                     font=(MONO, 8)).pack(side="left")
            ui.label(row, text, size=9, color=MUTED).pack(side="left")

        ui.divider(content, top=18, bottom=14)
        ui.section(content, "Copias de seguridad").pack(fill="x")
        paragraph("En la pestaña Mundos podés respaldar un mundo o todos de "
                  "una vez. Los ZIP quedan en backups dentro de la instancia y "
                  "se restauran desde la misma pestaña; el mundo anterior se "
                  "conserva como .old.")
        paragraph("En Avanzado se activa el respaldo automático antes de cada "
                  "partida y cuántas copias conservar por mundo.")
        paragraph("La pestaña Registros incluye Compartir: sube el log a "
                  "mclo.gs y copia el enlace al portapapeles.")

        ui.divider(content, top=18, bottom=14)
        ui.section(content, "Si algo falla").pack(fill="x")
        paragraph("La pestaña Consola muestra el registro en vivo. El botón "
                  "Diagnóstico revisa errores comunes de memoria, Java, mods y "
                  "gráficos.")
        paragraph("Si Minecraft se cierra solo, Blockys analiza el registro y "
                  "te muestra una sugerencia. También podés exportar un ZIP de "
                  "diagnóstico desde esta ventana; no contiene tokens ni "
                  "contraseñas.")
        paragraph("Los registros del launcher y del juego quedan en "
                  "%APPDATA%\\BloqueLauncher\\logs. Las instancias y cuentas "
                  "nunca se borran al actualizar o desinstalar Blockys.")

        ui.divider(content, top=18, bottom=14)
        ui.section(content, "Actualizaciones").pack(fill="x")
        paragraph("La versión instalada se actualiza sola: al abrir Blockys "
                  "se comprueba la última publicación de GitHub y, si hay una "
                  "nueva, se descarga el instalador oficial, se instala en "
                  "segundo plano y el launcher se abre de nuevo actualizado. "
                  "Se puede desactivar en Ajustes.")
        update_row = tk.Frame(content, bg=PANEL)
        update_row.pack(fill="x", pady=(6, 0))
        self.update_btn = ui.Button(update_row, "Buscar actualizaciones",
                                    kind="quiet", command=self._check_updates,
                                    width=176, height=32, font=(FONT, 8))
        self.update_btn.pack(side="left")
        self.update_status = tk.Label(
            update_row, text=f"Versión instalada: {__version__}",
            bg=PANEL, fg=FAINT, font=(FONT, 8), anchor="w")
        self.update_status.pack(side="left", fill="x", expand=True,
                                padx=(10, 0))

        ui.divider(content, top=18, bottom=14)
        ui.section(content, "Información").pack(fill="x")
        paragraph("Novedades de 1.0.5: copias de seguridad de mundos con "
                  "restauración, retención y respaldo automático antes de "
                  "cada partida; cada instancia puede usar su propia cuenta; "
                  "los registros se comparten con un enlace de mclo.gs; "
                  "Ajustes incluye proxy HTTP para descargas y para el juego; "
                  "y el launcher se actualiza solo a la última versión de "
                  "GitHub.")
        paragraph("Blockys no distribuye Minecraft. Para jugar en servidores "
                  "premium necesitás una licencia oficial de Minecraft Java "
                  "Edition. No está afiliado a Mojang, Microsoft, Modrinth ni "
                  "Prism Launcher.")

        tk.Frame(content, bg=PANEL, height=6).pack(fill="x")

    def _check_updates(self) -> None:
        self.update_btn.configure(state="disabled")
        self.update_status.configure(text="Buscando actualizaciones...",
                                     fg=FAINT)

        def work():
            try:
                result = updates.check_latest()
            except updates.UpdateError as exc:
                message = str(exc)
                self._post_update(lambda: self._update_failed(message, True))
            except Exception as exc:
                message = f"Error inesperado: {exc}"
                self._post_update(lambda: self._update_failed(message, False))
            else:
                self._post_update(lambda: self._show_update(result))

        threading.Thread(target=work, daemon=True).start()

    def _post_update(self, callback) -> None:
        try:
            self.after(0, callback)
        except tk.TclError:
            pass

    def _update_failed(self, message: str, warn: bool) -> None:
        if not self.winfo_exists():
            return
        self.update_btn.configure(state="normal")
        self.update_status.configure(text=message, fg=WARN if warn else DANGER)

    def _show_update(self, result: dict) -> None:
        if not self.winfo_exists():
            return
        self.update_btn.configure(state="normal")
        if result["newer"]:
            self.update_status.configure(
                text=f"Hay una versión nueva: {result['tag']}", fg=GRASS)
            self.app._offer_update(result)
        else:
            self.update_status.configure(
                text=f"Estás al día ({result['current']})", fg=GRASS)

    def _close(self) -> None:
        if self.app._help_window is self:
            self.app._help_window = None
        self.destroy()


class WelcomeDialog(tk.Toplevel):
    def __init__(self, app: LauncherApp):
        super().__init__(app)
        self.app = app
        self.title("Bienvenido a Blockys")
        width, height = 540, 500
        x = app.winfo_rootx() + max(0, (app.winfo_width() - width) // 2)
        y = app.winfo_rooty() + max(0, (app.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._finish)
        ui.set_app_icon(self)
        self.after(80, lambda: ui.enable_dark_titlebar(self))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=30, pady=24)

        mark = tk.Frame(body, bg=CARD, width=58, height=58,
                        highlightbackground=BORDER_SOFT, highlightthickness=1)
        mark.pack(anchor="w")
        mark.pack_propagate(False)
        tk.Label(mark, image=app._logo_photo, bg=CARD, bd=0).pack(expand=True)

        tk.Label(body, text="Bienvenido a Blockys", bg=BG, fg=TEXT,
                 font=(DISPLAY, 22)).pack(anchor="w", pady=(16, 0))
        tk.Label(body, text=f"Versión {__version__} · tu launcher de Minecraft Java",
                 bg=BG, fg=FAINT, font=(FONT, 9)).pack(anchor="w", pady=(3, 0))

        for title, text in (
                ("Cuentas", "Jugá offline con un nombre, o conectá tu cuenta "
                            "Microsoft desde Cuentas."),
                ("Instancias aisladas", "Cada mundo, mod y configuración vive "
                                        "en su propia carpeta."),
                ("Todo automático", "Java Temurin, librerías, Fabric, Quilt, "
                                    "Forge y NeoForge se preparan al jugar."),
                ("Si algo falla", "La consola y el diagnóstico te ayudan a "
                                  "encontrar la causa.")):
            row = tk.Frame(body, bg=PANEL, highlightbackground=BORDER_SOFT,
                           highlightthickness=1)
            row.pack(fill="x", pady=(10, 0))
            info = tk.Frame(row, bg=PANEL)
            info.pack(fill="x", padx=12, pady=9)
            tk.Label(info, text=title, bg=PANEL, fg=TEXT,
                     font=(FONT, 10, "bold")).pack(anchor="w")
            tk.Label(info, text=text, bg=PANEL, fg=MUTED, font=(FONT, 8),
                     wraplength=440, justify="left").pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(body, bg=BG)
        actions.pack(fill="x", side="bottom", pady=(18, 0))
        ui.Button(actions, "Crear mi primera instancia", kind="primary",
                  command=lambda: self._finish(app._open_instances, create=True),
                  width=212, height=40, font=(FONT, 9)).pack(side="left")
        ui.Button(actions, "Agregar cuenta",
                  command=lambda: self._finish(app._open_accounts),
                  width=126, height=40, font=(FONT, 8)).pack(
            side="left", padx=(8, 0))
        ui.Button(actions, "Explorar", command=self._finish, width=92,
                  height=40, font=(FONT, 8)).pack(side="right")

    def _finish(self, action=None, **kwargs) -> None:
        self.app.settings["onboarding_done"] = True
        try:
            paths.save_settings(self.app.settings)
        except OSError:
            pass
        if self.app._welcome_window is self:
            self.app._welcome_window = None
        self.destroy()
        if action is not None:
            self.app.after(80, lambda: action(**kwargs))


class AccountsDialog(tk.Toplevel):
    def __init__(self, app: LauncherApp):
        super().__init__(app)
        self.app = app
        self.title("Cuenta y skins · Blockys")
        area_x, area_y, area_w, area_h = ui.work_area_rect()
        width = min(478, area_w - 60)
        height = min(720, area_h - 60)
        self.geometry(f"{width}x{height}"
                      f"+{area_x + (area_w - width) // 2}"
                      f"+{area_y + max(0, (area_h - height - 40) // 2)}")
        self.minsize(min(430, area_w - 80), min(560, height))
        self.configure(bg=BG)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._close)
        ui.set_app_icon(self)
        self.after(80, lambda: ui.enable_dark_titlebar(self))

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=22, pady=(16, 10))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", anchor="s")
        tk.Label(titles, text="CUENTA Y SKIN", bg=BG, fg=TEXT,
                 font=(DISPLAY, 20)).pack(anchor="w")
        tk.Label(titles, text="Perfiles, skins y variantes de la cuenta activa",
                 bg=BG, fg=FAINT, font=(FONT, 8)).pack(anchor="w", pady=(1, 0))
        ui.Button(header, "Cerrar", command=self._close, width=88, height=32,
                  font=(FONT, 8)).pack(side="right", anchor="s")

        body = tk.Frame(self, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 20))
        app._build_left(body)
        app._refresh_accounts()

    def _close(self) -> None:
        if self.app._accounts_window is self:
            self.app._accounts_window = None
        self.destroy()


def main() -> None:
    diagnostics.install_exception_hooks()
    app = LauncherApp()

    def report_callback(exc, value, tb):
        app._handle_unexpected_error((exc, value, tb), "interfaz")

    app.report_callback_exception = report_callback
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
