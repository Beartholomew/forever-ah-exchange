"""Battle.net API client for WoW: Forever.

The Forever API is undocumented. Paths below follow what community developers
reported after launch (Nov 2026):
  /data/wow/ruleset/index                              -> list of rulesets
  /data/wow/ruleset/{id}/auctions/        (trailing /)  -> auction house index
  /data/wow/ruleset/{id}/auctions/{houseId}            -> item auctions for a house
  /data/wow/ruleset/{id}/auctions/{houseId}/commodities -> commodity auctions for a house
Anything marked VERIFY needs checking against the live API (run probe.py).
"""
from __future__ import annotations

import re
import time
from typing import Any

import requests

from .config import Settings


class BlizzardError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url} {body[:200]}")
        self.status = status
        self.url = url


class BlizzardClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        if not settings.client_id or not settings.client_secret:
            raise SystemExit("Missing BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET in settings.env")
        self.s = settings
        self.http = session or requests.Session()
        self.base = f"https://{settings.region}.api.blizzard.com"
        self._token: str | None = None
        self._token_expires = 0.0
        self.last_modified: str | None = None

    # ---- auth ----
    def token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        r = self.http.post(
            "https://oauth.battle.net/token",
            data={"grant_type": "client_credentials"},
            auth=(self.s.client_id, self.s.client_secret),
            timeout=30,
        )
        if r.status_code != 200:
            raise BlizzardError(r.status_code, "oauth token", r.text)
        js = r.json()
        self._token = js["access_token"]
        self._token_expires = time.time() + int(js.get("expires_in", 3600))
        return self._token

    # ---- requests ----
    def get(self, path: str, namespace: str, retries: int = 4, **params: Any) -> dict:
        url = path if path.startswith("http") else self.base + path
        params = {"namespace": namespace, "locale": self.s.locale, **params}
        delay = 2.0
        for attempt in range(retries):
            r = self.http.get(url, params=params, headers={"Authorization": f"Bearer {self.token()}"}, timeout=120)
            if r.status_code == 200:
                self.last_modified = r.headers.get("Last-Modified")
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise BlizzardError(r.status_code, r.url, r.text)
        raise BlizzardError(0, url)

    def dyn(self, path: str, **params: Any) -> dict:
        return self.get(path, self.s.dynamic_namespace, **params)

    def static(self, path: str, **params: Any) -> dict:
        return self.get(path, self.static_namespace(), **params)

    # ---- namespace discovery ----
    _static_ns: str | None = None

    def static_namespace(self) -> str:
        """Forever's static namespace is versioned (e.g. static-1.60.1_70399-forever-us)
        and changes every patch. Use the setting if given, otherwise try known values."""
        if self.s.static_namespace:
            return self.s.static_namespace
        if self._static_ns:
            return self._static_ns
        found = None
        for ns in STATIC_CANDIDATES:
            ns = ns.format(region=self.s.region)
            try:
                self.get("/data/wow/item/2589", ns, retries=1)  # Linen Cloth
                found = ns
                break
            except BlizzardError:
                continue
        if not found:
            raise SystemExit(
                "Couldn't auto-detect the Forever static namespace. Run probe.py, then set "
                "STATIC_NAMESPACE in settings.env (looks like static-1.60.1_70399-forever-us)."
            )
        self._static_ns = found
        return found

    # ---- Forever auction endpoints ----
    def rulesets(self) -> list[dict]:
        """The index only gives ids, so fetch each ruleset for its name (PvE, PvP, ...)."""
        js = self.dyn("/data/wow/ruleset/index")
        out = []
        for r in js.get("rulesets", []):
            try:
                d = self.dyn(f"/data/wow/ruleset/{r['id']}")
                out.append({"id": r["id"], "name": d.get("name", str(r["id"]))})
            except BlizzardError:
                out.append({"id": r["id"], "name": str(r["id"])})
        return out

    def pick_ruleset(self) -> dict:
        rs = self.rulesets()
        if not rs:
            raise SystemExit("No rulesets returned. Run probe.py to see what the API says.")
        want = self.s.ruleset_name.strip().lower()
        if want:
            names = [(r, str(r.get("name", "")).lower()) for r in rs]
            # exact name first, then a name that contains it but isn't a hardcore variant
            for r, n in names:
                if n == want:
                    return r
            for r, n in names:
                if want in n and ("hardcore" not in n or "hardcore" in want):
                    return r
            raise SystemExit(f"No ruleset named like '{self.s.ruleset_name}'. Available: "
                             + ", ".join(str(r.get("name")) for r in rs) + ". Set RULESET_NAME in settings.env.")
        return rs[0]

    def houses(self, ruleset_id: int) -> list[dict]:
        js = self.dyn(f"/data/wow/ruleset/{ruleset_id}/auctions/")  # trailing slash matters
        return js.get("auctions", [])

    def house_auctions(self, ruleset_id: int, house_id: int) -> dict:
        return self.dyn(f"/data/wow/ruleset/{ruleset_id}/auctions/{house_id}")

    def house_commodities(self, ruleset_id: int, house_id: int) -> dict:
        return self.dyn(f"/data/wow/ruleset/{ruleset_id}/auctions/{house_id}/commodities")

    def item(self, item_id: int) -> dict:
        return self.static(f"/data/wow/item/{item_id}")

    def item_media(self, item_id: int) -> dict:
        return self.static(f"/data/wow/media/item/{item_id}")

    def character_professions(self, name_surname: str) -> dict:
        # VERIFY: Forever characters have a surname and no realm; US reportedly
        # resolves /profile/wow/character/{name-surname}/... with a client token.
        return self.get(f"/profile/wow/character/{_slug(name_surname)}/professions", self.s.profile_namespace)

    def character_media(self, name_surname: str) -> dict:
        """Character pictures (avatar, inset, full render). VERIFY on Forever."""
        js = self.get(f"/profile/wow/character/{_slug(name_surname)}/character-media", self.s.profile_namespace)
        return {a.get("key"): a.get("value") for a in js.get("assets", []) if a.get("key")}

    def character_summary(self, name_surname: str) -> dict:
        return self.get(f"/profile/wow/character/{_slug(name_surname)}", self.s.profile_namespace)


STATIC_CANDIDATES = [
    "static-1.60.1_70399-forever-{region}",   # reported by community developers at launch
    "static-1.60.1_69913-forever-{region}",
    "static-forever-{region}",
    "static-1.60.1-forever-{region}",
]

def _slug(name_surname: str) -> str:
    return name_surname.strip().lower().replace(" ", "-")


_NS_RE = re.compile(r"namespace=(static-[\w.\-]*forever[\w\-]*)")


def find_static_namespace(obj: Any) -> str | None:
    """Search any JSON response for an href that carries the static namespace."""
    text = str(obj)
    m = _NS_RE.search(text)
    return m.group(1) if m else None
