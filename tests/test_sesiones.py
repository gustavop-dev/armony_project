"""Meeting history: saved with its agent and a chat-like title."""
import datetime as dt

import sesiones

AHORA = dt.datetime(2026, 10, 29, 16, 18, 5)


def test_meeting_is_saved_with_its_agent_and_title(isolated_data_dir):
    sesiones.guardar([("Ellos", "¿Qué harías con pagos duplicados?"), ("Sugerido", "Idempotencia")],
                     "grok", "Grok", AHORA)

    (s,) = sesiones.listar()
    assert (s["id"], s["agent"], s["agent_name"], s["title"], s["started"]) == (
        "sesion-20261029-161805", "grok", "Grok", "¿Qué harías con pagos duplicados?", AHORA)


def test_title_is_the_first_question_trimmed_at_a_word():
    largo = "¿Cómo diseñarías un sistema de pagos que aguante picos de tráfico en Black Friday?"

    titulo = sesiones._titulo([("Yo", "hola"), ("Ellos", largo)])

    assert titulo.endswith("…") and len(titulo) <= 49 and largo.startswith(titulo[:-1])


def test_meeting_without_questions_gets_a_plain_title():
    assert sesiones._titulo([("Yo", "hola")]) == "Reunión"


def test_empty_meeting_is_not_saved(isolated_data_dir):
    assert sesiones.guardar([], "coach", "Coach") is None
    assert sesiones.listar() == []


def test_newest_meeting_comes_first(isolated_data_dir):
    sesiones.guardar([("Ellos", "uno")], "coach", "Coach", AHORA)
    sesiones.guardar([("Ellos", "dos")], "coach", "Coach", AHORA + dt.timedelta(hours=1))

    assert [s["title"] for s in sesiones.listar()] == ["dos", "uno"]


def test_reading_returns_the_transcript_without_header(isolated_data_dir):
    sesiones.guardar([("Ellos", "Pregunta")], "coach", "Coach", AHORA)

    texto = sesiones.leer("sesion-20261029-161805")

    assert texto == "# Reunion del 29/10/2026 16:18\n\n**Ellos:** Pregunta"


def test_old_meetings_without_header_are_listed_without_agent(isolated_data_dir):
    carpeta = isolated_data_dir / "sesiones"
    carpeta.mkdir()
    (carpeta / "sesion-20261020-090000.md").write_text("# Reunion vieja\n", encoding="utf-8")

    (s,) = sesiones.listar()

    assert (s["agent"], s["title"], s["started"]) == ("", "Reunión", dt.datetime(2026, 10, 20, 9, 0))


def test_meeting_can_be_deleted(isolated_data_dir):
    sesiones.guardar([("Ellos", "x")], "coach", "Coach", AHORA)

    assert sesiones.borrar("sesion-20261029-161805") is True
    assert sesiones.listar() == []


def test_date_label_reads_like_a_chat_history():
    hoy = dt.datetime(2026, 10, 29, 20, 0)

    assert [sesiones.etiqueta_fecha(d, hoy) for d in (
        dt.datetime(2026, 10, 29, 16, 18), dt.datetime(2026, 10, 28, 11, 2),
        dt.datetime(2026, 10, 3, 9, 30))] == ["Hoy 16:18", "Ayer 11:02", "3 oct 09:30"]


def test_notes_live_next_to_the_meeting(isolated_data_dir):
    ruta = sesiones.guardar([("Ellos", "x")], "coach", "Coach", AHORA)
    sid = sesiones.id_de(ruta)

    sesiones.guardar_notas(sid, "## Resumen\nAlgo\n")

    assert sesiones.leer_notas(sid) == "## Resumen\nAlgo"
    assert [s["id"] for s in sesiones.listar()] == [sid]          # notes are not a meeting


def test_meeting_without_notes_reads_empty(isolated_data_dir):
    ruta = sesiones.guardar([("Ellos", "x")], "coach", "Coach", AHORA)

    assert sesiones.leer_notas(sesiones.id_de(ruta)) == ""


def test_deleting_a_meeting_deletes_its_notes(isolated_data_dir):
    sid = sesiones.id_de(sesiones.guardar([("Ellos", "x")], "coach", "Coach", AHORA))
    sesiones.guardar_notas(sid, "notas")

    sesiones.borrar(sid)

    assert list((isolated_data_dir / "sesiones").iterdir()) == []
