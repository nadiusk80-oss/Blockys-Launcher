from __future__ import annotations

import os
import shutil
import uuid as uuidlib
from pathlib import Path

from PIL import Image

from . import net, paths

VALID_SIZES = {(64, 64), (64, 32)}
UPLOAD_SKIN_URL = "https://api.minecraftservices.com/minecraft/profile/skins"


class SkinError(Exception):
    pass


def _safe_name(value) -> str:
    name = Path(str(value or "")).name
    return "" if name in ("", ".", "..") else name


def skin_path(profile: dict) -> Path | None:
    name = _safe_name(profile.get("skin"))
    if not name:
        return None
    path = paths.SKINS_DIR / name
    return path if path.is_file() else None


def validate_skin(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as img:
            if img.format != "PNG":
                raise SkinError("La skin debe ser un archivo PNG")
            size = img.size
            img.verify()
    except SkinError:
        raise
    except Exception as exc:
        raise SkinError("El archivo no es un PNG valido") from exc
    if size not in VALID_SIZES:
        raise SkinError("La skin debe medir 64x64 (moderna) o 64x32 (clasica)")
    return size


def import_skin(profile: dict, source: Path) -> Path:
    source = Path(source)
    validate_skin(source)
    paths.SKINS_DIR.mkdir(parents=True, exist_ok=True)
    ident = "".join(ch for ch in str(profile.get("uuid") or "")
                    if ch.isalnum() or ch in "-_")
    if not ident:
        ident = uuidlib.uuid4().hex
    dest = paths.SKINS_DIR / f"{ident}.png"
    profile["skin"] = dest.name
    try:
        if source.resolve() == dest.resolve():
            return dest
    except OSError:
        pass
    tmp = dest.with_name(dest.name + ".part")
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, dest)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise SkinError(f"No se pudo guardar la skin: {exc}") from exc
    return dest


def _base(img: Image.Image) -> Image.Image:
    return img.convert("RGBA").copy()


def render_head(path: Path, size: int = 96, background=None) -> Image.Image:
    with Image.open(path) as source:
        img = _base(source)
    canvas = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    canvas.alpha_composite(img.crop((8, 8, 16, 16)))
    if img.height >= 16:
        canvas.alpha_composite(img.crop((40, 8, 48, 16)))
    result = canvas.resize((size, size), Image.NEAREST)
    if background is not None:
        bg = Image.new("RGBA", result.size, background)
        bg.alpha_composite(result)
        return bg
    return result


def render_body(path: Path, scale: int = 6, background=None) -> Image.Image:
    with Image.open(path) as source:
        img = _base(source)
    _, height = img.size
    canvas = Image.new("RGBA", (16, 32), (0, 0, 0, 0))

    canvas.alpha_composite(img.crop((8, 8, 16, 16)), (4, 0))
    canvas.alpha_composite(img.crop((20, 20, 28, 32)), (4, 8))
    canvas.alpha_composite(img.crop((44, 20, 48, 32)), (0, 8))
    canvas.alpha_composite(img.crop((4, 20, 8, 32)), (4, 20))

    if height >= 64:
        canvas.alpha_composite(img.crop((36, 52, 40, 64)), (12, 8))
        canvas.alpha_composite(img.crop((20, 52, 24, 64)), (8, 20))
    else:
        right_arm = img.crop((44, 20, 48, 32)).transpose(Image.FLIP_LEFT_RIGHT)
        right_leg = img.crop((4, 20, 8, 32)).transpose(Image.FLIP_LEFT_RIGHT)
        canvas.alpha_composite(right_arm, (12, 8))
        canvas.alpha_composite(right_leg, (8, 20))

    canvas.alpha_composite(img.crop((40, 8, 48, 16)), (4, 0))

    overlays = [
        ((20, 36, 28, 48), (4, 8)),
        ((44, 36, 48, 48), (0, 8)),
        ((4, 36, 8, 48), (4, 20)),
    ]
    if height >= 64:
        overlays.extend([
            ((52, 52, 56, 64), (12, 8)),
            ((4, 52, 8, 64), (8, 20)),
        ])
    else:
        sleeve = img.crop((44, 36, 48, 48)).transpose(Image.FLIP_LEFT_RIGHT)
        pant = img.crop((4, 36, 8, 48)).transpose(Image.FLIP_LEFT_RIGHT)
        canvas.alpha_composite(sleeve, (12, 8))
        canvas.alpha_composite(pant, (8, 20))

    for box, dest in overlays:
        canvas.alpha_composite(img.crop(box), dest)

    result = canvas.resize((16 * scale, 32 * scale), Image.NEAREST)
    if background is not None:
        bg = Image.new("RGBA", result.size, background)
        bg.alpha_composite(result)
        return bg
    return result


