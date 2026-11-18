from __future__ import annotations

import hashlib
import json
import re
import time
import uuid as uuidlib
from pathlib import Path
from urllib.parse import urlencode

from . import net, paths

DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
SCOPE = "XboxLive.signin offline_access"
XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"

FORM = {"Content-Type": "application/x-www-form-urlencoded"}
JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

XERR_MESSAGES = {
    "2148916233": "Esa cuenta de Microsoft no tiene un perfil de Xbox. Crea uno en xbox.com.",
    "2148916235": "Xbox Live no esta disponible en tu pais o region.",
    "2148916236": "Esta cuenta necesita verificacion de edad en Xbox.",
    "2148916237": "Esta cuenta necesita verificacion de edad en Xbox.",
    "2148916238": "Esta cuenta es de un menor y debe unirse a una familia de Microsoft.",
}


class AuthError(Exception):
    pass


def offline_uuid(name: str) -> str:
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuidlib.UUID(bytes=bytes(digest)))


def _sleep(seconds: float, cancel_event=None) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise AuthError("Inicio de sesion cancelado")
        time.sleep(0.25)


def _auth_error(exc: net.HttpError, prefix: str) -> AuthError:
    data = exc.json()
    description = data.get("error_description") or data.get("error") or exc.text
    return AuthError(f"{prefix}: {str(description)[:300]}")


