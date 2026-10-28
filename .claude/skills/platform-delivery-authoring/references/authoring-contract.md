# Contrato operativo de autoría

Descubrir el esquema vivo antes de construir argumentos. El conector `projects`
se presenta como Gestor de la plataforma; la administración usa sus servicios
compartidos y no toma decisiones ordinarias del cliente.

| Operación | Herramienta | Efecto |
| --- | --- | --- |
| Consultar proyecto y jerarquía | `get_project`, `get_delivery_overview` | Lectura administrativa |
| Consultar opciones y JSON | `get_delivery_authoring_contract` | Lectura de contrato, fuentes y esquemas |
| Preparar guías | `create_delivery_guide_prompt` | Guarda contexto y copias privadas seleccionadas |
| Reabrir preparación | `list_delivery_prompt_contexts`, `get_delivery_prompt_context` | Lectura de capturas históricas |
| Descargar fuente capturada | `download_delivery_prompt_source` | Bytes originales privados por contexto/source_key |
| Previsualizar borradores | `preview_delivery_import` | Valida JSON sin aplicar jerarquía |
| Aplicar borradores | `apply_delivery_import` | Operación confirmada y versionada, atómica e idempotente |

El JSON usa la plantilla v2 del contexto. Las citas deben pertenecer a fuentes
y fragmentos realmente capturados. El contrato u otrosí sustenta el alcance;
una referencia de código explica conducta, no sustituye ese fundamento.
Una asociación administrativa no acredita incorporación contractual del anexo.

Las claves editoriales identifican elementos dentro del padre. Lo omitido no se
borra. Ni una guía aprobada ni una etapa/fase aprobada reciben modificaciones
silenciosas. La revisión parcial conserva lo conforme entre nuevas rondas.

El inventario de código se crea por el esquema descubierto de Documentos,
con privacidad explícita y sin secretos. Debe seguir siendo administrativo:
no asociarlo a un nivel público, no adjuntarlo al cliente y no habilitar firma.

Una fuente de aprobación `approval_file_id`, cuando el esquema la admite,
selecciona una copia del cierre confirmada para ese proyecto; excluye las otras
fuentes contractuales. No acredita firma. El registro contractual es explícito,
previo a la captura; esta skill no debe crearlo automáticamente por faltar.
Las fuentes no PDF conservan formato original y sus límites de lectura.

Publicación y respuesta son operaciones distintas. Para proponer una respuesta
usa `create_delivery_reply_prompt` y `preview_delivery_reply`, conservando
conversación pública, clasificaciones y citas; compartirla requiere la revisión
humana y la acción autorizada correspondiente. Los avisos automáticos del
producto no habilitan envíos MCP adicionales desde esta skill.
