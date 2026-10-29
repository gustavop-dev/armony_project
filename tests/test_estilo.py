"""WhatsApp export reading and the tone request: only the user's own messages."""
import sys
import zipfile
from types import SimpleNamespace

import pytest

import estilo

ANDROID = (
    "29/10/26, 16:18 - Los mensajes y las llamadas están cifrados de extremo a extremo.\n"
    "29/10/26, 16:18 - Ana: hola! qué tal\n"
    "29/10/26, 16:19 - Gustavo: Bien, la verdad es que liado\n"
    "con el proyecto\n"
    "29/10/26, 16:20 - Gustavo: <Multimedia omitido>\n"
    "29/10/26, 16:21 - Ana se unió usando el enlace de invitación\n"
    "29/10/26, 16:22 - Gustavo: mira https://x.com/a y llámame al +34 600 123 456\n"
)
IPHONE = (
    "[29/10/26, 16:18:05] Ana: buenas\n"
    "‎[29/10/26, 16:18:30] Gustavo: ‎imagen omitida\n"
    "[29/10/26, 16:19:00] Gustavo: ok, lo vemos mañana\n"
)
DOCE_HORAS = "10/29/26, 4:18 PM - Gustavo: sounds good\n10/29/26, 4:19 p. m. - Ana: ok\n"


def test_android_export_is_split_by_author():
    assert estilo.parsear(ANDROID) == [
        ("Ana", "hola! qué tal"),
        ("Gustavo", "Bien, la verdad es que liado\ncon el proyecto"),
        ("Gustavo", "mira https://x.com/a y llámame al +34 600 123 456"),
    ]


def test_iphone_export_drops_attachments():
    assert estilo.parsear(IPHONE) == [("Ana", "buenas"), ("Gustavo", "ok, lo vemos mañana")]


def test_twelve_hour_clock_is_understood():
    assert [a for a, _ in estilo.parsear(DOCE_HORAS)] == ["Gustavo", "Ana"]


def test_authors_are_ranked_by_messages():
    assert estilo.autores(estilo.parsear(ANDROID)) == {"Gustavo": 2, "Ana": 1}


def test_links_mails_and_phones_are_removed():
    assert estilo.limpiar("ve a https://a.b/c o www.x.com, escribe a yo@mail.com "
                          "o al +34 600 123 456") == (
        "ve a [enlace] o [enlace] escribe a [correo] o al [teléfono]")


def test_sample_keeps_only_the_chosen_author():
    mensajes = [("Ana", "secreto de Ana"), ("Yo", "uno"), ("Ana", "otro"), ("Yo", "dos")]

    assert estilo.muestra(mensajes, "Yo") == ["uno", "dos"]


def test_sample_keeps_the_most_recent_that_fit():
    mensajes = [("Yo", f"mensaje {i:03d}") for i in range(100)]

    elegidos = estilo.muestra(mensajes, "Yo", max_caracteres=60)

    assert elegidos[-1] == "mensaje 099" and len(elegidos) == 5


def test_model_input_has_no_one_else():
    entrada = estilo.entrada_modelo(["la verdad es que sí", "ok"])

    texto = entrada[1]["content"][0]["text"]
    assert entrada[0]["role"] == "developer"
    assert texto == "Mis mensajes (2):\n- la verdad es que sí\n- ok"


def test_zip_export_is_read(tmp_path):
    ruta = tmp_path / "WhatsApp Chat - Ana.zip"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("_chat.txt", IPHONE)
        z.writestr("IMG-001.jpg", b"\xff\xd8")

    assert estilo.leer_export(str(ruta)) == IPHONE


def test_zip_without_chat_is_rejected(tmp_path):
    ruta = tmp_path / "otro.zip"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("foto.jpg", b"x")

    with pytest.raises(ValueError):
        estilo.leer_export(str(ruta))


def test_txt_export_with_bom_is_read(tmp_path):
    ruta = tmp_path / "chat.txt"
    ruta.write_bytes("﻿".encode("utf-8") + DOCE_HORAS.encode("utf-8"))

    assert estilo.leer_export(str(ruta)) == DOCE_HORAS


class FakeOpenAI:
    llamadas = []

    def __init__(self, **kw):
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        FakeOpenAI.llamadas.append(kw)
        return SimpleNamespace(output_text="## Registro\nCercano.")


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.llamadas = []
    modulo = SimpleNamespace(OpenAI=FakeOpenAI, Timeout=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "openai", modulo)
    return FakeOpenAI


def test_tone_is_asked_with_only_my_messages(fake_openai):
    texto = estilo.generar_tono("k", "gpt-6.1-sol", ["uno", "dos"])

    (llamada,) = fake_openai.llamadas
    assert texto == "## Registro\nCercano."
    assert (llamada["model"], llamada["reasoning"]) == ("gpt-6.1-sol", {"effort": "medium"})
    assert llamada["input"] == estilo.entrada_modelo(["uno", "dos"])


def test_empty_answer_is_an_error(fake_openai, monkeypatch):
    monkeypatch.setattr(FakeOpenAI, "_create", lambda self, **kw: SimpleNamespace(output_text=" "))

    with pytest.raises(RuntimeError):
        estilo.generar_tono("k", "m", ["uno"])