def _multipart(variant: str, data: bytes) -> tuple[bytes, str]:
    boundary = "----Blockys" + uuidlib.uuid4().hex
    chunks = []
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(b'Content-Disposition: form-data; name="variant"\r\n\r\n')
    chunks.append(variant.encode() + b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(b'Content-Disposition: form-data; name="file"; filename="skin.png"\r\n')
    chunks.append(b"Content-Type: image/png\r\n\r\n")
    chunks.append(data)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def upload_skin(profile: dict, variant: str = "classic", timeout: int = 60) -> None:
    if profile.get("type") != "microsoft":
        raise SkinError("Solo las cuentas Microsoft pueden subir skins a Mojang")
    path = skin_path(profile)
    if not path:
        raise SkinError("Esta cuenta no tiene una skin importada")
    validate_skin(path)
    token = profile.get("access_token")
    if not token:
        raise SkinError("Inicia sesion con Microsoft para subir skins")
    body, boundary = _multipart("slim" if variant == "slim" else "classic", path.read_bytes())
    try:
        status, _ = net.request(
            UPLOAD_SKIN_URL, data=body, method="POST", timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
    except net.HttpError as exc:
        if exc.status == 401:
            raise SkinError("El token de Minecraft expiro. Inicia sesion de nuevo.") from exc
        if exc.status == 400:
            raise SkinError("Mojang rechazo la skin (formato o variante invalida)") from exc
        if exc.status == 429:
            raise SkinError("Demasiadas subidas seguidas. Espera un momento.") from exc
        raise SkinError(f"Mojang devolvio un error {exc.status}") from exc
    if status not in (200, 204):
        raise SkinError(f"Mojang devolvio un estado inesperado ({status})")


def copy_for_customskinloader(profile: dict, game_dir: Path) -> Path | None:
    source = skin_path(profile)
    if not source:
        return None
    folder = Path(game_dir) / "CustomSkinLoader" / "LocalSkin" / "skins"
    folder.mkdir(parents=True, exist_ok=True)
    for name in (profile.get("name"), profile.get("uuid")):
        safe = _safe_name(name)
        if safe:
            shutil.copyfile(source, folder / f"{safe}.png")
    return folder


def placeholder_head(size: int = 64, background=(34, 31, 25, 255)):
    canvas = Image.new("RGBA", (8, 8), background)
    canvas.paste((121, 110, 91, 255), (1, 1, 7, 7))
    for x in (2, 5):
        canvas.putpixel((x, 3), (40, 34, 26, 255))
    return canvas.resize((size, size), Image.NEAREST)


def placeholder_body(scale: int = 5, background=(34, 31, 25, 255)):
    canvas = Image.new("RGBA", (16, 32), background)
    color = (121, 110, 91, 255)
    for box in ((4, 0, 12, 8), (4, 8, 12, 20), (0, 8, 4, 20),
                (12, 8, 16, 20), (4, 20, 8, 32), (8, 20, 12, 32)):
        canvas.paste(color, box)
    for x in (6, 9):
        canvas.putpixel((x, 4), (40, 34, 26, 255))
    return canvas.resize((16 * scale, 32 * scale), Image.NEAREST)
