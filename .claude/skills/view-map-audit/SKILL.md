---
name: view-map-audit
description: "Alias legado de [[view-map-update]] en modo `--check`. Usar cuando prompts viejos o hábitos del equipo todavía piden auditar el Mapa de vistas (`/panel/views`) sin modificar archivos."
argument-hint: "[<section-id>|<url-prefix>|all]"
---

Alias legado de [[view-map-update]] `--check`: la misma auditoría read-only del
Mapa de vistas (`/panel/views`) —estructura global más semántica del alcance—,
sin escribir nada.

- `/view-map-audit` ≡ `/view-map-update --check` (alcance por defecto: `--since`)
- `/view-map-audit <section-id|url-prefix>` ≡ `/view-map-update --check <section-id|url-prefix>`
- `/view-map-audit all` ≡ `/view-map-update --check --all`
- Nunca pasa a `--apply`: para corregir, `/view-map-update --apply …`.

Gating e invocación: los de [[view-map-update]], con el modo fijo en `--check`
(alias, regla de `## Skills alias` de [[_output-protocol]]).

---

## Output final

Reportar siguiendo [[_output-protocol]]. Misma plantilla que `/view-map-update`.
