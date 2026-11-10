type ChartRecord = Record<string, unknown>;

export interface TopologyLink extends ChartRecord {
  source: string | number;
  target: string | number;
}

export interface TopologyNode extends ChartRecord {
  id: string;
  name: string;
  children?: TopologyNode[];
}

interface TopologySeries extends ChartRecord {
  type: "tree" | "graph";
  data: TopologyNode[];
  links?: TopologyLink[];
}

function record(value: unknown): ChartRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as ChartRecord
    : {};
}

function escapeHtml(value: unknown): string {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[char]!);
}

// Collapse strongly connected components before ranking, so cycles remain
// visible without reversing or discarding their edges.
function graphRanks(ids: string[], outgoing: Map<string, string[]>): Map<string, number> {
  const incoming = new Map(ids.map((id) => [id, [] as string[]]));
  outgoing.forEach((targets, source) => {
    targets.forEach((target) => incoming.get(target)!.push(source));
  });
  const visited = new Set<string>();
  const finished: string[] = [];
  for (const id of ids) {
    const stack: Array<[string, boolean]> = [[id, false]];
    while (stack.length) {
      const [current, exit] = stack.pop()!;
      if (exit) {
        finished.push(current);
      } else if (!visited.has(current)) {
        visited.add(current);
        stack.push([current, true]);
        for (const target of outgoing.get(current)!) {
          if (!visited.has(target)) stack.push([target, false]);
        }
      }
    }
  }
  const component = new Map<string, number>();
  let count = 0;
  for (const id of finished.reverse()) {
    if (component.has(id)) continue;
    const stack = [id];
    component.set(id, count);
    while (stack.length) {
      for (const source of incoming.get(stack.pop()!)!) {
        if (!component.has(source)) {
          component.set(source, count);
          stack.push(source);
        }
      }
    }
    count += 1;
  }
  const successors = Array.from({ length: count }, () => new Set<number>());
  const indegree = Array<number>(count).fill(0);
  outgoing.forEach((targets, source) => {
    const from = component.get(source)!;
    targets.forEach((target) => {
      const to = component.get(target)!;
      if (from !== to && !successors[from].has(to)) {
        successors[from].add(to);
        indegree[to] += 1;
      }
    });
  });
  const ranks = Array<number>(count).fill(0);
  const queue = indegree.flatMap((degree, index) => degree === 0 ? [index] : []);
  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    for (const target of successors[current]) {
      ranks[target] = Math.max(ranks[target], ranks[current] + 1);
      if (--indegree[target] === 0) queue.push(target);
    }
  }
  return new Map(ids.map((id) => [id, ranks[component.get(id)!]]));
}

