"""Repositorios de GitHub como conocimiento de un agente.

Para preguntas sobre una implementacion ("¿por que usaste select_for_update?",
"¿como funciona tu idempotencia?") el agente tiene que conocer el codigo. Pero
meter el repo entero en el prompt al empezar la reunion seria lento y caro, asi
que todo lo pesado se hace ANTES, al conectarlo (o al pulsar Actualizar):

1. Se descarga el repo de GitHub (tarball de un commit concreto) y se queda
   una copia local de sus archivos de texto: repos/<id>/archivos.zip, con su
   manifest.json (commit, rama, fecha, archivos).
2. El modelo lee lo importante y escribe la MEMORIA del repo: que es, como
   esta montado, el modelo de datos, los flujos, las decisiones y donde esta
   cada cosa. Esa memoria es un documento mas del conocimiento del agente:
   va en el prompt, se ve y se edita en la Home, y se precarga en cache.
3. En la reunion, si hace falta el codigo exacto, el modelo lo lee de la copia
   local con dos herramientas (leer_archivos, buscar_en_repo): leer del disco
   es instantaneo y solo se manda lo que pide.

Repos privados: con un token de GitHub (Ajustes, se guarda cifrado). El token
solo viaja a la API de GitHub.
"""
import datetime as dt
import io
import json
import logging
import os
import re
import tarfile
import urllib.error
import urllib.request
import zipfile

import config as cfg_mod

log = logging.getLogger("armony.repos")

REPOS_DIR = os.path.join(cfg_mod.data_dir(), "repos")
API = "https://api.github.com"
USER_AGENT = "Armony-meeting-coach"

# Lo que se descarga y se guarda como mucho.
MAX_TARBALL = 300 * 1024 * 1024        # comprimido
MAX_ARCHIVO = 300_000                  # bytes por archivo de texto
MAX_ARCHIVOS = 6000
MAX_TOTAL = 60 * 1024 * 1024           # texto guardado en total

# Carpetas y archivos que no dicen nada de la implementacion (dependencias,
# compilados, caches) o que son ruido (lockfiles, minificados).
_DIRS_FUERA = {
    ".git", "node_modules", "vendor", "dist", "build", ".venv", "venv",
    "__pycache__", ".next", ".nuxt", "target", "coverage", "htmlcov",
    ".idea", ".pytest_cache", ".mypy_cache", ".tox", "bower_components",
    ".gradle", "Pods", ".terraform", ".svelte-kit", ".angular", ".cache",
    "site-packages", ".parcel-cache", ".turbo", ".expo",
}
_EXT_FUERA = {
    "png", "jpg", "jpeg", "gif", "webp", "ico", "svg", "bmp", "tif", "tiff",
    "pdf", "zip", "gz", "tgz", "tar", "7z", "rar", "bz2", "xz", "jar", "war",
    "class", "exe", "dll", "so", "dylib", "o", "a", "lib", "pyc", "pyo",
    "whl", "egg", "woff", "woff2", "ttf", "otf", "eot", "mp3", "mp4", "wav",
    "mov", "avi", "webm", "ogg", "flac", "m4a", "psd", "ai", "sketch", "fig",
    "db", "sqlite", "sqlite3", "bin", "dat", "pkl", "npy", "npz", "h5",
    "onnx", "pt", "pth", "ckpt", "safetensors", "parquet", "map", "keystore",
    "p12", "pfx", "der", "xcf", "icns", "apk", "ipa", "dmg", "iso",
}
_ARCHIVOS_FUERA = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "pipfile.lock", "cargo.lock", "composer.lock", "gemfile.lock", "go.sum",
    "uv.lock", "bun.lockb", "packages.lock.json", ".ds_store", "thumbs.db",
}


class RepoError(Exception):
    """Algo que el usuario tiene que saber (repo que no existe, token...)."""


