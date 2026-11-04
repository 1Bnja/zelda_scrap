"""Escenarios de falla de watch.run() con MeLi/Discord simulados. Correr: python test_watch.py"""
import json, os, tempfile
import watch


class R:
    def __init__(self, code, body=None):
        self.status_code, self._body, self.text = code, body, json.dumps(body)

    def json(self):
        return self._body


class Fake:
    """routes: substring de URL -> R. Registra los mensajes enviados a Discord."""
    def __init__(self, **routes):
        self.routes, self.sent = routes, []

    def _match(self, url):
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise AssertionError(f"url inesperada {url}")

    def get(self, url, **kw):
        assert "discord" not in url
        return self._match(url)

    def post(self, url, **kw):
        if "discord" in url:
            assert "headers" not in kw, "token de MeLi filtrado a Discord"
            self.sent.append(kw["json"])
        return self._match(url)


OK = dict(token=R(200, {"access_token": "t"}),
          discord=R(204),
          search=R(403, {}),
          items=R(404, {}),
          products=R(200, {"name": "The Legend Of Zelda Ocarina Of Time Switch 2"}))


def case(env=None, seen=None, **over):
    routes = {**OK, **over}
    # orden: /items antes que /products (ambas URLs contienen "products")
    fake = Fake(**{k: routes[k] for k in ("token", "discord", "search", "items", "products")})
    os.environ.update({"DISCORD_WEBHOOK": "https://discord/x", "MELI_CLIENT_ID": "i",
                       "MELI_CLIENT_SECRET": "s", "TEST": "0", "HEARTBEAT": "0", **(env or {})})
    if seen is None:
        watch.SEEN.unlink(missing_ok=True)
    else:
        watch.SEEN.write_text(json.dumps(seen))
    try:
        watch.run(fake)
        return fake, None
    except SystemExit as e:
        return fake, str(e)


def seen():
    return json.loads(watch.SEEN.read_text()) if watch.SEEN.exists() else []


def main():
    os.chdir(tempfile.mkdtemp())
    items = R(200, {"results": [{"item_id": "MLC1", "price": 49990}, {"item_id": "MLC2", "price": None}]})

    f, err = case()
    assert not err and not f.sent and seen() == [], "sin vendedores: silencio"

    f, err = case(items=items)
    assert not err and len(f.sent) == 1, "dos vendedores: UN mensaje"
    assert "<@335205619944652808>" in f.sent[0]["content"] and "$49.990" in f.sent[0]["content"]
    assert seen() == ["MLC1", "MLC2"]

    f, err = case(items=items, seen=["MLC1", "MLC2"])
    assert not err and not f.sent, "ya avisados: no repetir"

    f, err = case(items=items, discord=R(404, {"message": "Unknown Webhook"}))
    assert err and "discord" in err and seen() == [], "Discord falla: no marcar como visto"

    f, err = case(token=R(401, {"error": "invalid_client"}))
    assert err and "token" in err, "credenciales malas: falla ruidosa"

    f, err = case(products=R(404, {}))
    assert err and "product" in err, "ID de catálogo borrado: falla ruidosa"

    f, err = case(products=R(200, {"name": "Mario Kart World"}))
    assert err and "ya no es Zelda" in err, "ID reasignado a otro juego: falla ruidosa"

    f, err = case(items=R(403, {"code": "PA_UNAUTHORIZED"}))
    assert err and "catalog" in err, "catálogo bloqueado: falla ruidosa"

    try:
        case(items=R(200, {"unexpected": 1}))
        raise AssertionError("formato de API cambiado debe fallar")
    except KeyError:
        pass  # excepción no capturada = exit != 0 = alerta

    f, err = case(search=R(200, {"results": [
        {"id": "MLC9", "title": "Zelda Ocarina of Time Switch 2", "price": 1, "permalink": "p"},
        {"id": "MLC8", "title": "Amiibo Link Ocarina Switch 2", "price": 1, "permalink": "p"}]}))
    assert not err and len(f.sent) == 1 and seen() == ["MLC9"], "búsqueda habilitada: filtra"

    f, err = case(env={"HEARTBEAT": "1"})
    assert not err and len(f.sent) == 1 and "<@" not in f.sent[0]["content"], "heartbeat sin ping"

    f, err = case(env={"DISCORD_WEBHOOK": ""})
    assert err and "DISCORD_WEBHOOK" in err, "secret faltante"

    print("test_watch ok")


if __name__ == "__main__":
    main()
