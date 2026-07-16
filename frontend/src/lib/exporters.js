/**
 * Exportadores — espejo en JavaScript de backend/app/reporting/exporters.py.
 * Genera CSV, MS Project (MSPDI XML) y Primavera P6 (XER) en el cliente
 * (funciona offline). Incluye utilidades de descarga y exportación a PNG.
 *
 * La generación de texto es determinista y equivalente al backend.
 */
import { computeCPM } from "./cpm.js";

const HOURS_PER_DAY = 8;
const MSP_TYPE = { FF: 0, FS: 1, SF: 2, SS: 3 };
const P6_TYPE = { FS: "PR_FS", SS: "PR_SS", FF: "PR_FF", SF: "PR_SF" };

const num = (x) => (Number.isInteger(x) ? x : Math.round(x * 100) / 100);

function prepare(payload) {
  const rawTasks = payload.tasks || [];
  if (!rawTasks.length) throw new Error("No hay tareas para exportar.");
  const engTasks = rawTasks.map((t) => ({
    id: String(t.id),
    duration: Number(t.duration || 0),
    optimistic: t.optimistic ?? null,
    most_likely: t.most_likely ?? null,
    pessimistic: t.pessimistic ?? null,
  }));
  const deps = (payload.dependencies || []).map((d) => ({
    predecessor: String(d.predecessor),
    successor: String(d.successor),
    dep_type: d.dep_type || "FS",
    lag: Number(d.lag ?? d.lag_days ?? 0),
  }));
  const result = computeCPM(engTasks, deps);
  const meta = {};
  rawTasks.forEach((t) => {
    meta[String(t.id)] = {
      name: t.name ?? String(t.id),
      cost: Number(t.planned_cost ?? t.cost ?? 0),
      progress: Number(t.progress_pct ?? 0),
      milestone: Boolean(t.is_milestone) || Number(t.duration || 0) === 0,
    };
  });
  const preds = {};
  Object.keys(result.tasks).forEach((id) => (preds[id] = []));
  deps.forEach((d) => preds[d.successor].push(d));
  return { result, meta, preds, order: Object.keys(result.tasks), deps };
}

/* --------------------------------- CSV ------------------------------------ */
export function toCsv(payload) {
  const { result, meta, preds, order } = prepare(payload);
  const esc = (v) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = [[
    "ID", "Tarea", "Duración (d)", "Inicio temprano (ES)", "Fin temprano (EF)",
    "Inicio tardío (LS)", "Fin tardío (LF)", "Holgura total", "Crítica",
    "Predecesoras", "Avance %", "Costo planeado",
  ]];
  order.forEach((id) => {
    const tr = result.tasks[id];
    const m = meta[id];
    const p = preds[id]
      .map((d) => `${d.predecessor}(${d.dep_type}${d.lag ? "+" + num(d.lag) : ""})`)
      .join("; ");
    rows.push([
      id, m.name, num(tr.duration), num(tr.early_start), num(tr.early_finish),
      num(tr.late_start), num(tr.late_finish), num(tr.total_slack),
      tr.is_critical ? "Sí" : "No", p, num(m.progress), num(m.cost),
    ]);
  });
  return rows.map((r) => r.map(esc).join(",")).join("\r\n") + "\r\n";
}

