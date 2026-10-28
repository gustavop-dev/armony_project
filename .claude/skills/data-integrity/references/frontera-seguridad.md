# Frontera de seguridad de data-integrity

Qué toca y qué no toca esta skill, y qué hay que decirle al operador antes de cada paso.

## «Sólo leer» también escribe una línea de auditoría

- **Cada llamada MCP, aun de lectura, graba una fila `McpRequestLog`** en la base de
  producción (`backend/content/views/mcp_blog.py`) y puede actualizar `last_used_at` del
  conector y de su credencial.
- **Llamar una herramienta sensible crea una fila `McpActionIntent`**, aunque sea sólo
  para ver su vista previa (`apply_integrity_fixes`, `undo_integrity_operation`). Esa fila
  vence a los 10 minutos (`backend/content/mcp/confirmation.py`).
- **Cómo se le dice al operador, antes de la primera consulta:** «cada consulta deja una
  línea de auditoría del MCP; no cambia ningún dato».
- **El comando de sólo lectura no deja esa línea.** `manage.py audit_data_integrity` la
  evita: lo corre el operador en el VPS después del deploy e imprime sólo ids de regla,
  conteos y `modelo:id`.

## Conectores

- Los nombres de los conectores cambian por cuenta: en una cuenta pueden figurar
  «Gestor de Proyectos», en otra otro nombre. Las herramientas se buscan **por nombre
  base** con ToolSearch.
- **Un conector que no conecta no es «sin hallazgos».** Ese chequeo queda **requiere
  validación**, con el conector como dato faltante.

## Antes de la primera corrección en producción

1. **Respaldo verificado de la base y de la media.**
   - La media entra porque las señales `post_delete` borran el archivo físico al borrar
     una fila (`backend/accounts/signals.py`, `backend/content/signals.py`). Una fila
     borrada se recupera con el respaldo de la base; su archivo, sólo con el de la media.
   - El respaldo lo dispara el operador con las herramientas del toolkit; esta skill nunca
     lo corre.
   - Su referencia (fecha y ruta o identificador) se anota en el `reason` de cada lote.
2. **Aprobación del lote en la conversación**, por escrito, después de ver su vista previa.

## Lo que nunca se toca (sólo se informa)

- Inmutables y de solo-anexar:
  - `EntityRevision`;
  - `ImmutableContractRecord`, `ImmutablePromptRecord` e `ImmutableDeliveryEvidence`;
  - los `*Event` y los `*ChangeLog`;
  - `ProjectRetentionOperation`, `McpRequestLog`, `ContractTemplateVersion`,
    `DataIntegrityOperation` y `DocumentOwnershipOperation`.
- Las filas conservadas de un proyecto eliminado, salvo por su adopción auditada.
- Importes, y números de documentos emitidos o pagados: una cuenta de cobro emitida se
  anula por su flujo, nunca se borra ni se renumera.
- Lo firmado o aprobado de las entregas.
- Campos de secretos: `EntityRevision.secrets`, los accesos administrativos de proyectos,
  `McpCredential` y `LinkedInToken`.
- Referencias por id que existen para sobrevivir al borrado: `AccountingChangeLog.object_id`,
  `EmailLogTarget.object_id`, `EntityHistory` y los ids de retención y reasignación.

## Datos de clientes y secretos

- **Ningún dato de cliente** en el chat, en reportes locales, commits, PRs ni logs: ni
  nombres, ni correos, ni teléfonos, ni documentos de identidad, ni montos por cliente, ni
  textos.
  - Los nombres se ven en las vistas del panel o del MCP que abre el operador.
  - Fuera de ahí se reportan ids de regla, ids de registro, conteos y huellas.
- **Ningún secreto:** no se piden, pegan ni imprimen tokens, contraseñas ni valores de un
  `.env`. De un `.env` sólo se nombran claves.

## Dónde nunca

- **Nunca una sesión corriendo comandos en un VPS:** ni `tailscale ssh`, ni Django, ni
  consultas a la base. En producción, el comando lo tipea el operador.
- **Nunca desde un worktree contra el `.env` enlazado.**
- **Nunca `migrate`, `shell` ni `dbshell`.**