export function buildTopologySeries(
  sourceNodes: readonly ChartRecord[],
  sourceLinks: readonly TopologyLink[],
  presentation: { label?: ChartRecord; lineStyle?: ChartRecord } = {},
): TopologySeries {
  const nodes: TopologyNode[] = sourceNodes.map((node, index) => ({
    ...node,
    id: String(node.id ?? node.name ?? index),
    name: String(node.name ?? node.id ?? index),
  }));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const byName = new Map<string, string[]>();
  nodes.forEach((node) => {
    const matches = byName.get(node.name) ?? [];
    matches.push(node.id);
    byName.set(node.name, matches);
  });
  const resolve = (endpoint: string | number): string => {
    if (typeof endpoint === "number") return nodes[endpoint]?.id ?? String(endpoint);
    if (byId.has(endpoint)) return endpoint;
    const matches = byName.get(endpoint);
    return matches?.length === 1 ? matches[0] : endpoint;
  };
  const links: Array<TopologyLink & { source: string; target: string }> = sourceLinks.map((link) => ({
    ...link, source: resolve(link.source), target: resolve(link.target),
  }));
  const outgoing = new Map(nodes.map((node) => [node.id, [] as string[]]));
  const parents = new Map(nodes.map((node) => [node.id, [] as typeof links]));
  let complete = byId.size === nodes.length;
  for (const link of links) {
    if (!byId.has(link.source) || !byId.has(link.target)) {
      complete = false;
      continue;
    }
    outgoing.get(link.source)!.push(link.target);
    parents.get(link.target)!.push(link);
  }
  if (!complete) {
    console.warn("Topology contains duplicate IDs or unresolved endpoints; preserving it as a static graph.");
  }
  const roots = nodes.filter((node) => parents.get(node.id)!.length === 0);
  const queue = roots.map((node) => node.id);
  const indegree = new Map(nodes.map((node) => [node.id, parents.get(node.id)!.length]));
  for (let index = 0; index < queue.length; index += 1) {
    for (const target of outgoing.get(queue[index])!) {
      const remaining = indegree.get(target)! - 1;
      indegree.set(target, remaining);
      if (remaining === 0) queue.push(target);
    }
  }
  const common = {
    animation: false,
    roam: true,
    symbol: "circle",
    symbolSize: 24,
    left: 150,
    right: 150,
    top: 24,
    bottom: 36,
    label: { show: true, width: 120, overflow: "truncate", ...presentation.label },
    lineStyle: presentation.lineStyle,
    emphasis: { focus: "adjacency" },
  };
  if (
    complete && roots.length === 1 && queue.length === nodes.length
    && nodes.every((node) => parents.get(node.id)!.length <= 1)
  ) {
    for (const link of links) {
      const child = byId.get(link.target)!;
      const relation = link.value ?? link.name ?? record(link.label).formatter;
      child.relation = { ...link };
      child.lineStyle = { ...record(link.lineStyle), ...record(child.lineStyle) };
      if (typeof relation === "string" || typeof relation === "number") {
        child.tooltip = {
          formatter: `${escapeHtml(child.name)}${child.value == null ? "" : `<br/>${escapeHtml(child.value)}`}<br/>关系：${escapeHtml(relation)}`,
          ...record(child.tooltip),
        };
      }
      const parent = byId.get(link.source)!;
      (parent.children ??= []).push(child);
    }
    return {
      ...common,
      type: "tree",
      layout: "orthogonal",
      orient: "LR",
      edgeShape: "polyline",
      edgeForkPosition: "50%",
      initialTreeDepth: -1,
      expandAndCollapse: true,
      label: { ...common.label, position: "left", align: "right", verticalAlign: "middle" },
      leaves: { label: { position: "right", align: "left" } },
      emphasis: { focus: "descendant" },
      data: roots,
    };
  }
  const ranks = graphRanks([...byId.keys()], outgoing);
  const columns = new Map<number, TopologyNode[]>();
  nodes.forEach((node) => {
    const rank = ranks.get(node.id)!;
    const column = columns.get(rank) ?? [];
    column.push(node);
    columns.set(rank, column);
  });
  columns.forEach((column, rank) => column.forEach((node, index) => {
    node.x = rank * 240;
    node.y = (index - (column.length - 1) / 2) * 90;
  }));
  return {
    ...common,
    type: "graph",
    layout: "none",
    preserveAspect: "contain",
    draggable: false,
    edgeSymbol: ["none", "arrow"],
    edgeSymbolSize: [0, 8],
    label: { ...common.label, position: "bottom" },
    lineStyle: { curveness: 0.15, ...presentation.lineStyle },
    data: nodes,
    links,
  };
}

const TOPOLOGY_TITLE = /拓扑|依赖|链路|上下游|topology|dependency/i;

/** Upgrade named topology charts, not unrelated graph/force visualizations. */
export function normalizeTopologyOption(option: ChartRecord): ChartRecord {
  const titles = Array.isArray(option.title) ? option.title : [option.title];
  const topologyTitle = titles.some((title) => TOPOLOGY_TITLE.test(String(record(title).text ?? "")));
  const items = Array.isArray(option.series) ? option.series : [option.series];
  let changed = false;
  const series = items.map((value) => {
    const item = record(value);
    if (
      item.type !== "graph" || item.layout !== "force"
      || !(topologyTitle || TOPOLOGY_TITLE.test(String(item.name ?? "")))
    ) return value;
    const nodes = item.data ?? item.nodes;
    const links = item.links ?? item.edges ?? [];
    if (
      !Array.isArray(nodes) || !nodes.every((node) => Object.keys(record(node)).length > 0)
      || !Array.isArray(links) || !links.every((link) => {
        const edge = record(link);
        return ["string", "number"].includes(typeof edge.source)
          && ["string", "number"].includes(typeof edge.target);
      })
    ) {
      console.warn("Cannot normalize topology chart: expected node objects and source/target links.");
      return value;
    }
    const { force, nodes: _nodes, data, links: _links, edges, layout, ...appearance } = item;
    const next = buildTopologySeries(nodes, links);
    changed = true;
    return {
      ...appearance,
      ...next,
      label: { ...record(item.label), ...record(next.label) },
      lineStyle: { ...record(next.lineStyle), ...record(item.lineStyle) },
    };
  });
  return changed ? { ...option, series } : option;
}
