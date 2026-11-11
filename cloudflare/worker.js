// Forever AH Exchange — character sync helper (Cloudflare Worker)
//
// The dashboard calls:  https://<your-worker>.workers.dev/sync?name=Name-Surname
// This Worker asks Blizzard using your API key (kept as a Cloudflare secret, never
// sent to the browser) and returns the character's level, class, picture and professions.
//
// Secrets to add in Cloudflare (Settings → Variables and Secrets, type "Secret"):
//   BLIZZARD_CLIENT_ID, BLIZZARD_CLIENT_SECRET

const ALLOWED_ORIGINS = [
  "https://beartholomew.github.io",
  "http://localhost:5000",
  "http://127.0.0.1:5000",
];
const REGION = "us";
const NAMESPACE = `profile-forever-${REGION}`;
const API = `https://${REGION}.api.blizzard.com`;

let cachedToken = null;
let tokenExpires = 0;

async function getToken(env) {
  if (cachedToken && Date.now() < tokenExpires - 60_000) return cachedToken;
  const r = await fetch("https://oauth.battle.net/token", {
    method: "POST",
    headers: {
      Authorization: "Basic " + btoa(`${env.BLIZZARD_CLIENT_ID}:${env.BLIZZARD_CLIENT_SECRET}`),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: "grant_type=client_credentials",
  });
  if (!r.ok) throw new Error(`Blizzard login failed (${r.status}). Check the two secrets.`);
  const js = await r.json();
  cachedToken = js.access_token;
  tokenExpires = Date.now() + js.expires_in * 1000;
  return cachedToken;
}

async function blizzard(path, token) {
  const r = await fetch(`${API}${path}?namespace=${NAMESPACE}&locale=en_US`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) return { error: r.status };
  return r.json();
}

function cors(origin) {
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Content-Type": "application/json",
    "Cache-Control": "public, max-age=600",
    Vary: "Origin",
  };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const headers = cors(origin);
    if (request.method === "OPTIONS") return new Response(null, { headers });

    const url = new URL(request.url);
    if (url.pathname !== "/sync") {
      return new Response(JSON.stringify({ ok: true, usage: "/sync?name=Name-Surname" }), { headers });
    }
    const name = (url.searchParams.get("name") || "").trim();
    // Forever characters are Name-Surname; letters (incl. accented), spaces or hyphens only
    if (!/^[\p{L}][\p{L}' -]{1,40}$/u.test(name)) {
      return new Response(JSON.stringify({ error: "Enter your character as Name-Surname." }), { status: 400, headers });
    }
    const slug = encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));

    try {
      const token = await getToken(env);
      const base = `/profile/wow/character/${slug}`;
      const [summary, media, profs] = await Promise.all([
        blizzard(base, token),
        blizzard(`${base}/character-media`, token),
        blizzard(`${base}/professions`, token),
      ]);
      const notes = [];
      const out = { name };

      if (summary.error) {
        notes.push(summary.error === 404 ? "character not found (check spelling of Name-Surname)" : `character info unavailable (${summary.error})`);
      } else {
        out.summary = {
          level: summary.level,
          race: summary.race?.name,
          class: summary.character_class?.name,
          faction: summary.faction?.name,
        };
      }
      if (media.error) {
        notes.push(`picture unavailable (${media.error})`);
      } else {
        const assets = Object.fromEntries((media.assets || []).map(a => [a.key, a.value]));
        out.avatar = assets.avatar || assets.inset || null;
        out.render = assets["main-raw"] || assets.main || assets.inset || null;
      }
      out.professions = [];
      if (profs.error) {
        notes.push(`professions unavailable from Blizzard (${profs.error}); set skills by hand`);
      } else {
        for (const group of ["primaries", "secondaries"]) {
          for (const p of profs[group] || []) {
            const pname = p.profession?.name;
            let skill = p.skill_points;
            if (skill == null && Array.isArray(p.tiers)) skill = Math.max(0, ...p.tiers.map(t => t.skill_points || 0));
            if (pname) out.professions.push({ name: pname, skill: skill || 0 });
          }
        }
      }
      out.notes = notes;
      return new Response(JSON.stringify(out), { headers });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e.message || e) }), { status: 502, headers });
    }
  },
};
