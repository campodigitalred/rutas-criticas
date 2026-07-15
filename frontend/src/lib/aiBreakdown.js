/**
 * Asistente IA de desglose — espejo en JavaScript del núcleo Python
 * (backend/app/ai). Genera una EDT/WBS a partir de texto libre usando plantillas
 * de dominio y detección de plazo, y valida/escala el plan con el motor CPM.
 *
 * Permite el flujo de ingreso inteligente en el cliente y en modo offline. En
 * producción, el frontend debería llamar a `POST /api/v1/ai/breakdown` (que usa
 * un LLM real cuando está configurado) y usar este generador solo como respaldo.
 */
import { computeCPM } from "./cpm.js";

/* ------------------------- Detección de dominio --------------------------- */
const DOMAIN_KEYWORDS = {
  data_collection: ["censo", "encuesta", "levantamiento", "padrón", "padron", "registro de productores"],
  software: ["digitaliz", "plataforma", "app", "aplicación", "aplicacion", "sistema", "software", "portal", "tablero"],
  training: ["capacit", "formación", "formacion", "taller", "escuela de campo", "adiestr"],
  agri_field: ["riego", "cultivo", "siembra", "cosecha", "parcela", "invernadero", "suelo"],
};

const TIME_UNITS = {
  día: 1, dia: 1, días: 1, dias: 1,
  semana: 7, semanas: 7,
  mes: 30, meses: 30,
  año: 365, ano: 365, años: 365, anos: 365,
};
const TIME_RE = /(\d+(?:[.,]\d+)?)\s*(días|dias|día|dia|semanas|semana|meses|mes|años|anos|año|ano)/i;

export function detectHorizonDays(text) {
  const m = text.match(TIME_RE);
  if (!m) return null;
  const qty = parseFloat(m[1].replace(",", "."));
  return qty * (TIME_UNITS[m[2].toLowerCase()] ?? 1);
}

function detectDomain(text) {
  const low = text.toLowerCase();
  for (const [domain, keywords] of Object.entries(DOMAIN_KEYWORDS)) {
    if (keywords.some((k) => low.includes(k))) return domain;
  }
  return "generic";
}

const t = (temp_id, name, phase, o, m, p, is_milestone = false) => ({
  temp_id, name, phase, optimistic_days: o, most_likely_days: m, pessimistic_days: p,
  cost_estimated: 0, is_milestone,
});
const dep = (predecessor, successor, dep_type = "FS", lag_days = 0) => ({
  predecessor, successor, dep_type, lag_days,
});

/* ----------------------------- Plantillas --------------------------------- */
const TEMPLATES = {
  data_collection: () => ({
    summary: "Proyecto de recolección/censo de datos en territorio rural.",
    tasks: [
      t("T1", "Diseño del instrumento de recolección", "Planeación", 5, 8, 14),
      t("T2", "Cartografía y muestreo del territorio", "Planeación", 3, 5, 9),
      t("T3", "Capacitación de brigadas de campo", "Preparación", 3, 5, 8),
      t("T4", "Levantamiento en campo", "Campo", 15, 22, 40),
      t("T5", "Digitalización y captura de datos", "Datos", 8, 12, 20),
      t("T6", "Validación y limpieza de datos", "Datos", 6, 10, 16),
      t("T7", "Informe de resultados y entrega", "Cierre", 3, 4, 7, true),
    ],
    dependencies: [
      dep("T1", "T2"), dep("T1", "T3"), dep("T3", "T4"), dep("T2", "T4"),
      dep("T4", "T5", "SS", 5), dep("T4", "T6"), dep("T5", "T6"), dep("T6", "T7"),
    ],
  }),
  software: () => ({
    summary: "Proyecto de desarrollo de plataforma/aplicación digital.",
    tasks: [
      t("T1", "Levantamiento de requerimientos", "Descubrimiento", 4, 6, 10),
      t("T2", "Diseño UX/UI y arquitectura", "Diseño", 5, 8, 13),
      t("T3", "Desarrollo backend y API", "Construcción", 12, 18, 30),
      t("T4", "Desarrollo frontend", "Construcción", 10, 16, 26),
      t("T5", "Modo offline y sincronización", "Construcción", 5, 8, 14),
      t("T6", "Pruebas y control de calidad", "Calidad", 5, 8, 13),
      t("T7", "Despliegue y capacitación", "Cierre", 3, 5, 8, true),
    ],
    dependencies: [
      dep("T1", "T2"), dep("T2", "T3"), dep("T2", "T4"), dep("T3", "T4", "SS", 3),
      dep("T3", "T5"), dep("T4", "T6"), dep("T5", "T6"), dep("T6", "T7"),
    ],
  }),
  training: () => ({
    summary: "Programa de capacitación/formación.",
    tasks: [
      t("T1", "Diagnóstico de necesidades de capacitación", "Planeación", 3, 5, 8),
      t("T2", "Diseño curricular y materiales", "Diseño", 5, 8, 13),
      t("T3", "Selección y convocatoria de participantes", "Logística", 3, 5, 9),
      t("T4", "Impartición de talleres", "Ejecución", 8, 12, 20),
      t("T5", "Evaluación de aprendizaje", "Evaluación", 3, 4, 7),
      t("T6", "Informe y certificación", "Cierre", 2, 3, 5, true),
    ],
    dependencies: [
      dep("T1", "T2"), dep("T1", "T3"), dep("T2", "T4"), dep("T3", "T4"),
      dep("T4", "T5", "SS", 2), dep("T5", "T6"),
    ],
  }),
  agri_field: () => ({
    summary: "Proyecto agrícola de campo (ciclo productivo).",
    tasks: [
      t("T1", "Análisis de suelo y planeación agronómica", "Planeación", 3, 5, 9),
      t("T2", "Preparación del terreno", "Preparación", 4, 7, 12),
      t("T3", "Instalación de sistema de riego", "Infraestructura", 5, 8, 15),
      t("T4", "Siembra", "Producción", 3, 5, 8),
      t("T5", "Manejo del cultivo (labores)", "Producción", 20, 30, 50),
      t("T6", "Cosecha", "Cierre", 5, 8, 14, true),
    ],
    dependencies: [
      dep("T1", "T2"), dep("T2", "T3"), dep("T2", "T4"), dep("T3", "T4", "FF", 0),
      dep("T4", "T5"), dep("T5", "T6"),
    ],
  }),
  generic: () => ({
    summary: "Proyecto genérico por fases.",
    tasks: [
      t("T1", "Definición de alcance y objetivos", "Inicio", 2, 4, 7),
      t("T2", "Planeación detallada y recursos", "Planeación", 3, 5, 9),
      t("T3", "Ejecución — fase 1", "Ejecución", 8, 14, 24),
      t("T4", "Ejecución — fase 2", "Ejecución", 8, 14, 24),
      t("T5", "Seguimiento y control de calidad", "Control", 4, 6, 10),
      t("T6", "Cierre y entrega", "Cierre", 2, 3, 5, true),
    ],
    dependencies: [
      dep("T1", "T2"), dep("T2", "T3"), dep("T3", "T4", "SS", 4),
      dep("T3", "T5"), dep("T4", "T5"), dep("T5", "T6"),
    ],
  }),
};

