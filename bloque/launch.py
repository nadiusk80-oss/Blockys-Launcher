from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, paths
from .versions import InstallPlan, default_features, rules_allow

LAUNCHER_NAME = "Blockys"
CLIENT_ID = "b1f6f3b8-3c9e-4a1e-9d3a-1b0f4c2d7e55"
LOG_KEEP = 20

AIKAR_FLAGS = (
    "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled",
    "-XX:MaxGCPauseMillis=200", "-XX:+UnlockExperimentalVMOptions",
    "-XX:+DisableExplicitGC", "-XX:G1NewSizePercent=30",
    "-XX:G1MaxNewSizePercent=40", "-XX:G1HeapRegionSize=8M",
    "-XX:G1ReservePercent=20", "-XX:G1HeapWastePercent=5",
    "-XX:G1MixedGCCountTarget=4", "-XX:InitiatingHeapOccupancyPercent=15",
    "-XX:G1MixedGCLiveThresholdPercent=90",
    "-XX:G1RSetUpdatingPauseTimePercent=5", "-XX:SurvivorRatio=32",
    "-XX:+PerfDisableSharedMem", "-XX:MaxTenuringThreshold=1",
)


def _substitute(text: str, subs: dict) -> str:
    return re.sub(r"\$\{([A-Za-z0-9_]+)\}",
                  lambda match: str(subs.get(match.group(1), match.group(0))),
                  text)


def _split_args(text: str) -> list[str]:
    """Divide argumentos respetando comillas en cualquier posicion."""
    result: list[str] = []
    buffer: list[str] = []
    quote = None
    for char in str(text or ""):
        if quote:
            if char == quote:
                quote = None
            else:
                buffer.append(char)
        elif char in ("'", '"'):
            quote = char
        elif char.isspace():
            if buffer:
                result.append("".join(buffer))
                buffer = []
        else:
            buffer.append(char)
    if buffer:
        result.append("".join(buffer))
    return result