# ------------------------------------------------------------------ la URL
_URL = re.compile(
    r"^(?:https?://(?:www\.)?github\.com/|git@github\.com:|github\.com/)?"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<nombre>[A-Za-z0-9._-]+?)"
    r"(?:\.git)?(?:/tree/(?P<rama>.+?))?/?$")


def parse_url(url):
    """(owner, nombre, rama o None) de una URL de GitHub o de "owner/nombre"."""
    m = _URL.match((url or "").strip())
    if not m or m.group("nombre") in (".", ".."):
        raise RepoError("Eso no parece un repositorio de GitHub "
                        "(https://github.com/usuario/repo).")
    return m.group("owner"), m.group("nombre"), m.group("rama")


def id_repo(owner, nombre, rama):
    """Nombre de la carpeta local: sin barras ni caracteres raros."""
    limpio = re.sub(r"[^A-Za-z0-9._-]", "~", f"{owner}__{nombre}__{rama}")
    return limpio[:180]


def carpeta(rid):
    return os.path.join(REPOS_DIR, rid)


# ------------------------------------------------------------------ GitHub
def _pedir(url, token=None, accept="application/vnd.github+json", timeout=30,
           limite=None):
    cabeceras = {"Accept": accept, "User-Agent": USER_AGENT,
                 "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if limite is None:
                return r.read()
            partes, total = [], 0
            while True:
                trozo = r.read(1 << 20)
                if not trozo:
                    break
                total += len(trozo)
                if total > limite:
                    raise RepoError(f"El repositorio pesa más de "
                                    f"{limite // (1024 * 1024)} MB comprimido.")
                partes.append(trozo)
            return b"".join(partes)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RepoError("No encuentro ese repositorio o rama. Si es privado, "
                            "añade un token de GitHub en Ajustes.") from None
        if e.code == 401:
            raise RepoError("GitHub rechazó el token: revísalo en Ajustes.") from None
        if e.code == 403:
            raise RepoError("GitHub no deja leerlo ahora (permiso o límite de "
                            "peticiones). Con un token en Ajustes el límite es "
                            "mucho mayor.") from None
        raise RepoError(f"GitHub respondió {e.code}.") from None
    except urllib.error.URLError as e:
        raise RepoError(f"No hay conexión con GitHub: {e.reason}") from None


def _json(url, token):
    return json.loads(_pedir(url, token).decode("utf-8"))


def info_remota(owner, nombre, rama=None, token=None):
    """La rama (la principal si no se dice) y su ultimo commit."""
    repo = _json(f"{API}/repos/{owner}/{nombre}", token)
    rama = rama or repo.get("default_branch") or "main"
    commit = _json(f"{API}/repos/{owner}/{nombre}/commits/"
                   f"{urllib.request.quote(rama, safe='')}", token)
    fecha = (((commit.get("commit") or {}).get("committer") or {}).get("date") or "")
    return {"owner": repo.get("owner", {}).get("login", owner),
            "nombre": repo.get("name", nombre), "rama": rama,
            "commit": commit["sha"], "fecha_commit": fecha,
            "privado": bool(repo.get("private"))}


# ------------------------------------------------------------------ archivos
def _ruta_util(ruta):
    """La ruta dentro del repo si el archivo interesa; None si no."""
    partes = [p for p in ruta.split("/") if p]
    if not partes or any(p in (".", "..") for p in partes):
        return None
    if any(p in _DIRS_FUERA for p in partes[:-1]):
        return None
    nombre = partes[-1].lower()
    if nombre in _ARCHIVOS_FUERA or nombre.endswith((".min.js", ".min.css")):
        return None
    ext = nombre.rsplit(".", 1)[-1] if "." in nombre else ""
    if ext in _EXT_FUERA:
        return None
    return "/".join(partes)


def _texto(datos):
    """El contenido como texto, o None si es binario."""
    if b"\x00" in datos[:8192]:
        return None
    try:
        return datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos.decode("latin-1")


def extraer(tar_bytes):
    """[(ruta, texto)] de los archivos de texto utiles del tarball de GitHub.

    No se escribe nada a disco desde el tar: se lee cada miembro en memoria y
    la ruta se recompone (sin la carpeta raiz que pone GitHub), asi que un tar
    con rutas raras no puede salirse de su sitio.
    """
    salida, total = [], 0
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as tar:
        for m in tar:
            if not m.isfile() or m.size > MAX_ARCHIVO:
                continue
            nombre = m.name.split("/", 1)[1] if "/" in m.name else ""
            ruta = _ruta_util(nombre)
            if ruta is None:
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            texto = _texto(f.read())
            if texto is None:
                continue
            total += len(texto)
            if total > MAX_TOTAL or len(salida) >= MAX_ARCHIVOS:
                log.info("Repo snapshot capped at %d files", len(salida))
                break
            salida.append((ruta, texto))
    salida.sort(key=lambda x: x[0])
    return salida


def guardar(rid, info, archivos):
    """Deja la copia local (zip + manifest), sustituyendo la anterior de golpe."""
    destino = carpeta(rid)
    os.makedirs(destino, exist_ok=True)
    zip_tmp = os.path.join(destino, "archivos.zip.tmp")
    with zipfile.ZipFile(zip_tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for ruta, texto in archivos:
            z.writestr(ruta, texto)
    manifest = dict(info, sincronizado=dt.datetime.now().isoformat(timespec="seconds"),
                    archivos=[{"ruta": r, "lineas": t.count("\n") + 1, "bytes": len(t)}
                              for r, t in archivos])
    man_tmp = os.path.join(destino, "manifest.json.tmp")
    with open(man_tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    os.replace(zip_tmp, os.path.join(destino, "archivos.zip"))
    os.replace(man_tmp, os.path.join(destino, "manifest.json"))
    return manifest


def leer_manifest(rid):
    try:
        with open(os.path.join(carpeta(rid), "manifest.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def descargar(url, rama=None, token=None, progreso=None):
    """Descarga el repo y guarda la copia local. Devuelve (rid, manifest, archivos)."""
    avisar = progreso or (lambda _t: None)
    owner, nombre, rama_url = parse_url(url)
    avisar("Consultando GitHub…")
    info = info_remota(owner, nombre, rama or rama_url, token)
    avisar("Descargando el código…")
    tar = _pedir(f"{API}/repos/{info['owner']}/{info['nombre']}/tarball/{info['commit']}",
                 token, accept="application/vnd.github+json", timeout=120,
                 limite=MAX_TARBALL)
    archivos = extraer(tar)
    if not archivos:
        raise RepoError("El repositorio no tiene archivos de texto que leer.")
    avisar(f"Guardando {len(archivos)} archivos…")
    info["url"] = f"https://github.com/{info['owner']}/{info['nombre']}"
    rid = id_repo(info["owner"], info["nombre"], info["rama"])
    manifest = guardar(rid, info, archivos)
    return rid, manifest, archivos


# ------------------------------------------------------------------ la memoria
# Lo que se le manda al modelo para escribirla (caracteres; ~4 por token).
MAX_ENTRADA_MEMORIA = 480_000
MAX_SALIDA_MEMORIA = 12_000            # tokens

_DOCS = re.compile(r"(^|/)(readme|claude|agents|contributing|architecture|design)"
                   r"[^/]*\.(md|rst|txt)$|(^|/)(docs?|adr|adrs)/.*\.(md|rst|txt)$", re.I)
_MANIFIESTOS = re.compile(
    r"(^|/)(pyproject\.toml|setup\.py|setup\.cfg|requirements[^/]*\.txt|package\.json|"
    r"go\.mod|cargo\.toml|pom\.xml|build\.gradle(\.kts)?|dockerfile|docker-compose[^/]*\.ya?ml|"
    r"compose\.ya?ml|makefile|procfile|manage\.py|tsconfig\.json|\.env\.example|"
    r"[^/]*\.tf)$|(^|/)\.github/workflows/", re.I)
_TESTS = re.compile(r"(^|/)(tests?|spec|__tests__)/|(^|/)(test_[^/]*|[^/]*_test\.[a-z]+|"
                    r"[^/]*\.(test|spec)\.[a-z]+)$", re.I)
# Configuracion de asistentes de IA (skills, agentes, comandos): dice poco de
# la implementacion y en algunos repos son cientos de archivos.
_HERRAMIENTAS_IA = re.compile(r"^\.(claude|agents|codex|cursor|windsurf|continue|"
                              r"github/(copilot|prompts|instructions))(/|$)", re.I)
_DATOS = re.compile(r"\.(json|csv|tsv|ya?ml|xml|txt|ini|cfg|toml|sql|ndjson|jsonl)$", re.I)

# Topes del material de la memoria (caracteres): la documentacion larga y los
# archivos enormes no pueden comerse el sitio del codigo.
MAX_DOC = 12_000                       # por documento
MAX_DOCS = 60_000                      # toda la documentacion junta
MAX_CODIGO = 40_000                    # por archivo de codigo
MAX_OTRO = 6_000                       # tests, datos, configuracion
_FIRMA = re.compile(
    r"^\s{0,4}(async\s+def|def|class|function|export\s+(default\s+)?(async\s+)?"
    r"(function|class|const|interface|type)|func|interface|type|struct|impl|fn|"
    r"public|private|protected|module|resource)\b")


def _prioridad(ruta):
    """0 docs, 1 manifiestos, 2 codigo, 3 tests, 4 datos, 5 herramientas de IA."""
    if _HERRAMIENTAS_IA.search(ruta):
        return 5
    if _MANIFIESTOS.search(ruta):
        return 1
    if _DOCS.search(ruta):
        return 0
    if _TESTS.search(ruta):
        return 3
    if _DATOS.search(ruta):
        return 4
    return 2


def _tope(prioridad):
    return {0: MAX_DOC, 2: MAX_CODIGO}.get(prioridad, MAX_OTRO)


def esquema(texto, max_lineas=40):
    """Las firmas (def, class, function...) de un archivo: su indice."""
    lineas = [ln.rstrip() for ln in texto.splitlines() if _FIRMA.match(ln)]
    return lineas[:max_lineas]


def entrada_memoria(manifest, archivos, maximo=MAX_ENTRADA_MEMORIA):
    """Lo que lee el modelo: cabecera, arbol, documentacion, configuracion y el
    codigo por orden de importancia; lo que no cabe entero va como esquema."""
    rutas = [r for r, _ in archivos]
    partes = [f"Repositorio: {manifest['owner']}/{manifest['nombre']} · rama "
              f"{manifest['rama']} · commit {manifest['commit'][:7]} "
              f"({manifest.get('fecha_commit', '')[:10]})",
              "ARBOL DE ARCHIVOS:\n" + "\n".join(rutas)]
    usado = sum(len(p) for p in partes)
    # Por importancia; dentro del codigo, primero lo de arriba del arbol y lo
    # mas grande (los modulos centrales), que es lo que mas explica.
    ordenados = sorted(archivos, key=lambda x: (
        _prioridad(x[0]), x[0].count("/"),
        -len(x[1]) if _prioridad(x[0]) == 2 else len(x[1])))
    fuera, docs = [], 0
    for ruta, texto in ordenados:
        prioridad = _prioridad(ruta)
        tope = _tope(prioridad)
        cuerpo = texto if len(texto) <= tope else (
            texto[:tope] + f"\n[... recortado: {len(texto) - tope} caracteres más ...]")
        bloque = f"===== {ruta} =====\n{cuerpo}"
        if prioridad == 0 and docs + len(bloque) > MAX_DOCS:
            fuera.append((ruta, texto))
            continue
        if usado + len(bloque) <= maximo:
            partes.append(bloque)
            usado += len(bloque)
            if prioridad == 0:
                docs += len(bloque)
        else:
            fuera.append((ruta, texto))
    if fuera:
        esquemas = []
        for ruta, texto in fuera:
            firmas = esquema(texto)
            esquemas.append(f"--- {ruta}" + ("\n" + "\n".join(firmas) if firmas else ""))
        bloque = ("===== ESQUEMA DE LOS ARCHIVOS QUE NO CABEN ENTEROS =====\n"
                  + "\n".join(esquemas))
        partes.append(bloque[:max(0, maximo - usado)])
    return "\n\n".join(partes)


PROMPT_MEMORIA = (
    "Vas a escribir la MEMORIA TECNICA de este repositorio. La va a usar un "
    "asistente que me sopla que decir en reuniones y entrevistas en las que me "
    "preguntan por ESTA implementacion (la hice yo): por que esta hecha asi, como "
    "funciona una parte, que pasaria si... Tiene que poder responder con detalle "
    "sin volver a leer el codigo, y saber donde mirar cuando necesite el codigo "
    "exacto.\n\n"
    "Escribe en markdown, en espanol, con estas secciones (las que no apliquen, "
    "fuera):\n"
    "## Qué es — que hace, para quien, que problema resuelve.\n"
    "## Arquitectura — estilo (monolito, servicios...), capas y modulos con sus "
    "rutas y responsabilidades, y como se comunican.\n"
    "## Stack — lenguaje, framework, base de datos, librerias clave y para que.\n"
    "## Modelo de datos — entidades, campos importantes, relaciones, "
    "restricciones y maquinas de estado.\n"
    "## Flujos principales — paso a paso, con los archivos y funciones por los "
    "que pasa cada uno.\n"
    "## Decisiones y porqués — cada decision tecnica que se ve en el codigo, "
    "con la razon probable, la alternativa descartada y su coste.\n"
    "## Detalles delicados — concurrencia, transacciones, idempotencia, "
    "seguridad, validacion, manejo de errores, dinero, rendimiento: como esta "
    "resuelto cada uno que aparezca, con archivo y funcion.\n"
    "## API e interfaces — endpoints o comandos con lo que reciben y devuelven.\n"
    "## Pruebas — que se prueba y como; lo que no.\n"
    "## Cómo se ejecuta y despliega.\n"
    "## Puntos débiles y mejoras — lo que un entrevistador podria criticar y "
    "como lo mejoraria.\n"
    "## Dónde está cada cosa — indice: concepto -> archivo:funcion.\n\n"
    "Reglas: nombres reales (archivos, clases, funciones, tablas, endpoints), "
    "nada inventado; si algo no se ve en lo que te paso, no lo supongas o dilo. "
    "Denso y concreto, sin relleno ni frases de marketing.")


def generar_memoria(api_key, model, manifest, archivos, effort="medium"):
    """La memoria del repo en markdown (una llamada al modelo; tarda)."""
    import openai
    cliente = openai.OpenAI(api_key=api_key, max_retries=1,
                            timeout=openai.Timeout(600, connect=10))
    entrada = [
        {"role": "developer", "content": [{"type": "input_text", "text": PROMPT_MEMORIA}]},
        {"role": "user", "content": [{"type": "input_text",
                                      "text": entrada_memoria(manifest, archivos)}]},
    ]
    respuesta = cliente.responses.create(
        model=model, input=entrada, reasoning={"effort": effort},
        max_output_tokens=MAX_SALIDA_MEMORIA + 4000)
    texto = (getattr(respuesta, "output_text", "") or "").strip()
    if not texto:
        raise RepoError("El modelo no devolvió la memoria.")
    return texto


MAX_ARBOL = 400                        # rutas que se listan en el documento


def arbol(manifest, maximo=MAX_ARBOL):
    """Las rutas del repo para el documento: todas si caben; si no, cuantos
    archivos hay en cada carpeta (el resto lo encuentra buscar_en_repo). La
    configuracion de asistentes de IA va siempre resumida por carpeta."""
    todas = [a["ruta"] for a in manifest.get("archivos", [])]
    ia = {}
    for r in todas:
        if _HERRAMIENTAS_IA.search(r):
            clave = r.split("/")[0] + "/"
            ia[clave] = ia.get(clave, 0) + 1
    rutas = [r for r in todas if not _HERRAMIENTAS_IA.search(r)]
    resumen_ia = [f"{c} ({n})" for c, n in sorted(ia.items())]
    if len(rutas) <= maximo:
        return "\n".join(resumen_ia + rutas)
    carpetas = {}
    for r in rutas:
        partes = r.split("/")
        clave = "/".join(partes[:2]) + "/" if len(partes) > 2 else (
            partes[0] + "/" if len(partes) > 1 else r)
        carpetas[clave] = carpetas.get(clave, 0) + 1
    return "\n".join(resumen_ia + [f"{c} ({n})" if c.endswith("/") else c
                                   for c, n in sorted(carpetas.items())])


def documento(manifest, memoria):
    """El cuerpo del documento de conocimiento: cabecera, memoria y archivos."""
    cab = (f"# Repositorio {manifest['owner']}/{manifest['nombre']}\n"
           f"Rama `{manifest['rama']}` · commit `{manifest['commit'][:7]}` "
           f"({manifest.get('fecha_commit', '')[:10]}) · "
           f"{len(manifest.get('archivos', []))} archivos. Si necesitas el código "
           f"exacto, léelo con leer_archivos / buscar_en_repo.")
    return f"{cab}\n\n{memoria.strip()}\n\n## Archivos\n```\n{arbol(manifest)}\n```\n"


def sincronizar(url, rama=None, token=None, api_key=None, model="gpt-6.1-sol",
                progreso=None):
    """Todo el trabajo previo: descargar, guardar y escribir la memoria.
    Devuelve (rid, manifest, cuerpo del documento)."""
    avisar = progreso or (lambda _t: None)
    rid, manifest, archivos = descargar(url, rama, token, progreso=avisar)
    if not api_key:
        raise RepoError("Añade tu API key de OpenAI en Ajustes para escribir la memoria.")
    avisar(f"Leyendo {len(archivos)} archivos y escribiendo la memoria… "
           f"(puede tardar un par de minutos)")
    memoria = generar_memoria(api_key, model, manifest, archivos)
    return rid, manifest, documento(manifest, memoria)


# ------------------------------------------------------------------ en la reunion
MAX_LECTURA = 120_000                  # caracteres por llamada a leer_archivos
MAX_POR_ARCHIVO = 60_000
MAX_COINCIDENCIAS = 60


class Herramientas:
    """Lo que el modelo puede hacer con las copias locales durante la reunion.

    Se crean al empezar la reunion (leer el manifest es instantaneo); los
    archivos se descomprimen la primera vez que se piden.
    """

    def __init__(self, repos):
        """repos: [(rid, manifest)] con copia local."""
        self._repos = [(rid, m) for rid, m in repos if m]
        self._textos = {}              # rid -> {ruta: texto}

    def __bool__(self):
        return bool(self._repos)

    @property
    def nombres(self):
        return [m["nombre"] for _rid, m in self._repos]

    def definiciones(self):
        varios = len(self._repos) > 1
        rutas = ("Rutas tal como salen en la lista de archivos del repositorio"
                 + (" (con varios repos, empieza por su nombre: repo/ruta)" if varios else ""))
        return [
            {"type": "function", "name": "leer_archivos",
             "description": (
                 "Lee el contenido exacto (con numeros de linea) de archivos del "
                 "repositorio conectado. Usalo cuando la memoria del repositorio "
                 "no baste para responder con precision: codigo concreto, una "
                 "linea, un detalle. Hasta 6 archivos por llamada."),
             "parameters": {"type": "object", "properties": {
                 "rutas": {"type": "array", "items": {"type": "string"},
                           "description": rutas}},
                 "required": ["rutas"], "additionalProperties": False},
             "strict": True},
            {"type": "function", "name": "buscar_en_repo",
             "description": (
                 "Busca un texto (sin distinguir mayusculas) en todos los archivos "
                 "del repositorio y devuelve ruta:linea: contenido. Para encontrar "
                 "donde se define o usa algo antes de leerlo."),
             "parameters": {"type": "object", "properties": {
                 "texto": {"type": "string", "description": "Lo que se busca, literal"}},
                 "required": ["texto"], "additionalProperties": False},
             "strict": True},
        ]

    def _cargar(self, rid):
        if rid not in self._textos:
            try:
                with zipfile.ZipFile(os.path.join(carpeta(rid), "archivos.zip")) as z:
                    self._textos[rid] = {n: z.read(n).decode("utf-8", "replace")
                                         for n in z.namelist()}
            except (OSError, zipfile.BadZipFile):
                log.warning("Repo snapshot not readable: %s", rid)
                self._textos[rid] = {}
        return self._textos[rid]

    def _resolver(self, ruta):
        ruta = (ruta or "").strip().lstrip("/").replace("\\", "/")
        for rid, m in self._repos:
            for candidata in (ruta, ruta[len(m["nombre"]) + 1:]
                              if ruta.startswith(m["nombre"] + "/") else None):
                if candidata and candidata in self._cargar(rid):
                    return rid, m, candidata
        return None

    def leer(self, rutas):
        salida, usado = [], 0
        for ruta in list(rutas or [])[:6]:
            hallado = self._resolver(ruta)
            if hallado is None:
                salida.append(f"=== {ruta}: no existe en el repositorio ===")
                continue
            rid, m, r = hallado
            texto = self._textos[rid][r]
            recorte = len(texto) > MAX_POR_ARCHIVO
            texto = texto[:MAX_POR_ARCHIVO]
            numerado = "\n".join(f"{i:>4}| {ln}" for i, ln in
                                 enumerate(texto.splitlines(), 1))
            bloque = (f"=== {m['nombre']}/{r} ===\n{numerado}"
                      + ("\n[... archivo recortado ...]" if recorte else ""))
            if usado + len(bloque) > MAX_LECTURA:
                salida.append(f"=== {r}: no cabe en esta lectura, pídelo aparte ===")
                continue
            salida.append(bloque)
            usado += len(bloque)
        return "\n\n".join(salida) or "(sin rutas)"

    def buscar(self, texto):
        aguja = (texto or "").strip().lower()
        if len(aguja) < 2:
            return "Busca al menos dos caracteres."
        hallados = []
        for rid, m in self._repos:
            for ruta, contenido in self._cargar(rid).items():
                for i, ln in enumerate(contenido.splitlines(), 1):
                    if aguja in ln.lower():
                        hallados.append(f"{m['nombre']}/{ruta}:{i}: {ln.strip()[:200]}")
                        if len(hallados) >= MAX_COINCIDENCIAS:
                            return "\n".join(hallados) + "\n[... hay más coincidencias ...]"
        return "\n".join(hallados) or f"Sin coincidencias para «{texto}»."

    def ejecutar(self, nombre, argumentos):
        """Resultado (texto) de una llamada del modelo. Nunca lanza."""
        try:
            args = json.loads(argumentos or "{}")
            if nombre == "leer_archivos":
                return self.leer(args.get("rutas"))
            if nombre == "buscar_en_repo":
                return self.buscar(args.get("texto"))
            return f"Herramienta desconocida: {nombre}"
        except Exception as e:                       # argumentos rotos, disco...
            log.warning("Repo tool %s failed: %s", nombre, type(e).__name__)
            return f"No se pudo: {type(e).__name__}"


def herramientas(agente):
    """Las herramientas de los repos del agente con copia local, o None."""
    repos = []
    for d in agente.get("conocimiento", []):
        rid = (d.get("repo") or {}).get("id")
        if rid:
            repos.append((rid, leer_manifest(rid)))
    h = Herramientas(repos)
    return h if h else None
