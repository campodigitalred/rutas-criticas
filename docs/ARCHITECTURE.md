# Campo Crítico — Arquitectura & Especificación Funcional

> Plataforma web y móvil de **Agencia Campo Digital** para transformar ideas y proyectos
> en **Rutas Críticas** (CPM/PERT) visuales, automatizadas e inteligentes.

---

## 1. Propósito y contexto

Agencia Campo Digital opera en la intersección de **tecnología, agricultura, desarrollo rural
y transformación digital**. *Campo Crítico* permite que consultores, directores de proyecto y
aliados rurales ingresen una idea preliminar o un proyecto estructurado y obtengan un mapa de
ruta exacto con:

- Tiempos (tempranos, tardíos) y holguras.
- Dependencias entre tareas (FS / SS / FF / SF).
- Identificación de cuellos de botella (camino crítico).
- Asignación y detección de sobreasignación de recursos.
- Simulación de escenarios de riesgo (clima, presupuesto, plazos).

**Restricción de dominio clave:** los técnicos trabajan frecuentemente en zonas rurales con
**conectividad intermitente o nula**, por lo que la app debe operar en **modo offline limitado**
y sincronizar cuando recupere señal.

---

## 2. Vista general de la arquitectura

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          CLIENTES (Responsive + PWA)                       │
│                                                                            │
│  Web App (React + Vite)        Móvil (React Native / Expo — reusa core)    │
│  ├─ Diagrama de Red (PERT)      ├─ Vista Gantt táctil                       │
│  ├─ Gantt drag & drop           ├─ Kanban de ejecución                      │
│  ├─ Kanban                      └─ Captura offline (IndexedDB / SQLite)     │
│  └─ Dashboard EVM                                                          │
└───────────────┬───────────────────────────────┬──────────────────────────┘
                │ REST/JSON (HTTPS)              │  Sync cola offline
                ▼                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       API GATEWAY / BACKEND (FastAPI)                      │
│                                                                            │
│  Auth (JWT/OAuth2)   Proyectos   Tareas   Dependencias   Recursos          │
│                                                                            │
│  ┌───────────────────────┐   ┌──────────────────────┐   ┌───────────────┐  │
│  │  Motor CPM/PERT (core) │   │  Motor de Simulación │   │ Asistente IA  │  │
│  │  ES/EF/LS/LF, slack,   │   │  "¿Qué pasaría si…?" │   │  Desglose EDT │  │
│  │  camino crítico        │   │  Monte Carlo         │   │  (LLM)        │  │
│  └───────────────────────┘   └──────────────────────┘   └───────────────┘  │
│                                                                            │
│  Exportador (PDF / PNG / XLSX / MS Project XML / P6)                       │
└───────────────┬───────────────────────────────┬──────────────────────────┘
                │                                │
                ▼                                ▼
      ┌───────────────────┐            ┌───────────────────────┐
      │ PostgreSQL (datos)│            │ Redis (cache/colas)    │
      │ + esquema DAG     │            │ Celery workers (async) │
      └───────────────────┘            └───────────────────────┘
