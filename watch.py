"""Avisa por Discord cuando aparece Zelda Ocarina of Time (Switch 2) en MercadoLibre Chile.

Usa la API oficial de MercadoLibre (requiere app en developers.mercadolibre.cl).
Env: DISCORD_WEBHOOK, MELI_CLIENT_ID, MELI_CLIENT_SECRET
Opcional: PRODUCT_ID (default catálogo Zelda), QUERY, TEST=1 (manda un mensaje de prueba).
"""
import json, os, re, sys
from pathlib import Path
import requests

API = "https://api.mercadolibre.com"
PRODUCT_ID = os.getenv("PRODUCT_ID", "MLC79199012")
QUERY = os.getenv("QUERY", "zelda ocarina of time switch 2")
SEEN = Path("seen.json")
BAD = re.compile(r"amiibo|n64|nintendo 64|3ds|funda|carcasa|poster|polera|figura|llavero", re.I)


def title_ok(title):
    t = title.lower()
    return "ocarina" in t and re.search(r"switch\s*2", t) and not BAD.search(t)


def token():
    r = requests.post(f"{API}/oauth/token", timeout=20, data={
        "grant_type": "client_credentials",
        "client_id": os.environ["MELI_CLIENT_ID"],
        "client_secret": os.environ["MELI_CLIENT_SECRET"],
    })
    r.raise_for_status()
    return r.json()["access_token"]


def notify(text):
    r = requests.post(os.environ["DISCORD_WEBHOOK"], json={"content": text}, timeout=20)
    r.raise_for_status()


def catalog_items(s):
    """Publicaciones activas del producto de catálogo (vacío = no disponible)."""
    r = s.get(f"{API}/products/{PRODUCT_ID}/items", timeout=20)
    print(f"catalog {PRODUCT_ID}: HTTP {r.status_code}")
    if r.status_code == 404:  # sin vendedores todavía
        return []
    r.raise_for_status()
    return [(i["item_id"], f"{PRODUCT_ID} (catálogo)", i.get("price"),
             f"https://www.mercadolibre.cl/p/{PRODUCT_ID}?pdp_filters=item_id:{i['item_id']}")
            for i in r.json().get("results", [])]


def search_items(s):
    """Búsqueda por palabra clave. MeLi restringe este endpoint a algunas apps: si da 403, se omite."""
    r = s.get(f"{API}/sites/MLC/search", params={"q": QUERY, "limit": 50}, timeout=20)
    if r.status_code == 403:
        print("search: 403, endpoint no habilitado para esta app, se omite")
        return []
    r.raise_for_status()
    return [(i["id"], i["title"], i.get("price"), i["permalink"])
            for i in r.json().get("results", []) if title_ok(i["title"])]


def main():
    if os.getenv("TEST") == "1":
        notify("✅ zelda_scrap: webhook funcionando")
        return
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token()}"
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    found = catalog_items(s) + search_items(s)
    new = [f for f in found if f[0] not in seen]
    for item_id, title, price, url in new:
        price_txt = f" — ${price:,.0f}".replace(",", ".") if price else ""
        notify(f"🗡️ **¡Apareció!** {title}{price_txt}\n{url}")
        seen.add(item_id)
    SEEN.write_text(json.dumps(sorted(seen), indent=1))
    print(f"encontrados={len(found)} nuevos={len(new)}")


def selfcheck():
    assert title_ok("The Legend Of Zelda Ocarina Of Time Nintendo Switch 2 Físico")
    assert title_ok("Zelda Ocarina of Time SWITCH2 nuevo sellado")
    assert not title_ok("Zelda Ocarina of Time Nintendo 64 N64")
    assert not title_ok("Amiibo Link Ocarina Switch 2")
    assert not title_ok("Zelda Tears of the Kingdom Switch 2")
    print("selfcheck ok")


if __name__ == "__main__":
    selfcheck() if "--selfcheck" in sys.argv else main()
