"""Avisa por Discord cuando aparece Zelda Ocarina of Time (Switch 2) en MercadoLibre Chile.

Usa la API oficial de MercadoLibre (requiere app en developers.mercadolibre.cl).
Env: DISCORD_WEBHOOK, MELI_CLIENT_ID, MELI_CLIENT_SECRET
Opcional: PRODUCT_ID (default catálogo Zelda), QUERY, TEST=1 (mensaje de prueba),
          HEARTBEAT=1 (mensaje "sigo vivo" con el estado actual, sin ping).
Cualquier error = exit != 0, y el workflow avisa a Discord.
"""
import json, os, re, sys
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://api.mercadolibre.com"
ZELDA_ID = "MLC79199012"
PRODUCT_ID = os.getenv("PRODUCT_ID") or ZELDA_ID
QUERY = os.getenv("QUERY", "zelda ocarina of time switch 2")
PING_USER = "335205619944652808"
SEEN = Path("seen.json")
BAD = re.compile(r"amiibo|n64|nintendo 64|3ds|funda|carcasa|poster|polera|figura|llavero", re.I)


def session():
    # reintenta errores de red, 5xx y 429 (respeta Retry-After de MeLi y Discord)
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=None, respect_retry_after_header=True, raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def title_ok(title):
    t = title.lower()
    return bool("ocarina" in t and re.search(r"switch\s*2", t) and not BAD.search(t))


def token(s):
    r = s.post(f"{API}/oauth/token", timeout=20, data={
        "grant_type": "client_credentials",
        "client_id": os.environ["MELI_CLIENT_ID"],
        "client_secret": os.environ["MELI_CLIENT_SECRET"],
    })
    if r.status_code != 200:
        sys.exit(f"token: HTTP {r.status_code} {r.text[:200]} (¿credenciales MeLi revocadas o mal copiadas?)")
    return r.json()["access_token"]


def notify(s, text, ping=True):
    text = f"<@{PING_USER}> {text}" if ping else text
    r = s.post(os.environ["DISCORD_WEBHOOK"], timeout=20, json={
        "content": text[:2000],  # límite de Discord
        "allowed_mentions": {"users": [PING_USER] if ping else []},
    })
    if r.status_code not in (200, 204):
        sys.exit(f"discord: HTTP {r.status_code} {r.text[:200]} (¿webhook borrado?)")


def check_product(s, auth):
    """El ID de catálogo tiene que existir y ser el juego correcto; si no, avisamos al vacío para siempre."""
    r = s.get(f"{API}/products/{PRODUCT_ID}", headers=auth, timeout=20)
    if r.status_code != 200:
        sys.exit(f"product {PRODUCT_ID}: HTTP {r.status_code} {r.text[:200]}")
    name = r.json().get("name", "")
    print(f"product {PRODUCT_ID}: {name}")
    if PRODUCT_ID == ZELDA_ID and "ocarina" not in name.lower():
        sys.exit(f"product {PRODUCT_ID} ya no es Zelda Ocarina: '{name}'")
    return name


def catalog_items(s, auth, name):
    """Publicaciones activas del producto de catálogo (vacío = no disponible)."""
    r = s.get(f"{API}/products/{PRODUCT_ID}/items", headers=auth, timeout=20)
    print(f"catalog {PRODUCT_ID}: HTTP {r.status_code}")
    if r.status_code == 404:  # el producto existe (check_product), solo no tiene vendedores
        return []
    if r.status_code != 200:
        sys.exit(f"catalog: HTTP {r.status_code} {r.text[:200]}")
    results = r.json()["results"]  # KeyError = cambió el formato de la API → falla ruidosa
    return [(i["item_id"], name, i.get("price"),
             f"https://www.mercadolibre.cl/p/{PRODUCT_ID}?pdp_filters=item_id:{i['item_id']}")
            for i in results]


def search_items(s, auth):
    """Búsqueda por palabra clave. MeLi la restringe a algunas apps: 403 = se omite."""
    r = s.get(f"{API}/sites/MLC/search", params={"q": QUERY, "limit": 50}, headers=auth, timeout=20)
    if r.status_code == 403:
        print("search: 403, endpoint no habilitado para esta app, se omite")
        return []
    if r.status_code != 200:
        sys.exit(f"search: HTTP {r.status_code} {r.text[:200]}")
    return [(i["id"], i["title"], i.get("price"), i["permalink"])
            for i in r.json()["results"] if title_ok(i["title"])]


def fmt(item):
    _, title, price, url = item
    price_txt = f" — ${price:,.0f}".replace(",", ".") if isinstance(price, (int, float)) else ""
    return f"• {title}{price_txt}\n{url}"


def run(s):
    for k in ("DISCORD_WEBHOOK", "MELI_CLIENT_ID", "MELI_CLIENT_SECRET"):
        if not os.getenv(k):
            sys.exit(f"falta el secret {k}")
    if os.getenv("TEST") == "1":
        notify(s, "✅ zelda_scrap: webhook funcionando")
        return
    auth = {"Authorization": f"Bearer {token(s)}"}  # solo a MeLi, nunca a Discord
    name = check_product(s, auth)
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    found = {f[0]: f for f in catalog_items(s, auth, name) + search_items(s, auth)}  # dedupe por item_id
    new = [f for k, f in found.items() if k not in seen]
    print(f"encontrados={len(found)} nuevos={len(new)}")
    if os.getenv("HEARTBEAT") == "1":
        notify(s, f"💤 zelda_scrap sigue vigilando «{name}»: {len(found)} vendedores ahora.", ping=False)
    if new:
        # un solo mensaje: evita rate limit de Discord si aparecen muchos a la vez
        notify(s, f"🗡️ **¡Apareció!** ({len(new)} nuevas)\n" + "\n".join(fmt(f) for f in new[:10]))
        # se marca como visto solo después de avisar con éxito; si Discord falla, se reintenta en la próxima corrida
        SEEN.write_text(json.dumps(sorted(seen | {f[0] for f in new}), indent=1))


def selfcheck():
    assert title_ok("The Legend Of Zelda Ocarina Of Time Nintendo Switch 2 Físico")
    assert title_ok("Zelda Ocarina of Time SWITCH2 nuevo sellado")
    assert not title_ok("Zelda Ocarina of Time Nintendo 64 N64")
    assert not title_ok("Amiibo Link Ocarina Switch 2")
    assert not title_ok("Zelda Tears of the Kingdom Switch 2")
    assert fmt(("x", "T", 54990, "u")) == "• T — $54.990\nu"
    assert fmt(("x", "T", None, "u")) == "• T\nu"
    print("selfcheck ok")


if __name__ == "__main__":
    selfcheck() if "--selfcheck" in sys.argv else run(session())
