/**
 * DashboardView — Dashboard de Control (EVM) y Exportación (Módulo E).
 *
 * Muestra las métricas de Valor Ganado (EVM) y la curva S del proyecto, y ofrece
 * la exportación a formatos profesionales: CSV (Excel), MS Project (MSPDI XML),
 * Primavera P6 (XER), PNG del gráfico e impresión a PDF.
 *
 * Usa los núcleos deterministas ../lib/evm.js y ../lib/exporters.js (paridad
 * exacta con el backend), por lo que funciona en el cliente / offline.
 */
import React, { useMemo, useRef, useState } from "react";
import { EVM_HEALTH_META, computeEVM } from "../lib/evm.js";
import {
  downloadText,
  exportSvgToPng,
  toCsv,
  toMsProjectXml,
  toP6Xer,
} from "../lib/exporters.js";

const DAY_RATE = 1000; // costo planeado por día (demo)

/** Inicializa costos: planeado por duración, real por avance con 10% de sobrecosto. */
function initCosts(tasks) {
  const c = {};
  tasks.forEach((t) => {
    const planned = Math.round((t.duration || 0) * DAY_RATE);
    const actual = Math.round((planned * ((t.progress_pct || 0) / 100)) * 1.1);
    c[t.id] = { planned, actual };
  });
  return c;
}

function money(x) {
  return x == null ? "—" : `$${Number(x).toLocaleString()}`;
}

function IndexCard({ label, value, good }) {
  const color =
    value == null
      ? "var(--cc-gray-500)"
      : value >= 0.95
        ? "var(--cc-green-600)"
        : value >= 0.85
          ? "var(--cc-slack)"
          : "var(--cc-critical)";
  return (
    <div className="cc-stat">
      <div className="label">{label}</div>
      <div className="value" style={{ color }}>{value == null ? "—" : value.toFixed(2)}</div>
    </div>
  );
}

