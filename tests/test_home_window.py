"""Home: agents with their meeting history, agent design, knowledge and settings."""
import datetime as dt

import pytest
from PySide6 import QtCore, QtWidgets

import agents
import avatares
import config
import home_window as hw
import sesiones

LEFT = QtCore.Qt.LeftButton


@pytest.fixture(autouse=True)
def chevron_in_tmp(isolated_data_dir, monkeypatch):
    import icons
    save_png = icons.save_png
    monkeypatch.setattr(icons, "save_png", lambda name, color, size, path, *a, **k:
                        save_png(name, color, size, str(isolated_data_dir / "chevron.png")))


@pytest.fixture
def make_home(qtbot):
    def _make(**overrides):
        cfg = config.load_config()
        cfg.update(overrides)
        win = hw.HomeWindow(cfg)
        qtbot.addWidget(win)
        return win
    return _make


def _page(win):
    return win.content.widget()


def _find(win, cls, name):
    return _page(win).findChild(cls, name)


def _agent_rows(win):
    return [w for w in win.lista.widget().findChildren(hw.NavItem, "agente")]


def _row(win, key):
    return next(f for f in _page(win).findChildren(QtWidgets.QWidget, "fila")
                if f.property("clave") == key)


def _save_session(agent, nombre, pregunta, cuando):
    sesiones.guardar([("Ellos", pregunta), ("Sugerido", "respuesta")], agent, nombre, cuando)


# ------------------------------------------------------------------ landing
def test_home_opens_on_the_agent_in_use(make_home):
    win = make_home(agent="grok")

    assert win.vista == ("agente", "grok")
    assert _find(win, QtWidgets.QLabel, "nombre-portada").text() == "Grok"


def test_agent_page_only_offers_start_or_edit(make_home):
    win = make_home(agent="grok")

    botones = {b.objectName() for b in _page(win).findChildren(QtWidgets.QPushButton)
               if b.objectName()}

    assert botones == {"iniciar", "editar"}
    assert _page(win).findChildren(QtWidgets.QPlainTextEdit) == []


def test_edit_button_opens_the_configuration(make_home, qtbot):
    win = make_home(agent="grok")

    qtbot.mouseClick(_find(win, QtWidgets.QPushButton, "editar"), LEFT)

    assert win.vista == ("editar", "grok")
    assert _find(win, QtWidgets.QLineEdit, "nombre-agente").text() == "Grok"


