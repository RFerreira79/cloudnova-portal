import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from main import app  # noqa: E402


def test_pagina_inicial():
    resposta = app.test_client().get("/")
    assert resposta.status_code == 200
    assert b"CloudNova" in resposta.data


def test_health():
    resposta = app.test_client().get("/health")
    assert resposta.get_json() == {"status": "ok"}


def test_paginas_protegidas_exigem_login():
    cliente = app.test_client()
    for rota in ["/db", "/upload", "/egress"]:
        resposta = cliente.get(rota)
        assert resposta.status_code == 302
        assert "/login" in resposta.headers["Location"]
