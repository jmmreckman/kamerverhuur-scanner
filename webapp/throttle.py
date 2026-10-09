"""Simpele in-memory inlog-throttle (brute-force-rem) per client-IP.

Bewust licht (geen externe store/Redis): het draait in één gunicorn-proces per
app en hoeft alleen geautomatiseerd wachtwoord-raden af te remmen, niet een
gedistribueerde aanval. Na te veel mislukte inlogpogingen binnen een tijdvenster
worden verdere pogingen van hetzelfde IP even geweigerd; een geslaagde login
wist de teller. Normale gebruikers merken hier niets van.

Los van webapp/app.py gehouden zodat deze logica in de sandbox testbaar is
zonder de zware webapp-imports (bunq_sdk e.d.) - zie CLAUDE.md §6.
"""
from __future__ import annotations

import threading
import time

STANDAARD_MAX_POGINGEN = 8          # toegestane mislukte pogingen per venster
STANDAARD_VENSTER_SECONDEN = 300    # venster (5 min) waarover geteld wordt


class LoginThrottle:
    def __init__(
        self,
        max_pogingen: int = STANDAARD_MAX_POGINGEN,
        venster_seconden: float = STANDAARD_VENSTER_SECONDEN,
    ) -> None:
        self.max_pogingen = max_pogingen
        self.venster_seconden = venster_seconden
        self._pogingen: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, ip: str, nu: float) -> list[float]:
        return [t for t in self._pogingen.get(ip, []) if nu - t < self.venster_seconden]

    def geblokkeerd(self, ip: str, nu: float | None = None) -> bool:
        nu = time.monotonic() if nu is None else nu
        with self._lock:
            pogingen = self._recent(ip, nu)
            if pogingen:
                self._pogingen[ip] = pogingen
            else:
                self._pogingen.pop(ip, None)
            return len(pogingen) >= self.max_pogingen

    def registreer_mislukt(self, ip: str, nu: float | None = None) -> None:
        nu = time.monotonic() if nu is None else nu
        with self._lock:
            pogingen = self._recent(ip, nu)
            pogingen.append(nu)
            self._pogingen[ip] = pogingen

    def wis(self, ip: str) -> None:
        """Na een geslaagde login: teller voor dit IP leegmaken."""
        with self._lock:
            self._pogingen.pop(ip, None)