```

---

## 3. Módulos y funcionalidades

### A. Módulo de Ingreso Inteligente (Onboarding de ideas/proyectos)

| Función | Descripción | Implementación |
|---|---|---|
| **Asistente IA de desglose** | Texto libre o nota de voz transcrita → Estructura de Desglose del Trabajo (EDT/WBS). | Endpoint `POST /ai/breakdown`. Prompt estructurado a un LLM que devuelve tareas, duraciones estimadas y dependencias sugeridas en JSON validado por esquema (Pydantic). Transcripción de voz vía Whisper. |
| **Formulario estructurado** | Objetivos, presupuesto, fecha límite improrrogable, stakeholders, restricciones geográficas/conectividad. | Entidad `Project` + `Constraint`. La restricción de conectividad alimenta el planificador (tareas de campo sin dependencia de red). |

**Flujo:** idea → borrador de EDT (editable por el usuario) → confirmación → generación de ruta.

### B. Motor de Generación de Ruta Crítica (algoritmo core)

- **Cálculo CPM/PERT:** pase hacia adelante (ES/EF), pase hacia atrás (LS/LF), holgura total y libre.
- **PERT:** estimación de tres puntos `te = (o + 4m + p) / 6`, varianza `σ² = ((p − o)/6)²`,
  desviación estándar del proyecto sobre el camino crítico → probabilidad de cumplir la fecha meta.
- **Camino crítico:** tareas con holgura total = 0, resaltadas de forma inequívoca.
- **Gestor de dependencias:** relaciones **FS, SS, FF, SF** con *lag/lead* configurable.

> Implementación de referencia: [`backend/app/cpm/engine.py`](../backend/app/cpm/engine.py).

### C. Interfaz visual e interactiva (UX/UI)

| Vista | Propósito | Librería sugerida |
|---|---|---|
| **Diagrama de Red (PERT)** | Nodos interactivos mostrando la secuencia lógica. | React Flow / vis-network / d3.js |
| **Gantt dinámico** | Drag & drop que modifica fechas y **recalcula la ruta crítica en tiempo real**. | frappe-gantt / dhtmlx / componente propio + d3 |
| **Kanban de ejecución** | Seguimiento diario de tareas derivadas de la ruta. | dnd-kit / react-beautiful-dnd |

Prototipo de referencia: [`frontend/src/components/CriticalPathView.jsx`](../frontend/src/components/CriticalPathView.jsx).

### D. Gestión de recursos y simulación ("¿Qué pasaría si…?")

- **Asignación de personal y maquinaria** con **alertas por sobreasignación** (histograma de carga por recurso vs. capacidad).
- **Modo simulación:** clonar el escenario base y aplicar perturbaciones (p. ej. *"las lluvias retrasan la fase de campo 15 días"*). El sistema recalcula:
  - Nueva fecha final y desplazamiento del camino crítico.
  - Impacto presupuestal (costo por retraso / recurso extra).
  - Probabilidad de cumplir el hito con **Monte Carlo** sobre distribuciones PERT.

### E. Exportación y reportes

- **Formatos:** PDF ejecutivo, PNG del diagrama, Excel (XLSX), **MS Project (.xml)** y **Primavera P6 (XER/XML)**.
- **Dashboard de control (EVM):** PV, EV, AC, CPI, SPI, % de avance y semáforo de salud del proyecto.

---

## 4. Stack técnico

| Capa | Tecnología | Motivo |
|---|---|---|
| Frontend web | **React 18 + Vite + TypeScript** | Ecosistema maduro, PWA sencilla. |
| Visualización | **d3.js / React Flow / frappe-gantt** | Grafos, Gantt interactivo. |
| Estado | Zustand / React Query | Estado local + cache de servidor. |
| Móvil | React Native (Expo) reutilizando el core TS | Un solo modelo de dominio. |
| Backend | **Python 3.11 + FastAPI** | Async, tipado con Pydantic, ideal para algoritmos. |
| Algoritmos | NumPy / networkx (validación DAG) | Cálculo CPM, Monte Carlo. |
| Async | Celery + Redis | Simulaciones y exportaciones pesadas. |
| Base de datos | **PostgreSQL 15** | Integridad relacional, consultas recursivas (CTE) para DAG. |
| Cache/offline | IndexedDB (web) / SQLite (móvil) | Modo offline limitado. |
| Auth | OAuth2 + JWT | Roles: consultor, director, aliado. |
| IA | LLM vía API + Whisper | Desglose EDT y transcripción. |

---

## 5. Sistema de diseño (agro + tecnología)

Paleta inspirada en el agro y lo digital: verdes profundos, azules digitales, grises limpios.

| Token | Hex | Uso |
|---|---|---|
| `--cc-green-900` | `#14432A` | Fondo de marca, headers. |
| `--cc-green-600` | `#2E7D4F` | Acciones primarias, tareas OK. |
| `--cc-green-300` | `#8FD3A8` | Estados de éxito, avance. |
| `--cc-blue-600`  | `#1E6FD9` | Enlaces, acentos digitales. |
| `--cc-blue-300`  | `#7FB4F2` | Bordes/hover. |
| `--cc-critical`  | `#E4572E` | **Camino crítico / alertas**. |
| `--cc-slack`     | `#F2B705` | Holgura ajustada / advertencias. |
| `--cc-gray-900`  | `#1F2933` | Texto principal. |
| `--cc-gray-500`  | `#7B8794` | Texto secundario. |
| `--cc-gray-100`  | `#F5F7FA` | Fondo de superficie. |

- Tipografía: `Inter` / `IBM Plex Sans` (legible en campo, soporta datos densos).
- Responsivo *mobile-first*; objetivos táctiles ≥ 44px para uso en tablet en campo.
- Accesibilidad AA: el camino crítico se distingue por **color + patrón/borde** (no solo color).

---

## 6. Estrategia offline ✅ (implementada)

1. **Lectura offline:** el proyecto activo se cachea (snapshot) en IndexedDB/localStorage al abrirlo
   — `frontend/src/lib/offlineStore.js`.
2. **Escritura offline:** los cambios (avance/estado de tareas, notas de campo) se encolan como
   *mutations* con `ts` y `base_ts`; ediciones repetidas del mismo campo se colapsan.
3. **Sincronización:** al recuperar señal, la cola se envía a `POST /api/v1/sync`; el motor
   (`backend/app/sync/engine.py`) resuelve conflictos por **last-write-wins a nivel de campo**
   (conflicto = `server_ts > base_ts`; gana el `ts` mayor) y **marca los conflictos para revisión**
   (`SyncStatusBar`).
4. **Recálculo local:** el motor CPM está portado a JavaScript (`frontend/src/lib/cpm.js`) para
   recalcular la ruta sin conexión; el servidor revalida al sincronizar.

> El motor de sincronización tiene **paridad exacta** Python ↔ JavaScript
> (`backend/app/sync/engine.py` ↔ `frontend/src/lib/sync.js`) y está cubierto por pruebas
> (`tests/test_sync.py`).

---

## 7. Estructura del repositorio

```
rutas-criticas/
├── docs/
│   ├── ARCHITECTURE.md      ← este documento
│   ├── DATA_MODEL.md        ← modelo entidad-relación (Mermaid + notas)
│   └── API.md               ← endpoints REST
├── db/
│   └── schema.sql           ← esquema PostgreSQL
├── backend/
│   ├── app/
│   │   ├── cpm/engine.py     ← Motor CPM/PERT (core)
│   │   ├── schemas.py        ← modelos Pydantic
│   │   └── main.py           ← API FastAPI
│   ├── tests/test_engine.py  ← pruebas del motor
│   └── requirements.txt
└── frontend/
    └── src/components/CriticalPathView.jsx  ← prototipo React
```
