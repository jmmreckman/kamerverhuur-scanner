"""Tado-client: inloggen (OAuth2 device-flow), uitlezen en sturen.

Gebaseerd op de officiële Tado REST-API (my.tado.com/api/v2). Sinds maart 2025
is wachtwoord-login weg; het gaat via de device-code-flow: eenmalig goedkeuren
in de browser, daarna werkt de client met een refresh-token dat roteert en in
een bestand bewaard wordt (op de VPS, nooit in git).

Alleen `urllib` uit de standaardbibliotheek (geen extra dependency). De pure
parsing (`verwerk_state`) staat los zodat 'ie testbaar is zonder netwerk.

Providerlaag: dit is de Tado-implementatie. Woningen met evohome (Honeywell)
krijgen later een eigen client met dezelfde vorm (get_homes/get_zones/
get_state/set_overlay/clear_overlay); de rest van de module (db, regels, UI)
is providernaam-bewust via de kolom `provider`. Zie docs/verwarming-tado-plan.md.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

PROVIDER = "tado"
CLIENT_ID = "1bb50063-6b0c-4d11-bd99-387f4a91cc46"  # publieke client-id van Tado zelf
AUTH = "https://login.tado.com/oauth2"
API = "https://my.tado.com/api/v2"
_TIMEOUT = 30


class TadoError(RuntimeError):
    """Fout bij een Tado-aanroep (netwerk, auth of API)."""


# --- pure parsing (los testbaar) --------------------------------------------

def verwerk_state(state: dict) -> dict:
    """Haalt uit een zone-state-antwoord de velden die wij bewaren/gebruiken.

    `online`: of de knop volgens Tado verbonden is (`link.state == "ONLINE"`).
    Bij een offline knop blijft de API wel de laatst bekende (bevroren) meting en
    de ingestelde temperatuur teruggeven - die moeten we dus apart herkennen,
    zodat we er niet op sturen en ze niet in de conclusies meetellen. None =
    onbekend (geen link-info in het antwoord)."""
    setting = state.get("setting") or {}
    temp = setting.get("temperature") or {}
    sensor = state.get("sensorDataPoints") or {}
    binnen = sensor.get("insideTemperature") or {}
    activity = state.get("activityDataPoints") or {}
    verwarmt = activity.get("heatingPower") or {}
    overlay = state.get("overlay")
    overlay_type = None
    if overlay:
        overlay_type = (overlay.get("termination") or {}).get("type") or "MANUAL"
    link_state = (state.get("link") or {}).get("state")
    online = None if link_state is None else (link_state == "ONLINE")
    return {
        "inside": binnen.get("celsius"),
        "setpoint": temp.get("celsius"),
        "power": setting.get("power"),
        "heating_pct": verwarmt.get("percentage"),
        "overlay_type": overlay_type,
        "online": online,
    }


# --- lage-niveau HTTP -------------------------------------------------------

def _post_form(url: str, params: dict):
    """POST met parameters in de query-string (zoals Tado's device/token-endpoints)."""
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}
    except urllib.error.URLError as e:
        raise TadoError(f"Netwerkfout richting Tado: {e}") from e


# --- token-opslag -----------------------------------------------------------

def _lees_token(pad: str):
    try:
        with open(pad) as f:
            return json.load(f).get("refresh_token")
    except (OSError, ValueError):
        return None


def _schrijf_token(pad: str, refresh_token: str) -> None:
    os.makedirs(os.path.dirname(pad) or ".", exist_ok=True)
    with open(pad, "w") as f:
        json.dump({"refresh_token": refresh_token}, f)
    try:
        os.chmod(pad, 0o600)
    except OSError:
        pass


# --- device-flow login (voor scripts/verwarming_login.py) -------------------

def start_device_login() -> dict:
    status, d = _post_form(AUTH + "/device_authorize",
                           {"client_id": CLIENT_ID, "scope": "offline_access"})
    if status != 200:
        raise TadoError(f"Kon geen device-code aanvragen (HTTP {status}): {d}")
    return d


