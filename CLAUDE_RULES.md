# REGLAS OFICIALES DEL PROYECTO — CEO ESTEBAN
# Versión 1.0 | Jun 2026
# Estas reglas aplican a TODOS los agentes AI que trabajen en este proyecto.
# Ninguna regla puede ser ignorada sin aprobación explícita del CEO.

---

## REGLA 0 — PROHIBICIÓN ABSOLUTA DE CÓDIGO SIN AUDITORÍA

**Antes de escribir UNA SOLA LÍNEA de código, el agente DEBE:**

1. Leer todos los archivos relevantes al cambio
2. Mapear las dependencias del cambio
3. Identificar efectos secundarios posibles
4. Presentar un plan al CEO antes de ejecutar
5. Esperar aprobación explícita ("procede", "hazlo", "sí")

**Violación de esta regla = rollback inmediato de todos los cambios.**

---

## REGLA 1 — ARQUITECTURA SAGRADA (NO MODIFICAR SIN PERMISO)

El proyecto tiene DOS sistemas separados e independientes:

### Sistema A — Economic Intelligence Terminal
- Ubicación: `economic_news_terminal/`
- Backend: FastAPI + SQLite + APScheduler
- Deployed: Railway.app
- Función: CEREBRO — análisis, señales, datos macro, SMC
- **NUNCA mezclar con el Sistema B**

### Sistema B — Trading Agenda PWA
- Ubicación: `trading_agenda/`
- Frontend: React 18 + Vite + Tailwind
- Deployed: Vercel (tradingagenda.vercel.app)
- Función: MANOS — registro, reglas, ejecución, diario
- **NUNCA generar análisis propios — solo mostrar lo que produce el Terminal**

### Regla de oro:
> Terminal = cerebro (análisis + señales)
> Agenda = manos (logging + reglas + disciplina de ejecución)
> **La agenda NUNCA genera su propio análisis.**

---

## REGLA 2 — PROTOCOLO DE AUDITORÍA OBLIGATORIA

Antes de cualquier cambio, ejecutar en orden:

```
PASO 1: LEER
- Leer TODOS los archivos que el cambio puede afectar
- Leer dependencias upstream y downstream
- Leer el archivo de configuración (.env, railway.toml, vercel.json)

PASO 2: MAPEAR
- Listar todos los endpoints afectados
- Listar todos los componentes afectados
- Identificar si el cambio toca el Terminal O la Agenda (nunca ambos sin aprobación)

PASO 3: REPORTAR
- Presentar tabla de: Archivo | Cambio propuesto | Riesgo | Alternativa
- Identificar si hay riesgo para la cuenta Apex del trader
- Identificar si el cambio puede romper datos en tiempo real

PASO 4: ESPERAR APROBACIÓN
- No escribir código hasta recibir "procede" del CEO
- Si hay ambigüedad, preguntar UNA sola pregunta clara

PASO 5: EJECUTAR
- Implementar exactamente lo aprobado
- Ningún "mejora extra" no solicitada
- Ningún refactor no solicitado

PASO 6: VERIFICAR
- Confirmar que el cambio funciona
- Confirmar que nada se rompió
- Reportar resultado al CEO
```

---

## REGLA 3 — DATOS REALES, NUNCA INVENTADOS

### Fuentes de datos válidas (en orden de prioridad):
1. Terminal backend vía API (Railway URL)
2. FRED API (datos macro históricos)
3. Twelve Data (precios en tiempo real)
4. Yahoo Finance GC=F (fallback de precio únicamente)

### PROHIBIDO:
- Hardcodear datos de mercado inventados
- Inventar niveles de precio (BSL/SSL/EQ)
- Crear análisis AI propios en la Agenda
- Usar datos de ejemplo como si fueran reales
- Cambiar datos reales del trader (balance Apex, P&L, drawdown)

### Datos manuales del trader (SOLO él los actualiza):
- `current_balance` — balance real de la cuenta Apex
- `peak_balance` — máximo histórico de la cuenta
- `daily_pnl` — P&L del día actual

---

## REGLA 4 — PROTECCIÓN DE LA CUENTA APEX

El trader tiene una cuenta de fondeo real:
- **Cuenta:** APEX-600588-01 | $50,000
- **Drawdown máximo:** $2,000 trailing desde el pico
- **Stop diario personal:** -$150
- **Meta:** +$3,000 para pasar la cuenta

