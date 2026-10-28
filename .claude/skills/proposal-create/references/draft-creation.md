# Exportación, auditoría y creación del borrador

Ejecuta desde la raíz de ProjectApp. En un worktree, reutiliza el venv del clon principal sin modificarlo:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
COMMON_ROOT=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
PY="$REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$COMMON_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$REPO_ROOT/backend/venv/bin/python"
[ -x "$PY" ] || PY="$COMMON_ROOT/backend/venv/bin/python"
[ -x "$PY" ] || { echo "No encuentro el Python de ProjectApp"; exit 1; }
SKILL_DIR="$REPO_ROOT/.agents/skills/proposal-create"
```

Para Claude puede usarse `.claude/skills/proposal-create`; los recursos son equivalentes.

## 1. Exportar plantilla activa

Elige explícitamente el settings module y el idioma:

```bash
mkdir -p "$REPO_ROOT/proposal-artifacts"
"$PY" "$SKILL_DIR/scripts/proposal_artifact.py" template \
  --settings projectapp.settings_prod \
  --language es \
  --output "$REPO_ROOT/proposal-artifacts/.template_es.json"
```

El comando es de solo lectura. Si el destino es desarrollo, usa `projectapp.settings_dev`; nunca permitas que `manage.py` caiga implícitamente a SQLite.

## 2. Auditar

```bash
"$PY" "$SKILL_DIR/scripts/proposal_artifact.py" audit \
  "$REPO_ROOT/proposal-artifacts/<archivo>.json" \
  "$REPO_ROOT/proposal-artifacts/<archivo>.manifest.json" \
  --template "$REPO_ROOT/proposal-artifacts/.template_es.json" \
  --settings projectapp.settings_prod
```

`AUDIT_FAIL` tiene exit code 1. Corrige y repite hasta `AUDIT_PASS`. Los `WARN` se incluyen en el resumen y no se esconden.

## 3. Simular la creación

Después del resumen auditado, pero antes de pedir autorización mutante:

```bash
"$PY" "$SKILL_DIR/scripts/create_draft.py" \
  "$REPO_ROOT/proposal-artifacts/<archivo>.json" \
  "$REPO_ROOT/proposal-artifacts/<archivo>.manifest.json" \
  --settings projectapp.settings_prod
```

Esto valida serializer, entorno, defaults estándar de hosting y duplicados sin crear registros.

Si devuelve `DUPLICATE_CANDIDATE`, muestra los IDs y títulos. Solo después de que el operador confirme que se trata de otra propuesta puede añadirse `--allow-duplicate` tanto al dry-run como al apply.

## 4. Crear el borrador

Requiere aprobación explícita posterior al resumen. El comando mutante necesita dos flags deliberados:

```bash
"$PY" "$SKILL_DIR/scripts/create_draft.py" \
  "$REPO_ROOT/proposal-artifacts/<archivo>.json" \
  "$REPO_ROOT/proposal-artifacts/<archivo>.manifest.json" \
  --settings projectapp.settings_prod \
  --apply \
  --confirm CREATE_DRAFT
```

Agrega `--allow-duplicate` únicamente si el operador aprobó el candidato informado en el dry-run.

El script nunca envía la propuesta. La salida correcta incluye `DRAFT_CREATED`, id, slug, mensaje personalizado persistido, total efectivo y URL administrativa. No abras la URL pública para verificar: una visita altera métricas.

## Fallos

- Entorno no coincidente: corrige `target_environment` o el settings module; no fuerces la ejecución.
- Defaults estándar de hosting cambiaron: vuelve a exportar, muestra los términos nuevos y reconfirma.
- Error del serializer o auditor: corrige el artefacto; no escribas por ORM manual.
- Error dentro de la creación: la transacción hace rollback. Conserva JSON y manifiesto para diagnóstico.
