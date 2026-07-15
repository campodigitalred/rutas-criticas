/**
 * Motor CPM/PERT — port en JavaScript del núcleo Python (backend/app/cpm/engine.py).
 *
 * Permite recalcular la ruta crítica en el cliente (drag & drop del Gantt) y en
 * modo offline, sin depender del backend. El servidor revalida al sincronizar.
 *
 * Dependencias soportadas: FS, SS, FF, SF con lag/lead.
 */

const VALID_DEP_TYPES = new Set(["FS", "SS", "FF", "SF"]);

export class CPMError extends Error {}

function expectedDuration(task) {
  const { optimistic: o, most_likely: m, pessimistic: p, duration } = task;
  if (o != null && m != null && p != null) return (o + 4 * m + p) / 6;
  return duration ?? 0;
}

function variance(task) {
  const { optimistic: o, pessimistic: p } = task;
  if (o != null && p != null) return ((p - o) / 6) ** 2;
  return 0;
}

function topologicalOrder(taskIds, deps, succ) {
  const indegree = {};
  taskIds.forEach((id) => (indegree[id] = 0));
  deps.forEach((d) => (indegree[d.successor] += 1));
  const queue = taskIds.filter((id) => indegree[id] === 0).sort();
  const order = [];
  while (queue.length) {
    const node = queue.shift();
    order.push(node);
    (succ[node] || []).forEach((d) => {
      indegree[d.successor] -= 1;
      if (indegree[d.successor] === 0) queue.push(d.successor);
    });
  }
  if (order.length !== taskIds.length) {
    const remaining = taskIds.filter((t) => !order.includes(t));
    throw new CPMError(`El grafo de dependencias contiene un ciclo: ${remaining.join(", ")}`);
  }
  return order;
}

/**
 * @param {Array<{id,duration,optimistic?,most_likely?,pessimistic?}>} tasks
 * @param {Array<{predecessor,successor,dep_type?,lag?}>} dependencies
 * @returns {{project_duration, critical_path, pert_variance, pert_std_dev, tasks}}
 */
export function computeCPM(tasks, dependencies = []) {
  const taskMap = {};
  tasks.forEach((t) => (taskMap[t.id] = t));
  const taskIds = tasks.map((t) => t.id);

  const succ = {};
  const pred = {};
  taskIds.forEach((id) => {
    succ[id] = [];
    pred[id] = [];
  });
  dependencies.forEach((d) => {
    const dep = { dep_type: "FS", lag: 0, ...d };
    if (!VALID_DEP_TYPES.has(dep.dep_type)) {
      throw new CPMError(`Tipo de dependencia inválido: ${dep.dep_type}`);
    }
    if (!(dep.predecessor in taskMap)) throw new CPMError(`Predecesor inexistente: ${dep.predecessor}`);
    if (!(dep.successor in taskMap)) throw new CPMError(`Sucesor inexistente: ${dep.successor}`);
    succ[dep.predecessor].push(dep);
    pred[dep.successor].push(dep);
  });

  const order = topologicalOrder(taskIds, dependencies, succ);
  const dur = {};
  taskIds.forEach((id) => (dur[id] = expectedDuration(taskMap[id])));

  const es = {};
  const ef = {};
  taskIds.forEach((id) => {
    es[id] = 0;
    ef[id] = 0;
  });

  // Pase hacia adelante
  order.forEach((id) => {
    let start = 0;
    const dJ = dur[id];
    pred[id].forEach((dep) => {
      const p = dep.predecessor;
      let candidate;
      if (dep.dep_type === "FS") candidate = ef[p] + dep.lag;
      else if (dep.dep_type === "SS") candidate = es[p] + dep.lag;
      else if (dep.dep_type === "FF") candidate = ef[p] + dep.lag - dJ;
      else candidate = es[p] + dep.lag - dJ; // SF
      start = Math.max(start, candidate);
    });
    es[id] = start;
    ef[id] = start + dur[id];
  });

  const projectDuration = taskIds.length ? Math.max(...taskIds.map((id) => ef[id])) : 0;

  // Pase hacia atrás
  const lf = {};
  const ls = {};
  taskIds.forEach((id) => {
    lf[id] = projectDuration;
    ls[id] = projectDuration;
  });
  [...order].reverse().forEach((id) => {
    const dI = dur[id];
    const successors = succ[id];
    if (successors.length === 0) {
      lf[id] = projectDuration;
    } else {
      let finish = Infinity;
      successors.forEach((dep) => {
        const s = dep.successor;
        let candidate;
        if (dep.dep_type === "FS") candidate = ls[s] - dep.lag;
        else if (dep.dep_type === "SS") candidate = ls[s] - dep.lag + dI;
        else if (dep.dep_type === "FF") candidate = lf[s] - dep.lag;
        else candidate = lf[s] - dep.lag + dI; // SF
        finish = Math.min(finish, candidate);
      });
      lf[id] = finish;
    }
    ls[id] = lf[id] - dI;
  });

  // Holguras y resultados
  const eps = 1e-6;
  const results = {};
  taskIds.forEach((id) => {
    const totalSlack = ls[id] - es[id];
    let freeSlack = totalSlack;
    if (succ[id].length) {
      const candidates = succ[id].map((dep) => {
        const s = dep.successor;
        if (dep.dep_type === "FS" || dep.dep_type === "FF") return es[s] - ef[id] - dep.lag;
        return es[s] - es[id] - dep.lag;
      });
      freeSlack = Math.max(0, Math.min(...candidates));
    }
    freeSlack = Math.min(freeSlack, totalSlack);
    const round = (n) => Math.round(n * 1e6) / 1e6;
    results[id] = {
      duration: dur[id],
      early_start: round(es[id]),
      early_finish: round(ef[id]),
      late_start: round(ls[id]),
      late_finish: round(lf[id]),
      total_slack: round(totalSlack),
      free_slack: round(Math.max(0, freeSlack)),
      is_critical: Math.abs(totalSlack) < eps,
      pert_expected: round(expectedDuration(taskMap[id])),
      pert_variance: round(variance(taskMap[id])),
    };
  });

  const criticalPath = extractCriticalPath(order, results, pred, succ);
  const projVariance = criticalPath.reduce((acc, t) => acc + results[t].pert_variance, 0);

  return {
    project_duration: Math.round(projectDuration * 1e6) / 1e6,
    critical_path: criticalPath,
    pert_variance: Math.round(projVariance * 1e6) / 1e6,
    pert_std_dev: Math.round(Math.sqrt(projVariance) * 1e6) / 1e6,
    tasks: results,
  };
}

function extractCriticalPath(order, results, pred, succ) {
  const critical = order.filter((t) => results[t].is_critical);
  if (!critical.length) return [];
  const criticalSet = new Set(critical);
  const starts = critical.filter(
    (t) => !pred[t].some((d) => criticalSet.has(d.predecessor))
  );
  let current = starts.length ? starts[0] : critical[0];
  const path = [current];
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const next = succ[current]
      .filter((d) => criticalSet.has(d.successor) && !path.includes(d.successor))
      .map((d) => d.successor);
    if (!next.length) break;
    next.sort((a, b) => results[a].early_finish - results[b].early_finish);
    current = next[next.length - 1];
    path.push(current);
  }
  return path;
}
