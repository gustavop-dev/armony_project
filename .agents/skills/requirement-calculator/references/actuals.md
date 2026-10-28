# Cierres de estimación — ledger de calibración contra la realidad

Bandeja **append-only** de la fase §7-bis del `SKILL.md` (mismo patrón que
`pending-signals.md`): el skill registra acá los dos momentos de cierre de cada
estimate y **nunca** recalibra las tablas por su cuenta — la recalibración la
decide el dueño cuando los datos la sustentan.

Formato de cada entrada (una línea por evento):

- **Momento venta:** `- <DDMMYYYY> · #<id> · desenlace: vendido|rechazado|recortado|vencido · monto cerrado: $X,XM (vs techo $Y,YM)`
- **Momento entrega:** `- <DDMMYYYY> · #<id> · horas estimadas: A–B · horas reales: ≈C (fuente: registro del operador; proxy: rango de fechas del PR de release) · desvío: ±N% · causa: <una frase>`

**Regla de recalibración:** con ≥3 cierres de entrega del mismo nivel, comparar
la mediana de horas reales contra la banda del nivel en `market-pricing.md`;
desvío sostenido >±30% → proponer recalibración de la tabla (la regla de
mantenimiento del baseline en `validation/` absorbe el cambio). Los desenlaces
de venta contrastan, con volumen suficiente, los umbrales del semáforo
($12M/$20M — hoy disposición de pago declarada, no medida).

---
