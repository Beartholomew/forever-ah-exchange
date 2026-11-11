"""Settings, loaded from settings.env next to the project root (never commit that file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def _get(env: dict[str, str], key: str, default: str = "") -> str:
    return os.environ.get(key, env.get(key, default))


@dataclass
class Settings:
    client_id: str = ""
    client_secret: str = ""
    region: str = "us"
    locale: str = "en_US"
    # Forever namespaces (undocumented). Leave static blank to auto-discover.
    dynamic_namespace: str = "dynamic-forever-us"
    static_namespace: str = ""
    profile_namespace: str = "profile-forever-us"
    ruleset_name: str = "PvE"  # PvE, PvP, Hardcore or RP
    default_house: str = "Alliance"
    house_ids: list[int] = field(default_factory=list)  # which houses to collect (from find_house)
    db_path: Path = DATA_DIR / "ah.sqlite"
    # AH cut per house, keyed by lowercase words in the house name.
    # TODO(verify in game): original Classic took 5% at faction AHs and 15% at the neutral AH.
    ah_cut: dict[str, float] = field(default_factory=lambda: {"alliance": 0.05, "horde": 0.05, "blackwater": 0.15, "default": 0.05})
    # Deposit as a fraction of the item's vendor sell price, per listing duration.
    # TODO(verify in game): placeholder values.
    deposit_rate: float = 0.15
    # Filters for the Top 5 lists
    min_daily_sold: float = 5
    min_listings: int = 3
    min_price_copper: int = 500  # 5 silver

    def cut_for(self, house_name: str) -> float:
        name = (house_name or "").lower()
        for key, cut in self.ah_cut.items():
            if key != "default" and key in name:
                return cut
        return self.ah_cut["default"]


def load_settings() -> Settings:
    env = _load_env_file(ROOT / "settings.env")
    s = Settings()
    s.client_id = _get(env, "BLIZZARD_CLIENT_ID")
    s.client_secret = _get(env, "BLIZZARD_CLIENT_SECRET")
    s.region = _get(env, "REGION", "us").lower()
    s.locale = _get(env, "LOCALE", "en_US")
    s.dynamic_namespace = _get(env, "DYNAMIC_NAMESPACE", f"dynamic-forever-{s.region}")
    s.static_namespace = _get(env, "STATIC_NAMESPACE", "")
    s.profile_namespace = _get(env, "PROFILE_NAMESPACE", f"profile-forever-{s.region}")
    s.ruleset_name = _get(env, "RULESET_NAME", "PvE")
    s.default_house = _get(env, "DEFAULT_HOUSE", "Alliance")
    s.house_ids = [int(x) for x in _get(env, "HOUSE_IDS", "").replace(" ", "").split(",") if x]
    db = _get(env, "DB_PATH", "")
    if db:
        s.db_path = Path(db)
    for key in ("alliance", "horde", "blackwater", "default"):
        v = _get(env, f"AH_CUT_{key.upper()}", "")
        if v:
            s.ah_cut[key] = float(v)
    if _get(env, "DEPOSIT_RATE", ""):
        s.deposit_rate = float(_get(env, "DEPOSIT_RATE"))
    return s
