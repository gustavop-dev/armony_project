# Verificación independiente (Fase 5)

Un hallazgo o una corrección no se dan por buenos porque los afirme quien los produjo.
Los revisa un verificador fresco: un subagente de sólo lectura que no detectó ni corrigió
nada en esta corrida.

## Qué recibe

- **Sólo la lista de afirmaciones, cada una con su fuente.** La fuente es la regla y su
  invariante con `archivo:línea`, el canal por el que se midió (herramienta MCP o
  `audit_data_integrity`), el alcance y los ids de registro.
- **Nunca el razonamiento** de quien detectó o corrigió.
- **Nunca datos de clientes:** ni nombres, ni correos, ni montos por cliente.

## Qué hace

1. Re-deriva cada invariante desde su `archivo:línea`. Si el código cambió, manda el código.
2. Vuelve a medir **por el mismo canal** y con el mismo alcance.
3. Intenta refutar cada afirmación con:
   - una excepción de diseño, por ejemplo «la carpeta organiza y no es dueña»;
   - una excepción de negocio, como un cobro de diagnóstico sin proyecto o los hijos
     derivados de una liquidación;
   - la semántica de NULL, porque SQL no iguala dos nulos;
   - un dato que cambió entre las dos mediciones;
   - un conector caído.

## Veredictos

| Veredicto | Cuándo | Lleva |
|---|---|---|
| **confirmado** | Re-medido igual, invariante citado, sin excepción que aplique | La medición y la cita |
| **requiere validación** | Falta un dato para decidir | El dato exacto que falta: qué conteo, qué test, qué decisión o qué conector |
| **rechazado** | No es un problema | La razón: por diseño, excepción de negocio, falso positivo o ya corregido |

## Después de una corrección

- **Baja exacta:** desaparecen exactamente los ids esperados del hallazgo corregido.
- **Sin efectos colaterales:** cero hallazgos nuevos en los chequeos vecinos (mismo dominio
  y mismos registros).
- **Lo no tocado sigue igual:** sus huellas no cambian. El `impact_hash` de la vista previa
  y los valores antes/después del registro `DataIntegrityOperation` son la referencia.

## Sello

La salida del verificador se guarda fuera de todo repo, en una carpeta privada (0700), y
se sella con `sha256sum` en un `SHA256SUMS`. Al operador se le informa la ruta y el
sha256, nunca el contenido.