/* ----------------------------- MS Project XML ----------------------------- */
function xmlEsc(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}
function pad(n) {
  return String(n).padStart(2, "0");
}
function iso(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
function addDays(base, days) {
  const d = new Date(base.getTime());
  d.setDate(d.getDate() + Math.round(days));
  return d;
}
function isoDuration(days) {
  const totalMin = Math.round(days * HOURS_PER_DAY * 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return `PT${h}H${m}M0S`;
}

export function toMsProjectXml(payload) {
  const { result, meta, preds, order } = prepare(payload);
  const start = payload.start_date ? new Date(payload.start_date + "T00:00:00") : new Date(2025, 0, 6);
  const uid = {};
  order.forEach((id, i) => (uid[id] = i + 1));
  const parts = [];
  parts.push('<?xml version="1.0" encoding="utf-8"?>');
  parts.push('<Project xmlns="http://schemas.microsoft.com/project">');
  parts.push(`<Name>${xmlEsc(payload.project_name || "Campo Crítico")}</Name>`);
  parts.push(`<StartDate>${iso(start)}</StartDate>`);
  parts.push("<DurationFormat>7</DurationFormat><CalendarUID>1</CalendarUID>");
  parts.push("<Tasks>");
  order.forEach((id, i) => {
    const tr = result.tasks[id];
    const m = meta[id];
    parts.push("<Task>");
    parts.push(`<UID>${uid[id]}</UID><ID>${i + 1}</ID>`);
    parts.push(`<Name>${xmlEsc(m.name)}</Name>`);
    parts.push("<Active>1</Active><Manual>0</Manual>");
    parts.push(`<Duration>${isoDuration(tr.duration)}</Duration><DurationFormat>7</DurationFormat>`);
    parts.push(`<Start>${iso(addDays(start, tr.early_start))}</Start>`);
    parts.push(`<Finish>${iso(addDays(start, tr.early_finish))}</Finish>`);
    parts.push(`<Milestone>${m.milestone ? 1 : 0}</Milestone>`);
    parts.push(`<PercentComplete>${Math.round(m.progress)}</PercentComplete>`);
    parts.push(`<Critical>${tr.is_critical ? 1 : 0}</Critical>`);
    parts.push(`<TotalSlack>${isoDuration(tr.total_slack)}</TotalSlack>`);
    preds[id].forEach((d) => {
      parts.push("<PredecessorLink>");
      parts.push(`<PredecessorUID>${uid[d.predecessor]}</PredecessorUID>`);
      parts.push(`<Type>${MSP_TYPE[d.dep_type] ?? 1}</Type>`);
      parts.push(`<LinkLag>${Math.round(d.lag * HOURS_PER_DAY * 60 * 10)}</LinkLag><LagFormat>7</LagFormat>`);
      parts.push("</PredecessorLink>");
    });
    parts.push("</Task>");
  });
  parts.push("</Tasks></Project>");
  return parts.join("");
}

/* ------------------------------ Primavera XER ----------------------------- */
function xerDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function toP6Xer(payload) {
  const { result, meta, order, deps } = prepare(payload);
  const start = payload.start_date ? new Date(payload.start_date + "T00:00:00") : new Date(2025, 0, 6);
  const now = new Date(2025, 0, 6);
  const projId = payload.project_id || "CC1";
  const projName = payload.project_name || "Campo Crítico";
  const lines = [];
  lines.push(["ERMHDR", "18.8", xerDate(now), "Project", "CampoDigital", "CampoDigital", "USD", "Campo Crítico Export"].join("\t"));

  const table = (name, fields, rows) => {
    lines.push(`%T\t${name}`);
    lines.push("%F\t" + fields.join("\t"));
    rows.forEach((r) => lines.push("%R\t" + r.map((v) => (v == null ? "" : String(v))).join("\t")));
  };

  table("PROJECT", ["proj_id", "proj_short_name", "plan_start_date", "last_recalc_date"],
    [[projId, projName, xerDate(start), xerDate(now)]]);

  const taskRows = order.map((id) => {
    const tr = result.tasks[id];
    const m = meta[id];
    return [
      id, projId, id, m.name, m.milestone ? "TT_Mile" : "TT_Task",
      num(tr.duration * HOURS_PER_DAY), num(m.progress),
      xerDate(addDays(start, tr.early_start)), xerDate(addDays(start, tr.early_finish)),
      num(tr.total_slack * HOURS_PER_DAY), tr.is_critical ? "Y" : "N",
    ];
  });
  table("TASK",
    ["task_id", "proj_id", "task_code", "task_name", "task_type", "target_drtn_hr_cnt",
     "phys_complete_pct", "early_start_date", "early_end_date", "total_float_hr_cnt", "driving_path_flag"],
    taskRows);

  const predRows = deps.map((d, i) => [
    i + 1, d.successor, d.predecessor, projId, P6_TYPE[d.dep_type] || "PR_FS", num(d.lag * HOURS_PER_DAY),
  ]);
  table("TASKPRED", ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_type", "lag_hr_cnt"], predRows);

  lines.push("%E");
  return lines.join("\n") + "\n";
}

/* --------------------------- Utilidades de navegador ---------------------- */
export function downloadText(filename, text, mime = "text/plain") {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Exporta un elemento <svg> a PNG (data URL) y lo descarga. */
export function exportSvgToPng(svgEl, filename = "diagrama.png", scale = 2) {
  return new Promise((resolve, reject) => {
    const rect = svgEl.getBoundingClientRect();
    const w = rect.width || svgEl.viewBox.baseVal.width || 800;
    const h = rect.height || svgEl.viewBox.baseVal.height || 400;
    const clone = svgEl.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const svgStr = new XMLSerializer().serializeToString(clone);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = w * scale;
      canvas.height = h * scale;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0, w, h);
      canvas.toBlob((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
        resolve();
      }, "image/png");
    };
    img.onerror = reject;
    img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svgStr)));
  });
}