def parse_env(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in str(text or "").splitlines():
        if line.strip().startswith("#"):
            continue
        for part in re.split(r";(?=\s*[A-Za-z_][A-Za-z0-9_]*\s*=)", line):
            part = part.strip()
            if not part or part.startswith("#") or "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            if key:
                env[key] = value.strip()
    return env


def run_hook(settings: dict, key: str, game_dir: Path,
             env: dict[str, str] | None = None,
             timeout: int = 600) -> tuple[int, str] | None:
    command = str(settings.get(key) or "").strip()
    if not command:
        return None
    merged = os.environ.copy()
    merged.update(parse_env(settings.get("env_vars", "")))
    if env:
        merged.update(env)
    try:
        result = subprocess.run(command, shell=True, cwd=str(game_dir),
                                capture_output=True, text=True, errors="replace",
                                env=merged, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, f"El comando superó {timeout} segundos y se canceló"
    except OSError as exc:
        return 1, str(exc)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def _resolve_entries(entries, features: dict, subs: dict) -> list[str]:
    result: list[str] = []
    for entry in entries or []:
        if isinstance(entry, str):
            result.append(_substitute(entry, subs))
        elif isinstance(entry, dict):
            if not rules_allow(entry.get("rules"), features):
                continue
            value = entry.get("value")
            if isinstance(value, str):
                result.append(_substitute(value, subs))
            elif isinstance(value, list):
                result.extend(_substitute(item, subs) for item in value if isinstance(item, str))
    return result


def build_command(plan: InstallPlan, profile: dict, settings: dict,
                  java_exe: Path) -> list[str]:
    is_ms = profile.get("type") == "microsoft"
    token = profile.get("access_token") if is_ms else "0"
    token = token or "0"
    uuid_hex = (profile.get("uuid") or "").replace("-", "")
    game_dir = Path(settings["game_dir"])
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "logs").mkdir(parents=True, exist_ok=True)
    features = default_features(settings)
    quick_type = settings.get("quick_play_type", "none")
    quick_target = str(settings.get("quick_play_target") or "").strip()
    if quick_type not in ("world", "server", "realms"):
        quick_target = ""

    subs = {
        "auth_player_name": profile.get("name") or "Jugador",
        "version_name": plan.version_id,
        "game_directory": str(game_dir),
        "assets_root": str(paths.ASSETS_DIR),
        "assets_index_name": plan.asset_index_id,
        "auth_uuid": uuid_hex,
        "auth_access_token": token,
        "auth_session": f"token:{token}:{uuid_hex}",
        "clientid": CLIENT_ID,
        "auth_xuid": profile.get("xuid") or "0",
        "user_type": "msa" if is_ms else "legacy",
        "user_properties": "{}",
        "version_type": plan.version_type,
        "game_assets": str(plan.virtual_dir) if plan.virtual_dir else str(paths.ASSETS_DIR),
        "natives_directory": str(plan.natives_dir),
        "launcher_name": LAUNCHER_NAME,
        "launcher_version": __version__,
        "classpath": os.pathsep.join(str(path) for path in plan.classpath),
        "classpath_separator": os.pathsep,
        "library_directory": str(paths.LIBRARIES_DIR),
        "resolution_width": str(settings.get("resolution_width", 1280)),
        "resolution_height": str(settings.get("resolution_height", 720)),
        "quickPlaySingleplayer": quick_target if quick_type == "world" else "",
        "quickPlayMultiplayer": quick_target if quick_type == "server" else "",
        "quickPlayRealms": quick_target if quick_type == "realms" else "",
        "quickPlayPath": str(game_dir / "logs" / "quickplay.log"),
    }

    arguments = plan.data.get("arguments")
    if arguments:
        jvm_args = _resolve_entries(arguments.get("jvm", []), features, subs)
        game_args = _resolve_entries(arguments.get("game", []), features, subs)
    else:
        jvm_args = [f"-Djava.library.path={plan.natives_dir}"]
        legacy = plan.data.get("minecraftArguments") or ""
        game_args = [_substitute(part, subs) for part in _split_args(legacy)]

    if not any(arg in ("-cp", "-classpath") or arg.startswith(("-cp=", "-classpath="))
               for arg in jvm_args):
        jvm_args.extend(["-cp", subs["classpath"]])

    if not any("minecraft.launcher.brand" in arg for arg in jvm_args):
        jvm_args.extend([
            f"-Dminecraft.launcher.brand={LAUNCHER_NAME}",
            f"-Dminecraft.launcher.version={__version__}",
        ])

    logging_cfg = (plan.data.get("logging") or {}).get("client") or {}
    if plan.log_config and "${path}" in (logging_cfg.get("argument") or ""):
        arg = logging_cfg["argument"].replace("${path}", str(plan.log_config))
        if not any("log4j.configurationFile" in item for item in jvm_args):
            jvm_args.append(arg)

    memory = int(settings.get("memory_mb", paths.DEFAULT_MEMORY_MB))
    if sys.maxsize <= 2**32:
        memory = min(memory, 1024)
    jvm_args.insert(0, f"-Xmx{memory}M")
    if settings.get("aikar_flags", True):
        existing = set(jvm_args)
        jvm_args.extend(flag for flag in AIKAR_FLAGS if flag not in existing)

    if settings.get("custom_resolution") and "--width" not in game_args:
        game_args.extend([
            "--width", str(settings.get("resolution_width", 1280)),
            "--height", str(settings.get("resolution_height", 720)),
        ])

    jvm_args.extend(_split_args(settings.get("jvm_args", "")))
    game_args.extend(_split_args(settings.get("game_args", "")))

    if quick_target:
        supports_quick = "quickPlay" in str(plan.data.get("arguments") or "")
        quick_arg = {"world": "--quickPlaySingleplayer",
                     "server": "--quickPlayMultiplayer",
                     "realms": "--quickPlayRealms"}[quick_type]
        if supports_quick and quick_arg not in game_args:
            game_args.extend([quick_arg, quick_target])

    return [str(java_exe)] + jvm_args + [plan.main_class] + game_args


def redact_command(command: list[str]) -> list[str]:
    redacted = []
    for index, arg in enumerate(command):
        previous = command[index - 1] if index else ""
        if previous in ("--accessToken", "--session"):
            redacted.append("***")
        else:
            redacted.append(arg)
    return redacted


def prune_logs(keep: int = LOG_KEEP) -> None:
    try:
        files = sorted(paths.LOGS_DIR.glob("game-*.log"),
                       key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[max(1, keep):]:
        try:
            old.unlink()
        except OSError:
            pass


def start_game(plan: InstallPlan, profile: dict, settings: dict,
               java_exe: Path) -> tuple[subprocess.Popen, Path, object]:
    command = build_command(plan, profile, settings, java_exe)
    game_dir = Path(settings["game_dir"])
    game_dir.mkdir(parents=True, exist_ok=True)
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    prune_logs()
    log_path = paths.LOGS_DIR / f"game-{time.strftime('%Y%m%d-%H%M%S')}.log"
    log_file = open(log_path, "wb")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    log_file.write((" ".join(redact_command(command)) + "\n\n").encode("utf-8"))
    log_file.flush()
    env = os.environ.copy()
    env.update(parse_env(settings.get("env_vars", "")))
    try:
        process = subprocess.Popen(
            command, cwd=str(game_dir), stdout=log_file,
            stderr=subprocess.STDOUT, creationflags=flags, env=env,
        )
    except Exception:
        log_file.close()
        raise
    return process, log_path, log_file
