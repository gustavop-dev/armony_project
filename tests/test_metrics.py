"""Tests for metrics.Metricas: sample aggregation, counters, report output."""
import json

import pytest

import metrics
from metrics import Metricas


@pytest.fixture
def clock(monkeypatch):
    """Controllable replacement for time.monotonic inside metrics."""
    now = {"t": 1000.0}
    monkeypatch.setattr(metrics.time, "monotonic", lambda: now["t"])
    return now


@pytest.fixture
def m(clock):
    instance = Metricas()
    instance.iniciar()
    return instance


def test_summary_without_samples_has_empty_sections(m):
    assert m.resumen() == {"duracion_s": 0.0, "cuentas": {}, "notas": [],
                           "medidas": {}}


def test_summary_before_start_reports_zero_duration():
    assert Metricas().resumen()["duracion_s"] == 0


def test_duration_uses_time_since_start(m, clock):
    clock["t"] += 12.34

    assert m.resumen()["duracion_s"] == 12.3


def test_none_sample_is_ignored(m):
    m.medir("x", None)

    assert m.resumen()["medidas"] == {}


def _feed(m, name, values):
    for v in values:
        m.medir(name, v)


def test_measure_statistics_over_ten_samples(m):
    _feed(m, "x", (100, 20, 30, 40, 50, 60, 70, 80, 90, 10))

    assert m.resumen()["medidas"]["x"] == {"n": 10, "mediana": 55, "p90": 100,
                                           "min": 10, "max": 100}


def test_single_sample_statistics(m):
    m.medir("x", 7.6)

    assert m.resumen()["medidas"]["x"] == {"n": 1, "mediana": 8, "p90": 8,
                                           "min": 8, "max": 8}


def test_counter_accumulates(m):
    m.contar("a")
    m.contar("a", 3)

    assert m.resumen()["cuentas"] == {"a": 4}


def test_notes_keep_insertion_order(m):
    m.nota("first")
    m.nota("second")

    assert m.resumen()["notas"] == ["first", "second"]


def test_start_clears_previous_session(m):
    m.medir("x", 1)
    m.contar("a")
    m.nota("n")

    m.iniciar()

    assert m.resumen() == {"duracion_s": 0.0, "cuentas": {}, "notas": [],
                           "medidas": {}}


def test_stopwatch_records_elapsed_ms(m, clock):
    with m.cronometro("x"):
        clock["t"] += 0.25

    assert m.resumen()["medidas"]["x"]["mediana"] == 250


def test_stopwatch_does_not_swallow_exceptions(m):
    with pytest.raises(ValueError):
        with m.cronometro("x"):
            raise ValueError("boom")


def test_text_report_layout(m):
    m.nota("provider: anthropic")
    m.medir("x", 5)
    m.contar("a", 2)

    assert m.texto().splitlines() == [
        "Reunion de 0.0 s",
        "  provider: anthropic",
        "",
        "  medida                       n   mediana     p90     min     max",
        "  x                            1        5 ms      5       5       5",
        "",
        "  a                                      2",
    ]


def test_save_writes_json_report(m, tmp_path):
    m.medir("x", 5)

    ruta = m.guardar(str(tmp_path))

    with open(ruta, encoding="utf-8") as f:
        assert json.load(f)["medidas"]["x"]["n"] == 1


def test_save_writes_text_report_next_to_json(m, tmp_path):
    ruta = m.guardar(str(tmp_path))

    with open(ruta.replace(".json", ".txt"), encoding="utf-8") as f:
        assert f.read() == "Reunion de 0.0 s\n"


def test_save_returns_none_when_folder_is_not_writable(m, tmp_path):
    bloqueo = tmp_path / "file"
    bloqueo.write_text("not a dir")

    assert m.guardar(str(bloqueo)) is None