class MicrosoftAuth:
    def __init__(self, client_id: str):
        client_id = (client_id or "").strip()
        if not client_id:
            raise AuthError(
                "Falta el Client ID de Microsoft. Configuralo en Ajustes para "
                "iniciar sesion con una cuenta premium."
            )
        self.client_id = client_id

    def start_device_code(self) -> dict:
        body = urlencode({"client_id": self.client_id, "scope": SCOPE}).encode()
        try:
            flow = net.http_json(DEVICE_CODE_URL, data=body, headers=FORM, method="POST")
        except net.HttpError as exc:
            if exc.status == 400:
                raise AuthError(
                    "Microsoft rechazo el Client ID. Revisa que sea una app "
                    "con 'Flujos de cliente publico' habilitados."
                ) from exc
            raise _auth_error(exc, "Microsoft") from exc
        if not flow.get("device_code") or not flow.get("user_code"):
            raise AuthError("Microsoft no devolvio un codigo de dispositivo")
        return flow

    def poll_device_code(self, flow: dict, cancel_event=None, on_status=None) -> dict:
        interval = max(1, int(flow.get("interval") or 5))
        deadline = time.time() + int(flow.get("expires_in") or 900)
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise AuthError("Inicio de sesion cancelado")
            if on_status:
                on_status("Esperando autorizacion en el navegador...")
            body = urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.client_id,
                "device_code": flow["device_code"],
            }).encode()
            try:
                return net.http_json(TOKEN_URL, data=body, headers=FORM, method="POST")
            except net.HttpError as exc:
                error = exc.json().get("error", "")
                if error == "authorization_pending":
                    _sleep(interval, cancel_event)
                    continue
                if error == "slow_down":
                    interval += 5
                    _sleep(interval, cancel_event)
                    continue
                if error in ("expired_token", "code_expired"):
                    raise AuthError("El codigo expiro. Intenta iniciar sesion de nuevo.")
                if error == "authorization_declined":
                    raise AuthError("Inicio de sesion rechazado en el navegador.")
                raise _auth_error(exc, "Microsoft") from exc
            _sleep(interval, cancel_event)
        raise AuthError("El codigo expiro. Intenta iniciar sesion de nuevo.")

    def login_with_ms_token(self, ms_access_token: str) -> dict:
        try:
            xbl = net.http_json(
                XBL_URL,
                data=json.dumps({
                    "Properties": {
                        "AuthMethod": "RPS",
                        "SiteName": "user.auth.xboxlive.com",
                        "RpsTicket": f"d={ms_access_token}",
                    },
                    "RelyingParty": "http://auth.xboxlive.com",
                    "TokenType": "JWT",
                }).encode(),
                headers=JSON_HEADERS, method="POST",
            )
        except net.HttpError as exc:
            raise _auth_error(exc, "Xbox Live") from exc

        xbl_token = xbl.get("Token")
        if not xbl_token:
            raise AuthError("Xbox Live no devolvio un token")

        try:
            xsts = net.http_json(
                XSTS_URL,
                data=json.dumps({
                    "Properties": {
                        "SandboxId": "RETAIL",
                        "UserTokens": [xbl_token],
                    },
                    "RelyingParty": "rp://api.minecraftservices.com/",
                    "TokenType": "JWT",
                }).encode(),
                headers={**JSON_HEADERS, "x-xbl-contract-version": "1"},
                method="POST",
            )
        except net.HttpError as exc:
            data = exc.json()
            xerr = str(data.get("XErr") or "")
            if xerr in XERR_MESSAGES:
                raise AuthError(XERR_MESSAGES[xerr]) from exc
            raise _auth_error(exc, "Xbox Live") from exc

        try:
            claim = xsts["DisplayClaims"]["xui"][0]
            uhs = claim["uhs"]
            xuid = claim.get("xid", "")
            xsts_token = xsts["Token"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AuthError("Respuesta inesperada de Xbox Live") from exc

        try:
            mc = net.http_json(
                MC_LOGIN_URL,
                data=json.dumps({"identityToken": f"XBL3.0 x={uhs};{xsts_token}"}).encode(),
                headers=JSON_HEADERS, method="POST",
            )
        except net.HttpError as exc:
            raise _auth_error(exc, "Minecraft") from exc

        mc_token = mc.get("access_token")
        if not mc_token:
            raise AuthError("Minecraft no devolvio un token de acceso")

        try:
            profile = net.http_json(MC_PROFILE_URL, headers={
                "Authorization": f"Bearer {mc_token}",
                "Accept": "application/json",
            })
        except net.HttpError as exc:
            if exc.status == 404:
                raise AuthError(
                    "Esta cuenta no tiene Minecraft: Java Edition. "
                    "Compra el juego o usa una cuenta offline."
                ) from exc
            if exc.status == 401:
                raise AuthError("Minecraft rechazo el token. Intenta de nuevo.") from exc
            raise _auth_error(exc, "Minecraft") from exc

        if not profile.get("id") or not profile.get("name"):
            raise AuthError("Minecraft no devolvio un perfil valido")

        return {
            "uuid": profile["id"],
            "name": profile["name"],
            "access_token": mc_token,
            "expires_at": time.time() + int(mc.get("expires_in") or 86400) - 120,
            "xuid": xuid,
        }

    def refresh(self, refresh_token: str) -> dict:
        body = urlencode({
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
            "scope": SCOPE,
        }).encode()
        try:
            tokens = net.http_json(TOKEN_URL, data=body, headers=FORM, method="POST")
        except net.HttpError as exc:
            raise AuthError(
                "La sesion de Microsoft expiro. Vuelve a iniciar sesion."
            ) from exc
        except (net.ConnectionError_, OSError) as exc:
            raise AuthError(
                "No hay conexion con Microsoft. Revisa tu internet e intenta de nuevo."
            ) from exc
        result = self.login_with_ms_token(tokens.get("access_token", ""))
        result["refresh_token"] = tokens.get("refresh_token", refresh_token)
        return result


def microsoft_login(client_id: str, cancel_event=None, on_status=None, on_code=None) -> dict:
    auth = MicrosoftAuth(client_id)
    flow = auth.start_device_code()
    if on_code:
        on_code(flow)
    tokens = auth.poll_device_code(flow, cancel_event=cancel_event, on_status=on_status)
    result = auth.login_with_ms_token(tokens.get("access_token", ""))
    result["refresh_token"] = tokens.get("refresh_token", "")
    return result


def ensure_access_token(profile: dict, client_id: str) -> dict:
    if profile.get("type") != "microsoft":
        return profile
    if profile.get("access_token") and time.time() < float(profile.get("expires_at") or 0):
        return profile
    refresh_token = profile.get("refresh_token")
    if not refresh_token:
        raise AuthError("Vuelve a iniciar sesion con Microsoft")
    result = MicrosoftAuth(client_id).refresh(refresh_token)
    profile.update(result)
    return profile


VALID_NAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")


class ProfileStore:
    def __init__(self):
        self.data = paths.load_store()
        self.data.setdefault("profiles", [])
        self.data.setdefault("selected", "")
        if not self.data["profiles"]:
            self.add_offline("Jugador")

    @property
    def profiles(self) -> list[dict]:
        return self.data["profiles"]

    def by_id(self, profile_id: str) -> dict | None:
        return next((p for p in self.profiles if p.get("uuid") == profile_id), None)

    def selected(self) -> dict | None:
        profile = self.by_id(self.data.get("selected", ""))
        if profile is None and self.profiles:
            profile = self.profiles[0]
            self.data["selected"] = profile["uuid"]
        return profile

    def select(self, profile_id: str) -> None:
        if self.by_id(profile_id):
            self.data["selected"] = profile_id
            self.save()

    def add_offline(self, name: str) -> dict:
        name = name.strip()
        if not VALID_NAME.match(name):
            raise ValueError("El nombre debe tener 3-16 caracteres: letras, numeros o _")
        if any(p.get("name", "").lower() == name.lower() for p in self.profiles):
            raise ValueError("Ya existe una cuenta con ese nombre")
        profile = {
            "uuid": offline_uuid(name),
            "type": "offline",
            "name": name,
            "skin": "",
            "skin_variant": "classic",
        }
        self.profiles.append(profile)
        self.data["selected"] = profile["uuid"]
        self.save()
        return profile

    def upsert_microsoft(self, auth_data: dict) -> dict:
        uuid = auth_data["uuid"]
        profile = self.by_id(uuid)
        if profile is None:
            profile = {
                "uuid": uuid,
                "skin": "",
                "skin_variant": "classic",
            }
            self.profiles.append(profile)
        profile.update({
            "type": "microsoft",
            "name": auth_data["name"],
            "access_token": auth_data.get("access_token", ""),
            "refresh_token": auth_data.get("refresh_token", profile.get("refresh_token", "")),
            "expires_at": auth_data.get("expires_at", 0),
            "xuid": auth_data.get("xuid", profile.get("xuid", "")),
        })
        self.data["selected"] = uuid
        self.save()
        return profile

    def remove(self, profile_id: str) -> None:
        profile = self.by_id(profile_id)
        if not profile:
            return
        self.profiles.remove(profile)
        skin_file = Path(str(profile.get("skin") or "")).name
        if skin_file and skin_file not in (".", ".."):
            try:
                (paths.SKINS_DIR / skin_file).unlink()
            except OSError:
                pass
        if self.data.get("selected") == profile_id:
            self.data["selected"] = self.profiles[0]["uuid"] if self.profiles else ""
        self.save()

    def save(self) -> None:
        paths.save_store(self.data)