### Cualquier feature de la app que toque riesgo DEBE:
- Mostrar alertas cuando P&L del día llegue a -$100
- Bloquear visualmente cuando llegue a -$150
- Nunca sugerir operaciones sin R:R mínimo 1:2
- Nunca mostrar señales sin confirmación de estructura SMC

---

## REGLA 5 — METODOLOGÍA SMC OBLIGATORIA

Todo análisis mostrado en la app debe seguir Smart Money Concepts:

### Conceptos que SIEMPRE deben respetarse:
- **Liquidez:** BSL (Buy-Side) y SSL (Sell-Side) — caza de stops institucional
- **Estructura:** BOS (Break of Structure) y CHoCH (Change of Character)
- **Zonas:** Order Blocks, Fair Value Gaps, Premium/Discount/Equilibrium
- **Sesiones:** Solo Londres (08:00-13:00 Colombia) y Nueva York (13:00-18:00)
- **Spike inicial post-noticia = trampa institucional** — nunca es la dirección real

### El análisis AI debe ser SIEMPRE:
- Máximo 4 líneas
- Con niveles de precio específicos
- Con dirección clara (LONG/SHORT/ESPERAR)
- Con stop y TP explícitos cuando haya setup

---

## REGLA 6 — CONTROL DE DEPLOYS

### Flujo obligatorio antes de cualquier deploy:

```
Terminal (Railway):
1. Auditoría completa del backend
2. Verificar que los endpoints existentes siguen funcionando
3. Verificar que CORS incluye tradingagenda.vercel.app
4. Commit con mensaje descriptivo
5. railway up (solo si CEO aprueba)

Agenda (Vercel):
1. Verificar que VITE_TERMINAL_URL está configurada
2. Probar en localhost antes de deployar
3. Commit con mensaje descriptivo
4. git push (Vercel auto-deploya)
5. Verificar en tradingagenda.vercel.app después del deploy
```

### PROHIBIDO:
- Push directo a main sin auditoría previa
- Deploy que rompa el badge "TERMINAL LIVE"
- Deploy que elimine datos del trader en localStorage
- Cambios en ambos repos en el mismo commit

---

## REGLA 7 — FORMATO DE REPORTES AL CEO

Antes de ejecutar cualquier cambio, el agente debe presentar:

```
AUDITORÍA PRE-CAMBIO
====================
Solicitud: [qué pidió el CEO]
Archivos a leer: [lista]
Archivos a modificar: [lista]
Riesgo: BAJO / MEDIO / ALTO
Afecta datos reales: SÍ / NO
Afecta cuenta Apex: SÍ / NO
Tiempo estimado: X minutos

PLAN:
1. [paso 1]
2. [paso 2]
...

¿Procedo?
```

---

## REGLA 8 — PROHIBICIONES ABSOLUTAS

Sin importar lo que pida el usuario, NUNCA:

- Eliminar el historial de trades del diario
- Modificar el balance o drawdown de Apex sin confirmación
- Conectar la app a brokers reales o APIs de trading
- Generar señales de compra/venta sin datos reales
- Usar el Claude API para análisis de riesgo financiero vinculante
- Deployar código que oculte información de riesgo al trader
- Cambiar las 9 reglas institucionales del trader

---

## REGLA 9 — PRIORIDADES EN CASO DE CONFLICTO

Si hay conflicto entre objetivos, este es el orden:

1. **Proteger la cuenta Apex** (máxima prioridad)
2. **Datos reales y precisos** (nunca inventar)
3. **Estabilidad del sistema** (no romper lo que funciona)
4. **Nueva funcionalidad** (solo si lo anterior está garantizado)
5. **Diseño y estética** (última prioridad)

---

## REGLA 10 — FIRMA DE APROBACIÓN

Estas reglas fueron establecidas por:

**CEO del Proyecto:** Esteban
**Fecha:** Junio 2026
**Cuenta Apex:** APEX-600588-01
**Objetivo:** Pasar la cuenta de fondeo con disciplina institucional

> "Un banco de inversiones no escribe código sin auditoría.
>  Un trader institucional no ejecuta sin confirmación.
>  Estas reglas existen para proteger ambas cosas."