const expected = (task) =>
  (task.optimistic_days + 4 * task.most_likely_days + task.pessimistic_days) / 6;

function toEngineInput(tasks, deps) {
  return {
    tasks: tasks.map((x) => ({
      id: x.temp_id,
      optimistic: x.optimistic_days,
      most_likely: x.most_likely_days,
      pessimistic: x.pessimistic_days,
    })),
    dependencies: deps.map((d) => ({
      predecessor: d.predecessor,
      successor: d.successor,
      dep_type: d.dep_type,
      lag: d.lag_days,
    })),
  };
}

/**
 * Genera una EDT desde texto libre, la valida con el motor CPM y la escala al
 * horizonte detectado.
 * @returns {{summary, provider, detected_horizon_days, tasks, dependencies, preview, warnings}}
 */
export function breakdownIdea(rawText, targetHorizonDays = null) {
  const warnings = [];
  const domain = detectDomain(rawText);
  const template = TEMPLATES[domain]();
  let tasks = template.tasks.map((x) => ({ ...x }));
  const deps = template.dependencies.map((d) => ({ ...d }));

  const firstLine = rawText.trim().split("\n")[0].slice(0, 140);
  const summary = `${template.summary} (a partir de: “${firstLine}”)`;

  // Validación + preview con el motor CPM.
  const eng = toEngineInput(tasks, deps);
  let result = computeCPM(eng.tasks, eng.dependencies);

  // Escalado al horizonte.
  const horizon = targetHorizonDays ?? detectHorizonDays(rawText);
  if (horizon && result.project_duration > 0) {
    const factor = horizon / result.project_duration;
    if (Math.abs(factor - 1) > 0.05) {
      const before = result.project_duration;
      tasks = tasks.map((x) => ({
        ...x,
        optimistic_days: Math.round(Math.max(0.5, x.optimistic_days * factor) * 10) / 10,
        most_likely_days: Math.round(Math.max(0.5, x.most_likely_days * factor) * 10) / 10,
        pessimistic_days: Math.round(Math.max(0.5, x.pessimistic_days * factor) * 10) / 10,
      }));
      const eng2 = toEngineInput(tasks, deps);
      result = computeCPM(eng2.tasks, eng2.dependencies);
      const verb = factor < 1 ? "comprimió" : "expandió";
      warnings.push(
        `El plan base duraba ${Math.round(before)} días; se ${verb} al horizonte de ${Math.round(horizon)} días (factor ${factor.toFixed(2)}).`
      );
    }
  }

  return {
    summary,
    provider: "heuristic",
    detected_horizon_days: horizon,
    tasks,
    dependencies: deps,
    preview: {
      project_duration_days: result.project_duration,
      critical_path: result.critical_path,
      pert_std_dev: result.pert_std_dev,
    },
    warnings,
  };
}

/**
 * Convierte la EDT del asistente al formato que consume `CriticalPathView`.
 */
export function wbsToCriticalPathInput(breakdown) {
  const tasks = breakdown.tasks.map((x) => ({
    id: x.temp_id,
    name: x.name,
    duration: Math.round(expected(x) * 10) / 10,
    optimistic: x.optimistic_days,
    most_likely: x.most_likely_days,
    pessimistic: x.pessimistic_days,
  }));
  const deps = breakdown.dependencies.map((d) => ({
    predecessor: d.predecessor,
    successor: d.successor,
    dep_type: d.dep_type,
    lag: d.lag_days,
  }));
  return { tasks, deps };
}
