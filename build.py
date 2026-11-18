from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = "Blockys"
DIST = ROOT / "dist"
IS_64 = sys.maxsize > 2**32


def version() -> str:
    text = (ROOT / "bloque" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("No se encontro __version__ en bloque/__init__.py")
    return match.group(1)


def version_info(app_version: str) -> Path:
    template = (ROOT / "packaging" / "version_info.txt").read_text(
        encoding="utf-8")
    parts = app_version.split(".")
    parts += ["0"] * (4 - len(parts))
    content = (template
               .replace("@VERSION_COMMA@", ", ".join(parts[:4]))
               .replace("@VERSION@", app_version))
    target = ROOT / "build" / "version_info.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _build_dir(arch: str) -> tuple[Path, Path, Path, Path]:
    if arch == "x86":
        target = DIST / "Blockys32"
        staging = DIST / "_x86_stage"
    else:
        target = DIST / APP
        staging = DIST
    work = ROOT / "build" / f"pyinstaller-{arch}"
    spec = ROOT / "build" / f"spec-{arch}"
    return target, staging, work, spec


def build_app(app_version: str, arch: str) -> Path:
    if arch == "x86" and IS_64:
        raise SystemExit(
            "El build de 32 bits necesita un Python de 32 bits. "
            "Ejecutá build.py con el Python x86.")
    if arch == "x64" and not IS_64:
        raise SystemExit(
            "El build de 64 bits necesita un Python de 64 bits. "
            "Ejecutá build.py con el Python x64.")

    target, staging, work, spec = _build_dir(arch)
    shutil.rmtree(target, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(spec, ignore_errors=True)
    spec.mkdir(parents=True, exist_ok=True)

    data = f"{ROOT / 'bloque' / 'assets'};bloque/assets"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", APP,
        "--icon", str(ROOT / "bloque" / "assets" / "icon.ico"),
        "--version-file", str(version_info(app_version)),
        "--add-data", data,
        "--paths", str(ROOT),
        "--distpath", str(staging),
        "--workpath", str(work),
        "--specpath", str(spec),
        str(ROOT / "run.py"),
    ]
    print(f"Construyendo ejecutable {arch}...")
    subprocess.run(command, cwd=ROOT, check=True)
    built = staging / APP
    executable = built / f"{APP}.exe"
    if not executable.is_file():
        raise SystemExit(f"No se genero {executable}")

    if staging != target:
        shutil.move(str(built), str(target))
        try:
            staging.rmdir()
        except OSError:
            pass
    return target / f"{APP}.exe"


def find_iscc() -> Path | None:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("ISCC")
    return Path(found) if found else None


def _is_32bit_python(path: Path) -> bool:
    try:
        result = subprocess.run(
            [str(path), "-c",
             "import sys; raise SystemExit(0 if sys.maxsize <= 2**32 else 1)"],
            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def find_python32() -> Path | None:
    override = (os.environ.get("BLOCKYS_PYTHON32") or "").strip()
    candidates: list[Path] = [Path(override)] if override else []
    if not IS_64:
        candidates.append(Path(sys.executable))
    python_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    if python_root.is_dir():
        candidates.extend(sorted(python_root.glob("Python*-32/python.exe"),
                                 reverse=True))
    for candidate in candidates:
        if candidate.is_file() and _is_32bit_python(candidate):
            return candidate
    return None


def build_installer(app_version: str) -> Path:
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit(
            "No se encontro Inno Setup 6. Instalalo con: winget install "
            "--id JRSoftware.InnoSetup --exact")
    for arch_dir in (DIST / APP, DIST / "Blockys32"):
        if not (arch_dir / f"{APP}.exe").is_file():
            raise SystemExit(
                f"Falta el build {arch_dir.name}. Construí las dos "
                "arquitecturas antes del instalador.")
    setup = DIST / f"Blockys-Setup-{app_version}.exe"
    if setup.exists():
        setup.unlink()
    print("Construyendo instalador combinado...")
    subprocess.run([
        str(iscc),
        f"/DMyAppVersion={app_version}",
        str(ROOT / "packaging" / "Blockys.iss"),
    ], cwd=ROOT, check=True)
    if not setup.is_file():
        raise SystemExit(f"No se genero {setup}")
    return setup


def main() -> None:
    app_version = version()
    args = set(sys.argv[1:])
    x86_only = bool({"--x86", "--32", "--x86-app"} & args)

    if "--installer-only" in args:
        setup = build_installer(app_version)
        print(f"Instalador: {setup} ({setup.stat().st_size / (1024 * 1024):.1f} MB)")
        return

    executable = build_app(app_version, "x86" if x86_only else "x64")
    print(f"Ejecutable {('32' if x86_only else '64')} bits: {executable}")
    if x86_only:
        return

    if "--installer" in args:
        python32 = find_python32()
        if python32 is None:
            raise SystemExit(
                "Falta Python de 32 bits. Instalá Python 3.15 x86 y volvé a "
                "intentarlo, o definí BLOCKYS_PYTHON32 con la ruta a python.exe.")
        print(f"Python 32 bits: {python32}")
        subprocess.run(
            [str(python32), str(ROOT / "build.py"), "--x86-app"],
            cwd=ROOT, check=True)
        setup = build_installer(app_version)
        print(f"Instalador: {setup} ({setup.stat().st_size / (1024 * 1024):.1f} MB)")
    else:
        print("Usa --installer para generar tambien el instalador.")


if __name__ == "__main__":
    main()
