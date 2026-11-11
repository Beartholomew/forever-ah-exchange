"""Dashboard server.   python web/app.py        then open http://localhost:5000
Uses data/ah.sqlite once the collector has run, otherwise data/sample.sqlite.
Add --host 0.0.0.0 to let friends on your network (or a server) reach it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ahtracker import db as dbmod, service  # noqa: E402
from ahtracker.blizzard import BlizzardClient, BlizzardError  # noqa: E402
from ahtracker.config import DATA_DIR, load_settings  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
app = Flask(__name__, static_folder=None)
settings = load_settings()


def db_path() -> tuple[Path, bool]:
    real = settings.db_path
    if real.exists():
        con = dbmod.connect(real)
        has = con.execute("SELECT 1 FROM item_hour LIMIT 1").fetchone()
        con.close()
        if has:
            return real, False
    return DATA_DIR / "sample.sqlite", True


def con():
    path, _ = db_path()
    return dbmod.connect(path)


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/static/<path:name>")
def static_files(name: str):
    return send_from_directory(STATIC, name)


@app.get("/api/meta")
def meta():
    path, sample = db_path()
    c = con()
    hs = service.houses(c)
    default = next((h["house_key"] for h in hs if settings.default_house.lower() in h["name"].lower()), hs[0]["house_key"] if hs else None)
    return jsonify({"sample": sample, "houses": hs, "default_house": default, "professions": service.PROFESSIONS})


@app.get("/api/overview")
def overview():
    c = con()
    hs = service.houses(c)
    house = request.args.get("house") or (hs[0]["house_key"] if hs else "")
    return jsonify(service.overview(c, settings, house, service.load_profiles()))


@app.get("/api/conversions")
def conversions():
    c = con()
    house = request.args.get("house") or service.houses(c)[0]["house_key"]
    return jsonify(service.conversions(c, settings, house))


@app.get("/api/item/<int:item_id>")
def item(item_id: int):
    c = con()
    house = request.args.get("house") or service.houses(c)[0]["house_key"]
    return jsonify(service.item_detail(c, settings, house, item_id, int(request.args.get("days", 30))))


@app.get("/api/profiles")
def get_profiles():
    return jsonify(service.load_profiles())


@app.post("/api/profiles")
def set_profiles():
    service.save_profiles(request.get_json(force=True))
    return jsonify(service.load_profiles())


@app.post("/api/sync/<char_id>")
def sync(char_id: str):
    """Pull professions from Blizzard for a character's Name-Surname. VERIFY response shape."""
    data = service.load_profiles()
    char = next((c for c in data["characters"] if c["id"] == char_id), None)
    if not char or not char.get("name_surname"):
        return jsonify({"error": "Add the character's Name-Surname first."}), 400
    client = BlizzardClient(settings)
    notes = []
    # picture and basic info first: these are separate endpoints and may work even if professions don't
    try:
        media = client.character_media(char["name_surname"])
        char["avatar"] = media.get("avatar") or media.get("inset")
        char["render"] = media.get("main-raw") or media.get("main") or media.get("inset")
    except BlizzardError as e:
        notes.append(f"picture unavailable (HTTP {e.status})")
    try:
        sm = client.character_summary(char["name_surname"])
        char["summary"] = {"level": sm.get("level"), "race": (sm.get("race") or {}).get("name"),
                           "class": (sm.get("character_class") or {}).get("name"),
                           "faction": (sm.get("faction") or {}).get("name")}
    except BlizzardError as e:
        notes.append(f"character info unavailable (HTTP {e.status})")
    try:
        js = client.character_professions(char["name_surname"])
    except BlizzardError as e:
        service.save_profiles(data)
        return jsonify({"synced": [], "notes": notes + [f"professions unavailable (HTTP {e.status}), set skills by hand"]})
    profs = []
    for group in ("primaries", "secondaries"):
        for p in js.get(group, []):
            name = (p.get("profession") or {}).get("name")
            skill = p.get("skill_points")
            if skill is None and p.get("tiers"):  # retail-style shape
                skill = max(t.get("skill_points", 0) for t in p["tiers"])
            if name:
                profs.append({"name": name, "skill": int(skill or 0)})
    if profs:
        char["professions"] = profs
    service.save_profiles(data)
    return jsonify({"synced": profs, "notes": notes})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    a = ap.parse_args()
    app.run(host=a.host, port=a.port)
