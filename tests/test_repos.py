"""repos.py: GitHub URLs, download filtering, the local snapshot, the memory
input and the tools the model uses in the meeting. No network: GitHub calls go
through a fake urlopen or a replaced _pedir."""
import io
import json
import tarfile
import urllib.error

import pytest

import repos


def make_tar(files, root="owner-repo-abc1234"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            if isinstance(data, str):
                data = data.encode("utf-8")
            info = tarfile.TarInfo(f"{root}/{name}" if root else name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


MANIFEST = {"owner": "gus", "nombre": "acme", "rama": "main", "commit": "abc1234def",
            "fecha_commit": "2026-11-03T10:00:00Z", "url": "https://github.com/gus/acme",
            "privado": False}


# ------------------------------------------------------------------ URLs
@pytest.mark.parametrize("url, esperado", [
    ("https://github.com/gus/acme", ("gus", "acme", None)),
    ("https://github.com/gus/acme.git", ("gus", "acme", None)),
    ("https://github.com/gus/acme/", ("gus", "acme", None)),
    ("https://github.com/gus/acme/tree/feat/ledger-v2", ("gus", "acme", "feat/ledger-v2")),
    ("git@github.com:gus/acme.git", ("gus", "acme", None)),
    ("github.com/gus/acme", ("gus", "acme", None)),
    ("gus/acme", ("gus", "acme", None)),
    ("  https://www.github.com/gus/my.repo_x  ", ("gus", "my.repo_x", None)),
])
def test_github_urls_are_understood(url, esperado):
    assert repos.parse_url(url) == esperado


@pytest.mark.parametrize("url", ["", "https://gitlab.com/gus/acme", "acme",
                                 "https://github.com/gus/acme/pull/3", "gus/.."])
def test_other_urls_are_rejected(url):
    with pytest.raises(repos.RepoError):
        repos.parse_url(url)


def test_local_id_has_no_path_separators():
    rid = repos.id_repo("gus", "acme", "feat/x:y")

    assert "/" not in rid and ":" not in rid and rid.startswith("gus__acme__feat")


# ------------------------------------------------------------------ filtering
@pytest.mark.parametrize("ruta, util", [
    ("app/ledger.py", True),
    ("README.md", True),
    ("node_modules/x/index.js", False),
    ("web/dist/app.js", False),
    ("src/.venv/lib.py", False),
    ("package-lock.json", False),
    ("static/logo.png", False),
    ("static/app.min.js", False),
    ("docs/diagram.svg", False),
    ("../etc/passwd", False),
    ("a/./b.py", False),
    (".github/workflows/ci.yml", True),
])
def test_only_useful_text_files_are_kept(ruta, util):
    assert (repos._ruta_util(ruta) is not None) == util


def test_tarball_is_read_in_memory_without_its_root_folder():
    tar = make_tar({
        "app/ledger.py": "def post():\n    pass\n",
        "README.md": "# Acme",
        "logo.png": b"\x89PNG\x00\x00",
        "data.bin2": b"abc\x00def",
        "node_modules/a.js": "x",
        "big.py": "x" * (repos.MAX_ARCHIVO + 1),
    })

    archivos = repos.extraer(tar)

    assert [r for r, _ in archivos] == ["README.md", "app/ledger.py"]
    assert dict(archivos)["app/ledger.py"].startswith("def post")


def test_tarball_entries_cannot_escape():
    tar = make_tar({"../../evil.py": "x", "ok.py": "y"}, root="root")

    assert [r for r, _ in repos.extraer(tar)] == ["ok.py"]


def test_latin1_files_are_still_read():
    tar = make_tar({"viejo.txt": "año".encode("latin-1")})

    assert repos.extraer(tar) == [("viejo.txt", "año")]


# ------------------------------------------------------------------ snapshot
def test_snapshot_round_trip(isolated_data_dir):
    manifest = repos.guardar("gus__acme__main", dict(MANIFEST),
                             [("a.py", "uno\ndos"), ("b/c.md", "# C")])

    assert manifest["archivos"] == [{"ruta": "a.py", "lineas": 2, "bytes": 7},
                                    {"ruta": "b/c.md", "lineas": 1, "bytes": 3}]
    assert repos.leer_manifest("gus__acme__main")["commit"] == "abc1234def"
    assert sorted(p.name for p in (isolated_data_dir / "repos" / "gus__acme__main").iterdir()) \
        == ["archivos.zip", "manifest.json"]


def test_missing_snapshot_has_no_manifest():
    assert repos.leer_manifest("nada") is None


def test_download_pins_the_commit_and_saves_it(monkeypatch):
    pedidas = []

    def pedir(url, token=None, **kw):
        pedidas.append((url, token))
        if url.endswith("/repos/gus/acme"):
            return json.dumps({"default_branch": "main", "private": True,
                               "owner": {"login": "gus"}, "name": "acme"}).encode()
        if "/commits/" in url:
            return json.dumps({"sha": "abc1234def", "commit": {
                "committer": {"date": "2026-11-03T10:00:00Z"}}}).encode()
        return make_tar({"app.py": "print(1)"})

    monkeypatch.setattr(repos, "_pedir", pedir)
    pasos = []

    rid, manifest, archivos = repos.descargar("https://github.com/gus/acme", token="tok",
                                              progreso=pasos.append)

    assert rid == "gus__acme__main"
    assert pedidas[-1][0].endswith("/repos/gus/acme/tarball/abc1234def")
    assert all(t == "tok" for _u, t in pedidas)
    assert manifest["privado"] is True and archivos == [("app.py", "print(1)")]
    assert pasos[0] == "Consultando GitHub…"


def test_branch_from_the_url_is_used(monkeypatch):
    pedidas = []

    def pedir(url, token=None, **kw):
        pedidas.append(url)
        if url.endswith("/repos/gus/acme"):
            return json.dumps({"default_branch": "main"}).encode()
        if "/commits/" in url:
            return json.dumps({"sha": "f" * 40}).encode()
        return make_tar({"a.py": "x"})

    monkeypatch.setattr(repos, "_pedir", pedir)

    rid, manifest, _ = repos.descargar("https://github.com/gus/acme/tree/feat/x")

    assert pedidas[1].endswith("/commits/feat%2Fx")
    assert manifest["rama"] == "feat/x"


def test_empty_repository_is_an_error(monkeypatch):
    def pedir(url, token=None, **kw):
        if "/commits/" in url:
            return json.dumps({"sha": "f" * 40}).encode()
        if url.endswith("/repos/gus/acme"):
            return b"{}"
        return make_tar({"logo.png": b"\x00"})

    monkeypatch.setattr(repos, "_pedir", pedir)

    with pytest.raises(repos.RepoError, match="no tiene archivos de texto"):
        repos.descargar("gus/acme")


class FakeResponse:
    def __init__(self, data):
        self.data = io.BytesIO(data)

    def read(self, n=-1):
        return self.data.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_token_goes_only_in_the_github_request(monkeypatch):
    vistas = []

    def urlopen(req, timeout=None):
        vistas.append((req.full_url, dict(req.header_items())))
        return FakeResponse(b"{}")

    monkeypatch.setattr(repos.urllib.request, "urlopen", urlopen)

    repos._pedir("https://api.github.com/repos/gus/acme", "secreto")

    url, cabeceras = vistas[0]
    assert url.startswith("https://api.github.com/")
    assert cabeceras["Authorization"] == "Bearer secreto"
    assert cabeceras["User-agent"] == repos.USER_AGENT


@pytest.mark.parametrize("codigo, texto", [
    (404, "Si es privado, añade un token"),
    (401, "rechazó el token"),
    (403, "límite de peticiones"),
    (500, "GitHub respondió 500"),
])
def test_github_errors_are_explained(monkeypatch, codigo, texto):
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, codigo, "x", {}, None)

    monkeypatch.setattr(repos.urllib.request, "urlopen", urlopen)

    with pytest.raises(repos.RepoError, match=texto):
        repos._pedir("https://api.github.com/repos/gus/acme")


def test_oversized_download_is_stopped(monkeypatch):
    monkeypatch.setattr(repos.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse(b"x" * (3 << 20)))

    with pytest.raises(repos.RepoError, match="pesa más de"):
        repos._pedir("https://api.github.com/x", limite=2 << 20)


# ------------------------------------------------------------------ the memory
def test_memory_input_puts_docs_and_config_before_code_and_tests():
    archivos = [("tests/test_ledger.py", "def test_x(): pass"), ("app/ledger.py", "def post(): pass"),
                ("README.md", "# Acme"), ("pyproject.toml", "[project]")]

    texto = repos.entrada_memoria(MANIFEST, archivos)

    orden = [texto.index(f"===== {r} =====") for r in
             ("README.md", "pyproject.toml", "app/ledger.py", "tests/test_ledger.py")]
    assert orden == sorted(orden)
    assert texto.startswith("Repositorio: gus/acme · rama main · commit abc1234")
    assert "ARBOL DE ARCHIVOS:\ntests/test_ledger.py" in texto


def test_files_that_do_not_fit_go_as_an_outline():
    grande = "class Ledger:\n    def post(self):\n        x = 1\n" + "# relleno\n" * 2000
    archivos = [("README.md", "# Acme"), ("app/ledger.py", grande)]

    texto = repos.entrada_memoria(MANIFEST, archivos, maximo=5000)

    assert "===== app/ledger.py =====" not in texto
    assert "--- app/ledger.py\nclass Ledger:\n    def post(self):" in texto
    assert len(texto) <= 5000 + 200


def test_document_has_header_memory_and_files():
    manifest = dict(MANIFEST, archivos=[{"ruta": "a.py"}, {"ruta": "b/c.py"}])

    cuerpo = repos.documento(manifest, "## Qué es\nUn ledger.")

    assert cuerpo.startswith("# Repositorio gus/acme\nRama `main` · commit `abc1234`")
    assert "## Qué es\nUn ledger." in cuerpo
    assert cuerpo.rstrip().endswith("## Archivos\n```\na.py\nb/c.py\n```")


def test_big_trees_are_summarised_by_folder():
    rutas = [{"ruta": f"src/mod{i}/f.py"} for i in range(300)] + \
            [{"ruta": f"tests/t{i}.py"} for i in range(200)] + [{"ruta": "README.md"}]

    texto = repos.arbol({"archivos": rutas})

    assert "tests/ (200)" in texto and "src/mod1/ (1)" in texto and "README.md" in texto


def test_sync_downloads_then_writes_the_memory(monkeypatch):
    monkeypatch.setattr(repos, "descargar", lambda url, rama, token, progreso:
                        ("rid", dict(MANIFEST, archivos=[{"ruta": "a.py"}]), [("a.py", "x")]))
    usados = []
    monkeypatch.setattr(repos, "generar_memoria",
                        lambda clave, modelo, m, a: usados.append((clave, modelo)) or "## Qué es\nX")

    rid, manifest, cuerpo = repos.sincronizar("gus/acme", api_key="sk", model="m")

    assert rid == "rid" and usados == [("sk", "m")]
    assert "## Qué es\nX" in cuerpo


def test_sync_without_openai_key_explains_it(monkeypatch):
    monkeypatch.setattr(repos, "descargar", lambda *a, **k: ("rid", dict(MANIFEST), [("a", "b")]))

    with pytest.raises(repos.RepoError, match="API key de OpenAI"):
        repos.sincronizar("gus/acme")


# ------------------------------------------------------------------ in the meeting
@pytest.fixture
def snapshot():
    codigo = "\n".join(f"linea {i}" for i in range(1, 6))
    repos.guardar("gus__acme__main", dict(MANIFEST),
                  [("app/ledger.py", "def post():\n    return SELECT_FOR_UPDATE\n"),
                   ("README.md", codigo)])
    return repos.Herramientas([("gus__acme__main", repos.leer_manifest("gus__acme__main"))])


def test_reading_returns_numbered_lines(snapshot):
    texto = snapshot.leer(["app/ledger.py"])

    assert texto == ("=== acme/app/ledger.py ===\n   1| def post():\n"
                     "   2|     return SELECT_FOR_UPDATE")


def test_reading_accepts_the_repo_prefix_and_reports_missing(snapshot):
    texto = snapshot.leer(["acme/README.md", "no/existe.py"])

    assert "=== acme/README.md ===" in texto
    assert "=== no/existe.py: no existe en el repositorio ===" in texto


def test_long_files_are_cut(snapshot, monkeypatch):
    monkeypatch.setattr(repos, "MAX_POR_ARCHIVO", 12)

    assert snapshot.leer(["README.md"]).endswith("[... archivo recortado ...]")


def test_search_is_case_insensitive_with_path_and_line(snapshot):
    assert snapshot.buscar("select_for_update") == (
        "acme/app/ledger.py:2: return SELECT_FOR_UPDATE")


def test_search_needs_two_characters_and_says_when_nothing_matches(snapshot):
    assert snapshot.buscar("x") == "Busca al menos dos caracteres."
    assert snapshot.buscar("kafka") == "Sin coincidencias para «kafka»."


def test_tool_calls_never_raise(snapshot):
    assert snapshot.ejecutar("leer_archivos", "{roto").startswith("No se pudo")
    assert snapshot.ejecutar("borrar_todo", "{}") == "Herramienta desconocida: borrar_todo"
    assert "def post" in snapshot.ejecutar("leer_archivos", '{"rutas": ["app/ledger.py"]}')
    assert "ledger.py:2" in snapshot.ejecutar("buscar_en_repo", '{"texto": "select"}')


def test_tool_definitions_are_strict_functions(snapshot):
    defs = snapshot.definiciones()

    assert [d["name"] for d in defs] == ["leer_archivos", "buscar_en_repo"]
    assert all(d["type"] == "function" and d["strict"] is True
               and d["parameters"]["additionalProperties"] is False for d in defs)


def test_agent_without_a_synced_repo_has_no_tools():
    assert repos.herramientas({"conocimiento": [{"id": "d", "body": "x"}]}) is None
    assert repos.herramientas({"conocimiento": [{"id": "d", "repo": {"url": "gus/acme"}}]}) is None


def test_agent_with_a_synced_repo_gets_tools(snapshot):
    agente = {"conocimiento": [{"id": "d", "repo": {"id": "gus__acme__main"}}]}

    h = repos.herramientas(agente)

    assert h.nombres == ["acme"]


def test_ai_assistant_config_goes_last_and_collapsed_in_the_tree():
    archivos = [(".claude/skills/plan/SKILL.md", "# skill"), ("app/ledger.py", "def post(): pass"),
                (".agents/skills/x.md", "x")]

    texto = repos.entrada_memoria(MANIFEST, archivos)
    arbol = repos.arbol({"archivos": [{"ruta": r} for r, _ in archivos]})

    assert texto.index("===== app/ledger.py") < texto.index("===== .claude/skills/plan/SKILL.md")
    assert arbol.splitlines() == [".agents/ (1)", ".claude/ (1)", "app/ledger.py"]


def test_long_docs_and_modules_are_cut_to_leave_room_for_code(monkeypatch):
    monkeypatch.setattr(repos, "MAX_DOC", 100)
    monkeypatch.setattr(repos, "MAX_CODIGO", 200)
    archivos = [("README.md", "d" * 500), ("app/core.py", "c" * 1000)]

    texto = repos.entrada_memoria(MANIFEST, archivos)

    assert "d" * 100 + "\n[... recortado: 400 caracteres más ...]" in texto
    assert "c" * 200 + "\n[... recortado: 800 caracteres más ...]" in texto


def test_documentation_has_a_total_budget(monkeypatch):
    monkeypatch.setattr(repos, "MAX_DOCS", 150)
    archivos = [("docs/a.md", "a" * 100), ("docs/b.md", "b" * 100), ("app.py", "x = 1")]

    texto = repos.entrada_memoria(MANIFEST, archivos)

    assert "===== docs/a.md" in texto and "===== app.py" in texto
    assert "===== docs/b.md" not in texto and "--- docs/b.md" in texto


def test_core_modules_come_before_small_helpers():
    archivos = [("utils.py", "x = 1"), ("engine.py", "def run():\n" + "    pass\n" * 500)]

    texto = repos.entrada_memoria(MANIFEST, archivos)

    assert texto.index("===== engine.py") < texto.index("===== utils.py")