def test_back_button_returns_to_the_agent_page(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok")

    qtbot.mouseClick(_find(win, QtWidgets.QPushButton, "volver"), LEFT)

    assert win.vista == ("agente", "grok")


def test_sidebar_lists_every_agent(make_home):
    win = make_home()

    assert [r._lab.text() for r in _agent_rows(win)] == [
        "Coach", "Directo", "Grok", "Senior técnico"]


def test_open_agent_is_marked_in_the_sidebar(make_home):
    win = make_home(agent="directo")

    assert [r._activo for r in _agent_rows(win)] == [False, True, False, False]


def test_meetings_are_folded_until_the_arrow_is_pressed(make_home):
    _save_session("grok", "Grok", "¿Pagos duplicados?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()

    assert win.lista.widget().findChildren(hw.SessionItem) == []
    win._filas_agente["grok"].desplegar.emit()

    assert len(win.lista.widget().findChildren(hw.SessionItem)) == 1


def test_meetings_are_listed_under_their_agent(make_home):
    _save_session("grok", "Grok", "¿Pagos duplicados?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()
    win._desplegar("grok")

    filas = [w for w in win.lista.widget().children()
             if isinstance(w, (hw.NavItem, hw.SessionItem))]
    orden = [w._lab.text() if isinstance(w, hw.NavItem) else w.toolTip() or w._titulo.toolTip()
             for w in filas]
    assert orden.index("¿Pagos duplicados?") == orden.index("Grok") + 1


# ------------------------------------------------------------------ agent design
@pytest.mark.parametrize("pestana, campo", [("instrucciones", "instrucciones"),
                                            ("reglas", "reglas")])
def test_tabs_show_the_full_agent_text(make_home, pestana, campo):
    win = make_home(agent="grok")

    win.editar_agente("grok", pestana)

    assert _find(win, QtWidgets.QPlainTextEdit, campo).toPlainText() == agents.preset("grok")[campo]


def test_edits_are_saved_automatically(make_home):
    win = make_home(agent="grok")
    win.editar_agente("grok", "instrucciones")
    _find(win, QtWidgets.QPlainTextEdit, "instrucciones").setPlainText("Sarcástico y breve.")

    assert win.saved_lbl.text() == "Guardando…"
    win.guardar_ya()

    assert agents.get("grok")["instrucciones"] == "Sarcástico y breve."
    assert win.saved_lbl.text() == "Todo guardado"


def test_autosave_fires_on_its_own(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok")
    win._guardado.setInterval(10)

    _find(win, QtWidgets.QLineEdit, "nombre-agente").setText("Grok 2")

    qtbot.waitUntil(lambda: agents.get("grok")["name"] == "Grok 2", timeout=1000)


def test_renaming_updates_the_sidebar_live(make_home):
    win = make_home(agent="grok")
    win.editar_agente("grok")

    _find(win, QtWidgets.QLineEdit, "nombre-agente").setText("Grok 2")

    assert _agent_rows(win)[2]._lab.text() == "Grok 2"


def test_new_agent_starts_as_a_copy_of_the_coach(make_home, qtbot):
    win = make_home()

    win._ag_add()

    assert win.vista == ("editar", "agente-1")
    assert _find(win, QtWidgets.QPlainTextEdit, "instrucciones").toPlainText() == (
        agents.preset("coach")["instrucciones"])


def test_restore_brings_back_the_preset_text(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok", "reglas")
    _find(win, QtWidgets.QPlainTextEdit, "reglas").setPlainText("sin reglas")
    win._mostrar()

    qtbot.mouseClick(_find(win, QtWidgets.QPushButton, "restaurar-reglas"), LEFT)

    assert _find(win, QtWidgets.QPlainTextEdit, "reglas").toPlainText() == agents.preset("grok")["reglas"]


def test_deleting_needs_a_second_click(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok")
    borrar = _find(win, hw.ConfirmDelete, "borrar-agente")

    qtbot.mouseClick(borrar.papelera, LEFT)
    assert win._ag_get("grok") is not None
    qtbot.mouseClick(borrar.confirmar, LEFT)

    assert win._ag_get("grok") is None
    win.guardar_ya()
    assert "grok" not in [a["id"] for a in agents.list_agents()]


def test_unconfirmed_delete_goes_back(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok")
    borrar = _find(win, hw.ConfirmDelete, "borrar-agente")
    borrar._vuelta.setInterval(10)

    qtbot.mouseClick(borrar.papelera, LEFT)

    qtbot.waitUntil(lambda: borrar.papelera.isVisibleTo(borrar), timeout=1000)
    assert win._ag_get("grok") is not None


def test_last_agent_cannot_be_deleted(make_home):
    agents.write_all([agents.preset("coach")])
    win = make_home()

    win._ag_del("coach")

    assert [a["id"] for a in win.agents] == ["coach"]


# ------------------------------------------------------------------ knowledge
def test_knowledge_documents_are_saved_with_the_agent(make_home):
    win = make_home(agent="senior")
    win.editar_agente("senior", "conocimiento")

    win._doc_add("senior")
    _find(win, QtWidgets.QLineEdit, "nombre-documento").setText("Mi CV")
    _find(win, QtWidgets.QPlainTextEdit, "cuerpo-documento").setPlainText("Backend 6 años")
    win.guardar_ya()

    assert agents.get("senior")["conocimiento"] == [
        {"id": "doc-1", "name": "Mi CV", "body": "Backend 6 años"}]


def test_knowledge_tab_counts_documents(make_home):
    lista = agents.list_agents()
    lista[0]["conocimiento"] = [{"id": "doc-1", "name": "CV", "body": "x"}]
    agents.write_all(lista)
    win = make_home()
    win.editar_agente("coach")

    tabs = _find(win, hw.Segmented, "pestanas")

    assert tabs._btns["conocimiento"].text() == "Conocimiento · 1"


def test_old_active_contexts_move_into_the_agent_in_use(isolated_data_dir):
    carpeta = isolated_data_dir / "contexts"
    carpeta.mkdir()
    (carpeta / "ctx-1.md").write_text("---\nname: CV\nactive: true\n---\nBackend", encoding="utf-8")
    (carpeta / "ctx-2.md").write_text("---\nname: Viejo\nactive: false\n---\nNo", encoding="utf-8")

    assert agents.migrar_contextos("grok") == 1
    assert agents.migrar_contextos("grok") == 0          # only once
    assert agents.get("grok")["conocimiento"] == [{"id": "doc-1", "name": "CV", "body": "Backend"}]


# ------------------------------------------------------------------ meetings
def test_opening_a_meeting_shows_its_transcript(make_home):
    _save_session("grok", "Grok", "¿Pagos duplicados?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()

    win.abrir_sesion("sesion-20261029-161800")

    texto = _find(win, QtWidgets.QTextBrowser, "transcripcion").toPlainText()
    assert "¿Pagos duplicados?" in texto and "respuesta" in texto


def test_meeting_view_starts_with_its_agent(make_home):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home(agent="coach")

    win.abrir_sesion("sesion-20261029-161800")

    assert win.agente_actual() == "grok"


def test_deleting_a_meeting_removes_it(make_home, qtbot):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()
    win.abrir_sesion("sesion-20261029-161800")
    borrar = _find(win, hw.ConfirmDelete, "borrar-sesion")

    qtbot.mouseClick(borrar.papelera, LEFT)
    qtbot.mouseClick(borrar.confirmar, LEFT)

    assert sesiones.listar() == [] and win.vista == ("agente", "grok")


def test_refresh_after_a_meeting_opens_the_new_one(make_home):
    win = make_home()
    _save_session("coach", "Coach", "¿Recién?", dt.datetime(2026, 10, 29, 17, 0))

    win.refrescar(abrir_ultima=True)

    assert win.vista == ("sesion", "sesion-20261029-170000")


# ------------------------------------------------------------------ start
def test_start_button_emits_the_open_agent(make_home, qtbot):
    win = make_home(agent="coach")
    win.abrir_agente("senior")

    with qtbot.waitSignal(win.startMeeting) as senal:
        qtbot.mouseClick(_find(win, QtWidgets.QPushButton, "iniciar"), LEFT)

    assert senal.args == ["senior"]
    assert config.load_config()["agent"] == "senior"


def test_warning_shows_at_the_top_of_the_page(make_home):
    win = make_home()

    win.mostrar_aviso("Añade tu API key de OpenAI para iniciar la reunión.")

    assert _find(win, QtWidgets.QLabel, "aviso").text().startswith("Añade tu API key")


# ------------------------------------------------------------------ settings
def test_settings_are_a_separate_view(make_home):
    win = make_home()

    win.ir_a_ajustes()

    assert win.vista == ("ajustes", None) and win.nav_ajustes._activo is True


@pytest.mark.parametrize("key", ["openai_api_key", "assemblyai_api_key", "typesafe_api_key"])
def test_keys_are_masked_and_saved(make_home, key):
    win = make_home()
    win.ir_a_ajustes()
    campo = _row(win, key).findChild(QtWidgets.QLineEdit)

    campo.setText("  secreto  ")
    win.guardar_ya()

    assert campo.echoMode() == QtWidgets.QLineEdit.Password
    assert config.load_config()[key] == "secreto"


def test_language_and_opacity_are_saved(make_home):
    win = make_home()
    win.ir_a_ajustes()
    combo = _row(win, "language").findChild(QtWidgets.QComboBox)
    combo.setCurrentIndex(combo.findData("auto"))
    _row(win, "window_opacity").findChild(QtWidgets.QSlider).setValue(0)

    win.guardar_ya()

    cfg = config.load_config()
    assert (cfg["language"], cfg["window_opacity"]) == ("auto", 0.15)


@pytest.mark.parametrize("key", config.FIJAS)
def test_internal_settings_have_no_field(make_home, key):
    win = make_home()
    win.ir_a_ajustes()

    assert key not in [f.property("clave") for f in _page(win).findChildren(QtWidgets.QWidget, "fila")]


def test_close_saves_and_asks_to_quit(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok")
    _find(win, QtWidgets.QLineEdit, "nombre-agente").setText("Grok 3")

    with qtbot.waitSignal(win.closeApp):
        win._cerrar_app()

    assert agents.get("grok")["name"] == "Grok 3"


# ------------------------------------------------------------------ sidebar hover
def test_gear_and_arrow_show_on_hover(make_home, qtbot):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home(agent="coach")
    fila = win._filas_agente["grok"]

    antes = (fila.btn_editar.isVisibleTo(fila), fila.btn_flecha.isVisibleTo(fila))
    fila._hover = True
    fila._actualizar()

    assert antes == (False, False)
    assert (fila.btn_editar.isVisibleTo(fila), fila.btn_flecha.isVisibleTo(fila)) == (True, True)


def test_agent_without_meetings_has_no_arrow(make_home):
    win = make_home(agent="coach")
    fila = win._filas_agente["grok"]
    fila._hover = True
    fila._actualizar()

    assert fila.btn_flecha.isVisibleTo(fila) is False


def test_gear_opens_the_configuration(make_home, qtbot):
    win = make_home(agent="coach")

    qtbot.mouseClick(win._filas_agente["grok"].btn_editar, LEFT)

    assert win.vista == ("editar", "grok")


def test_opening_a_meeting_unfolds_its_agent(make_home):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()

    win.abrir_sesion("sesion-20261029-161800")

    assert "grok" in win._desplegados


# ------------------------------------------------------------------ markdown
def test_text_is_shown_rendered_by_default(make_home):
    win = make_home(agent="grok")
    win.editar_agente("grok", "reglas")

    vista = _find(win, QtWidgets.QTextBrowser, "vista-reglas")
    editor = _find(win, QtWidgets.QPlainTextEdit, "reglas")

    assert (vista.isVisibleTo(win), editor.isVisibleTo(win)) == (True, False)
    assert "#" not in vista.toPlainText().splitlines()[0]     # heading rendered


def test_edit_button_switches_to_raw_text_and_back(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok", "instrucciones")
    boton = _find(win, QtWidgets.QPushButton, "modo-instrucciones")

    qtbot.mouseClick(boton, LEFT)
    editor = _find(win, QtWidgets.QPlainTextEdit, "instrucciones")
    assert (editor.isVisibleTo(win), boton.text()) == (True, "Vista previa")
    editor.setPlainText("**Breve** y directo")
    qtbot.mouseClick(boton, LEFT)

    vista = _find(win, QtWidgets.QTextBrowser, "vista-instrucciones")
    assert vista.toPlainText().strip() == "Breve y directo"


def test_edit_mode_survives_a_redraw(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok", "instrucciones")
    qtbot.mouseClick(_find(win, QtWidgets.QPushButton, "modo-instrucciones"), LEFT)

    win._mostrar()

    assert _find(win, QtWidgets.QPlainTextEdit, "instrucciones").isVisibleTo(win) is True


def test_double_click_on_the_preview_starts_editing(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok", "instrucciones")
    vista = _find(win, QtWidgets.QTextBrowser, "vista-instrucciones")

    qtbot.mouseDClick(vista.viewport(), LEFT)

    assert _find(win, QtWidgets.QPlainTextEdit, "instrucciones").isVisibleTo(win) is True


def test_new_document_opens_ready_to_write(make_home):
    win = make_home(agent="senior")
    win.editar_agente("senior", "conocimiento")

    win._doc_add("senior")

    assert _find(win, QtWidgets.QPlainTextEdit, "cuerpo-documento").isVisibleTo(win) is True


def test_meeting_transcript_is_rendered(make_home):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()

    win.abrir_sesion("sesion-20261029-161800")

    texto = _find(win, QtWidgets.QTextBrowser, "transcripcion").toPlainText()
    assert "**" not in texto and "###" not in texto


# ------------------------------------------------------------------ tone
import estilo  # noqa: E402

CHAT = "".join(f"29/10/26, 16:{i:02d} - Yo: mensaje mío {i}\n"
               f"29/10/26, 16:{i:02d} - Ana: privado de Ana {i}\n" for i in range(30))


@pytest.fixture
def chat(isolated_data_dir):
    ruta = isolated_data_dir / "chat.txt"
    ruta.write_text(CHAT, encoding="utf-8")
    return str(ruta)


@pytest.fixture
def tone_home(make_home, monkeypatch):
    """Home whose background job runs inline and whose author dialog picks 'Yo'."""
    enviados = []
    win = make_home(agent="grok", openai_api_key="sk-test")
    win._lanzar = lambda trabajo, ok, ko: ok(trabajo())
    win._elegir_autor = lambda cuentas, mensajes: "Yo"
    monkeypatch.setattr(estilo, "generar_tono", lambda key, model, propios: (
        enviados.append(propios) or "## Registro\nCercano"))
    win.enviados = enviados
    win.editar_agente("grok", "tono")
    return win


def test_tone_tab_exists_next_to_instructions(make_home):
    win = make_home(agent="grok")
    win.editar_agente("grok")

    tabs = _find(win, hw.Segmented, "pestanas")

    assert list(tabs._btns) == ["instrucciones", "tono", "conocimiento", "permisos", "reglas"]


def test_tone_is_written_like_any_other_section(make_home):
    win = make_home(agent="grok")
    win.editar_agente("grok", "tono")

    _find(win, QtWidgets.QPlainTextEdit, "tono").setPlainText("Cercano, sin rodeos.")
    win.guardar_ya()

    assert agents.get("grok")["tono"] == "Cercano, sin rodeos."


def test_whatsapp_import_fills_the_tone(tone_home, chat):
    tone_home.analizar_export("grok", chat)
    tone_home.guardar_ya()

    assert agents.get("grok")["tono"] == "## Registro\nCercano"
    assert _find(tone_home, QtWidgets.QTextBrowser, "vista-tono").isVisibleTo(tone_home)


def test_only_my_messages_reach_the_model(tone_home, chat):
    tone_home.analizar_export("grok", chat)

    (propios,) = tone_home.enviados
    assert len(propios) == 30 and not any("Ana" in m for m in propios)


def test_import_can_be_undone(tone_home, chat, qtbot):
    tone_home._ag_get("grok")["tono"] = "Mi tono escrito a mano"
    tone_home.analizar_export("grok", chat)

    qtbot.mouseClick(_find(tone_home, QtWidgets.QPushButton, "deshacer-tono"), LEFT)

    assert tone_home._ag_get("grok")["tono"] == "Mi tono escrito a mano"


def test_cancelled_author_choice_sends_nothing(tone_home, chat):
    tone_home._elegir_autor = lambda cuentas, mensajes: None

    tone_home.analizar_export("grok", chat)

    assert tone_home.enviados == []


def test_too_few_messages_are_not_sent(tone_home, isolated_data_dir):
    corto = isolated_data_dir / "corto.txt"
    corto.write_text("29/10/26, 16:00 - Yo: hola\n", encoding="utf-8")

    tone_home.analizar_export("grok", str(corto))

    assert tone_home.enviados == [] and "pocos mensajes" in tone_home._aviso


def test_not_a_chat_is_explained(tone_home, isolated_data_dir):
    nada = isolated_data_dir / "nada.txt"
    nada.write_text("esto no es un chat", encoding="utf-8")

    tone_home.analizar_export("grok", str(nada))

    assert tone_home._aviso.startswith("No encontré mensajes")


def test_without_openai_key_nothing_is_sent(tone_home, chat):
    tone_home.values["openai_api_key"] = ""

    tone_home.analizar_export("grok", chat)

    assert tone_home.enviados == [] and "API key de OpenAI" in tone_home._aviso


def test_failed_analysis_keeps_the_tone_and_explains(tone_home, chat):
    tone_home._lanzar = lambda trabajo, ok, ko: ko("APIConnectionError: sin red")
    tone_home._ag_get("grok")["tono"] = "antes"

    tone_home.analizar_export("grok", chat)

    assert tone_home._ag_get("grok")["tono"] == "antes"
    assert tone_home._aviso == "No se pudo analizar tu estilo: APIConnectionError: sin red"
    assert tone_home._analizando is None


def test_author_dialog_says_what_will_be_sent(qtbot):
    mensajes = estilo.parsear(CHAT)
    dialogo = hw.ElegirAutor(estilo.autores(mensajes), mensajes)
    qtbot.addWidget(dialogo)
    dialogo.combo.setCurrentIndex(dialogo.combo.findData("Yo"))

    assert dialogo.info.text().startswith("Se enviarán a OpenAI tus últimos 30 mensajes")
    assert "Los mensajes de los demás no salen de tu equipo" in dialogo.info.text()
    assert dialogo.ok.isEnabled() is True


# ------------------------------------------------------------------ permissions
def test_permissions_tab_saves_the_mode(make_home):
    win = make_home(agent="grok")
    win.editar_agente("grok", "permisos")

    selector = _find(win, hw.Segmented, "modo")
    selector._btns["manual"].click()
    win.guardar_ya()

    assert agents.get("grok")["modo"] == "manual"
    assert _find(win, QtWidgets.QLabel, "modo-explicacion").text().startswith("Detecta las preguntas")


def test_notetaker_locks_screens_off_and_notes_on(make_home):
    win = make_home(agent="grok")
    win.editar_agente("grok", "permisos")

    _find(win, hw.Segmented, "modo")._btns["notetaker"].click()

    capturas = _find(win, hw.ToggleSwitch, "capturas")
    notas_ = _find(win, hw.ToggleSwitch, "notas")
    assert (capturas.isEnabled(), capturas.isChecked()) == (False, False)
    assert (notas_.isEnabled(), notas_.isChecked()) == (False, True)


def test_screens_and_notes_toggles_are_saved(make_home, qtbot):
    win = make_home(agent="grok")
    win.editar_agente("grok", "permisos")

    qtbot.mouseClick(_find(win, hw.ToggleSwitch, "capturas"), LEFT)
    qtbot.mouseClick(_find(win, hw.ToggleSwitch, "notas"), LEFT)
    win.guardar_ya()

    g = agents.get("grok")
    assert (g["capturas"], g["notas"]) == (False, False)


def test_agent_page_says_how_it_answers(make_home):
    lista = agents.list_agents()
    lista[2]["modo"] = "notetaker"
    agents.write_all(lista)
    win = make_home(agent="grok")

    assert _find(win, QtWidgets.QLabel, "modo-portada").text() == "Notetaker · solo toma notas"


# ------------------------------------------------------------------ meeting notes
def test_meeting_page_opens_on_its_notes(make_home):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    sesiones.guardar_notas("sesion-20261029-161800", "## Resumen\nSe habló de pagos.")
    win = make_home()

    win.abrir_sesion("sesion-20261029-161800")

    assert "Se habló de pagos." in _find(win, QtWidgets.QTextBrowser, "notas").toPlainText()


def test_meeting_page_switches_to_the_transcript(make_home):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    sesiones.guardar_notas("sesion-20261029-161800", "## Resumen\nx")
    win = make_home()
    win.abrir_sesion("sesion-20261029-161800")

    _find(win, hw.Segmented, "pestanas-sesion")._btns["transcripcion"].click()

    assert "¿Pagos?" in _find(win, QtWidgets.QTextBrowser, "transcripcion").toPlainText()


def test_meeting_without_notes_shows_only_the_transcript(make_home):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()

    win.abrir_sesion("sesion-20261029-161800")

    assert _find(win, hw.Segmented, "pestanas-sesion") is None


def test_notes_being_written_are_announced_then_shown(make_home):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()
    win.abrir_sesion("sesion-20261029-161800")

    win.notas_en_curso("sesion-20261029-161800")
    generando = _find(win, QtWidgets.QTextBrowser, "notas").toPlainText()
    sesiones.guardar_notas("sesion-20261029-161800", "## Resumen\nListo")
    win.notas_listas("sesion-20261029-161800", True)

    assert generando.startswith("Generando las notas")
    assert "Listo" in _find(win, QtWidgets.QTextBrowser, "notas").toPlainText()


def test_failed_notes_are_explained(make_home):
    _save_session("grok", "Grok", "¿Pagos?", dt.datetime(2026, 10, 29, 16, 18))
    win = make_home()
    win.abrir_sesion("sesion-20261029-161800")

    win.notas_listas("sesion-20261029-161800", False)

    assert _find(win, QtWidgets.QTextBrowser, "notas").toPlainText().startswith(
        "No se pudieron generar las notas")


# ------------------------------------------------------------------ mascot colour
def test_agent_page_shows_its_mascot(make_home):
    win = make_home(agent="grok")

    assert _find(win, avatares.Avatar, "cara").color == "coral"


def test_picking_a_colour_is_saved(make_home, monkeypatch):
    win = make_home(agent="grok")
    monkeypatch.setattr(win, "_elegir_color", lambda c, n: "lavanda")

    win.cambiar_color("grok")
    win.guardar_ya()

    assert agents.get("grok")["color"] == "lavanda"
    assert win._filas_agente["grok"]._cara == "lavanda"


def test_cancelled_picker_changes_nothing(make_home, monkeypatch):
    win = make_home(agent="grok")
    monkeypatch.setattr(win, "_elegir_color", lambda c, n: None)

    win.cambiar_color("grok")

    assert win._dirty is False


def test_picker_previews_the_colour(qtbot):
    dialogo = hw.ElegirColor("pervinca", "Coach")
    qtbot.addWidget(dialogo)

    qtbot.mouseClick(dialogo.findChild(QtWidgets.QAbstractButton, "color-menta"), LEFT)

    assert (dialogo.color, dialogo.vista.color) == ("menta", "menta")
    assert dialogo._colores["menta"].isChecked() and not dialogo._colores["pervinca"].isChecked()