def voltooi_device_login(token_file: str, device: dict, print_fn=print) -> None:
    """Pollt tot de gebruiker in de browser heeft goedgekeurd en bewaart het
    refresh-token. `device` is de uitkomst van start_device_login()."""
    interval = device.get("interval", 5)
    einde = time.time() + device.get("expires_in", 300)
    print_fn("Wachten op goedkeuring", end="", flush=True)
    while time.time() < einde:
        time.sleep(interval)
        print_fn(".", end="", flush=True)
        status, t = _post_form(AUTH + "/token", {
            "client_id": CLIENT_ID,
            "device_code": device["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        if status == 200:
            print_fn(" ingelogd!")
            _schrijf_token(token_file, t["refresh_token"])
            return
        if t.get("error") not in ("authorization_pending", "slow_down"):
            raise TadoError(f"Inloggen afgebroken: {t}")
    raise TadoError("Time-out: niet op tijd goedgekeurd.")


# --- client -----------------------------------------------------------------

class TadoClient:
    """Praat met de Tado-API namens één account (één refresh-token-bestand).

    Eén account kan meerdere homes dekken (get_homes). De client ververst het
    access-token lui en bewaart het geroteerde refresh-token telkens opnieuw.
    """

    def __init__(self, token_file: str):
        self.token_file = token_file
        self._access_token = None

    def is_ingelogd(self) -> bool:
        return _lees_token(self.token_file) is not None

    def _ververs(self) -> str:
        refresh = _lees_token(self.token_file)
        if not refresh:
            raise TadoError("Nog niet ingelogd bij Tado (geen token). "
                            "Draai eerst scripts/verwarming_login.py op de VPS.")
        status, t = _post_form(AUTH + "/token", {
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        })
        if status != 200:
            raise TadoError(f"Token verversen mislukt (HTTP {status}): {t}. "
                            "Mogelijk verlopen - opnieuw inloggen nodig.")
        _schrijf_token(self.token_file, t["refresh_token"])  # roteert
        self._access_token = t["access_token"]
        return self._access_token

    def _token(self) -> str:
        return self._access_token or self._ververs()

    def _api(self, method: str, path: str, body=None, _retry=True):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": "Bearer " + self._token()}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry:
                # access-token verlopen -> één keer verversen en opnieuw
                self._access_token = None
                return self._api(method, path, body, _retry=False)
            raise TadoError(f"Tado API {method} {path} -> HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise TadoError(f"Netwerkfout richting Tado: {e}") from e

    # -- lezen --
    def get_homes(self) -> list:
        me = self._api("GET", "/me") or {}
        return me.get("homes", [])

    def get_zones(self, home_id) -> list:
        return self._api("GET", f"/homes/{home_id}/zones") or []

    def get_state(self, home_id, zone_id) -> dict:
        return self._api("GET", f"/homes/{home_id}/zones/{zone_id}/state") or {}

    # -- sturen --
    def set_overlay(self, home_id, zone_id, celsius, duur_seconden=None, power="ON"):
        """Zet een handmatige overlay. duur_seconden=None -> MANUAL (blijft staan),
        anders TIMER die daarna terugvalt op het schema."""
        if power == "OFF":
            setting = {"type": "HEATING", "power": "OFF"}
        else:
            setting = {"type": "HEATING", "power": "ON", "temperature": {"celsius": celsius}}
        termination = ({"type": "TIMER", "durationInSeconds": int(duur_seconden)}
                       if duur_seconden else {"type": "MANUAL"})
        return self._api("PUT", f"/homes/{home_id}/zones/{zone_id}/overlay",
                         {"setting": setting, "termination": termination})

    def clear_overlay(self, home_id, zone_id):
        return self._api("DELETE", f"/homes/{home_id}/zones/{zone_id}/overlay")