function SCurve({ evm, svgRef }) {
  const W = 620;
  const H = 220;
  const pad = { l: 56, r: 16, t: 16, b: 28 };
  const curve = evm.pv_curve;
  const maxDay = curve.length ? curve[curve.length - 1].day : 1;
  const maxCost = Math.max(evm.bac, evm.ac || 0, evm.ev || 0, 1);
  const x = (d) => pad.l + (d / (maxDay || 1)) * (W - pad.l - pad.r);
  const y = (c) => H - pad.b - (c / maxCost) * (H - pad.t - pad.b);

  const pvPath = curve.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.day)},${y(p.pv)}`).join(" ");
  const cut = curve.find((p) => p.ev != null);

  return (
    <svg ref={svgRef} width="100%" viewBox={`0 0 ${W} ${H}`} className="cc-scurve">
      <rect x="0" y="0" width={W} height={H} fill="#ffffff" />
      {/* BAC */}
      <line x1={pad.l} y1={y(evm.bac)} x2={W - pad.r} y2={y(evm.bac)} stroke="var(--cc-gray-500)" strokeDasharray="4 3" strokeWidth="1" />
      <text x={pad.l + 2} y={y(evm.bac) - 4} fontSize="10" fill="var(--cc-gray-500)">BAC {money(evm.bac)}</text>
      {/* Ejes */}
      <line x1={pad.l} y1={pad.t} x2={pad.l} y2={H - pad.b} stroke="#d7dee7" />
      <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} stroke="#d7dee7" />
      {/* Curva PV */}
      <path d={pvPath} fill="none" stroke="var(--cc-blue-600)" strokeWidth="2" />
      {/* Corte a la fecha */}
      {cut && (
        <g>
          <line x1={x(cut.day)} y1={pad.t} x2={x(cut.day)} y2={H - pad.b} stroke="var(--cc-gray-900)" strokeDasharray="3 3" strokeWidth="1" />
          <circle cx={x(cut.day)} cy={y(evm.pv)} r="4" fill="var(--cc-blue-600)" />
          <circle cx={x(cut.day)} cy={y(evm.ev)} r="4" fill="var(--cc-green-600)" />
          <circle cx={x(cut.day)} cy={y(evm.ac)} r="4" fill="var(--cc-critical)" />
        </g>
      )}
      <text x={W - pad.r} y={H - pad.b + 18} fontSize="10" fill="var(--cc-gray-500)" textAnchor="end">día {maxDay}</text>
      {/* Leyenda */}
      <g fontSize="10">
        <circle cx={pad.l + 6} cy={pad.t + 4} r="4" fill="var(--cc-blue-600)" /><text x={pad.l + 14} y={pad.t + 7} fill="var(--cc-gray-500)">PV</text>
        <circle cx={pad.l + 46} cy={pad.t + 4} r="4" fill="var(--cc-green-600)" /><text x={pad.l + 54} y={pad.t + 7} fill="var(--cc-gray-500)">EV</text>
        <circle cx={pad.l + 86} cy={pad.t + 4} r="4" fill="var(--cc-critical)" /><text x={pad.l + 94} y={pad.t + 7} fill="var(--cc-gray-500)">AC</text>
      </g>
    </svg>
  );
}

export default function DashboardView({ tasks, deps }) {
  const [asOfDay, setAsOfDay] = useState("");
  const [costs, setCosts] = useState(() => initCosts(tasks));
  const svgRef = useRef(null);

  const evmTasks = useMemo(
    () =>
      tasks.map((t) => ({
        id: t.id,
        duration: t.duration,
        planned_cost: costs[t.id]?.planned ?? 0,
        progress_pct: t.progress_pct ?? 0,
        actual_cost: costs[t.id]?.actual ?? 0,
      })),
    [tasks, costs]
  );

  const evm = useMemo(
    () => computeEVM(evmTasks, deps, asOfDay === "" ? null : Number(asOfDay)),
    [evmTasks, deps, asOfDay]
  );

  const meta = EVM_HEALTH_META[evm.health] ?? EVM_HEALTH_META.not_started;

  function setCost(id, field, value) {
    setCosts((prev) => ({ ...prev, [id]: { ...prev[id], [field]: Number(value) } }));
  }

  /** Construye el payload de exportación con costos y nombres. */
  function exportPayload() {
    return {
      project_name: "Campo Crítico",
      project_id: "CC1",
      tasks: tasks.map((t) => ({
        id: t.id,
        name: t.name ?? t.id,
        duration: t.duration,
        optimistic: t.optimistic,
        most_likely: t.most_likely,
        pessimistic: t.pessimistic,
        planned_cost: costs[t.id]?.planned ?? 0,
        progress_pct: t.progress_pct ?? 0,
        is_milestone: (t.duration ?? 0) === 0,
      })),
      dependencies: deps,
    };
  }

  return (
    <div>
      <div className="cc-exec-header">
        <div className="cc-exec-health">
          <span className="cc-health" style={{ background: meta.color }}>{meta.label}</span>
          <div><div className="cc-exec-metric-label">Avance (EV/BAC)</div><div className="cc-exec-metric-value">{evm.percent_complete}%</div></div>
          <div><div className="cc-exec-metric-label">Gastado (AC/BAC)</div><div className="cc-exec-metric-value">{evm.percent_spent}%</div></div>
        </div>
        <div className="cc-exec-asof">
          <label>Día de corte:</label>
          <input type="number" min="0" placeholder="—" className="cc-input" style={{ width: 80 }} value={asOfDay} onChange={(e) => setAsOfDay(e.target.value)} />
        </div>
      </div>

      {/* Toolbar de exportación */}
      <div className="cc-export-bar">
        <span>Exportar:</span>
        <button className="cc-btn ghost" onClick={() => downloadText("campo-critico.csv", toCsv(exportPayload()), "text/csv")}>CSV / Excel</button>
        <button className="cc-btn ghost" onClick={() => downloadText("campo-critico.xml", toMsProjectXml(exportPayload()), "application/xml")}>MS Project</button>
        <button className="cc-btn ghost" onClick={() => downloadText("campo-critico.xer", toP6Xer(exportPayload()), "text/plain")}>Primavera P6</button>
        <button className="cc-btn ghost" onClick={() => svgRef.current && exportSvgToPng(svgRef.current, "curva-s.png")}>PNG (gráfico)</button>
        <button className="cc-btn ghost" onClick={() => window.print()}>PDF (imprimir)</button>
      </div>

      {/* Tarjetas de valor */}
      <div className="cc-stats" style={{ marginBottom: 8 }}>
        <div className="cc-stat"><div className="label">BAC (presupuesto)</div><div className="value" style={{ fontSize: 18 }}>{money(evm.bac)}</div></div>
        <div className="cc-stat"><div className="label">PV (planeado)</div><div className="value" style={{ fontSize: 18 }}>{money(evm.pv)}</div></div>
        <div className="cc-stat"><div className="label">EV (ganado)</div><div className="value" style={{ fontSize: 18, color: "var(--cc-green-600)" }}>{money(evm.ev)}</div></div>
        <div className="cc-stat"><div className="label">AC (real)</div><div className="value" style={{ fontSize: 18, color: "var(--cc-critical)" }}>{money(evm.ac)}</div></div>
        <IndexCard label="SPI (cronograma)" value={evm.spi} />
        <IndexCard label="CPI (costo)" value={evm.cpi} />
        <div className="cc-stat"><div className="label">EAC (proyección)</div><div className="value" style={{ fontSize: 18 }}>{money(evm.eac)}</div></div>
        <div className={`cc-stat ${evm.vac != null && evm.vac < 0 ? "critical" : ""}`}>
          <div className="label">VAC (variación final)</div>
          <div className="value" style={{ fontSize: 18 }}>{money(evm.vac)}</div>
        </div>
      </div>

      <h3 className="cc-section-title">Curva S — Valor planeado (PV) vs. ganado (EV) y costo real (AC)</h3>
      <SCurve evm={evm} svgRef={svgRef} />
      {asOfDay === "" && (
        <p className="cc-hint" style={{ marginTop: 0 }}>Indica un “día de corte” para calcular PV, SPI y el punto EV/AC en la curva.</p>
      )}

      {/* Tabla de costos editable */}
      <h3 className="cc-section-title">Costos por tarea</h3>
      <table className="cc-edt-table">
        <thead>
          <tr><th>Tarea</th><th>Avance</th><th>Costo planeado</th><th>Costo real</th></tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <tr key={t.id}>
              <td><strong>{t.id}</strong> · {t.name ?? t.id}</td>
              <td>{t.progress_pct ?? 0}%</td>
              <td>$<input type="number" min="0" step="100" value={costs[t.id]?.planned ?? 0} onChange={(e) => setCost(t.id, "planned", e.target.value)} style={{ width: 90 }} /></td>
              <td>$<input type="number" min="0" step="100" value={costs[t.id]?.actual ?? 0} onChange={(e) => setCost(t.id, "actual", e.target.value)} style={{ width: 90 }} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="cc-hint">
        Edita los costos planeado/real para reflejar el estado del proyecto; las métricas EVM, la
        salud y la curva S se recalculan al instante. Los exportadores incluyen los costos.
      </p>
    </div>
  );
}
