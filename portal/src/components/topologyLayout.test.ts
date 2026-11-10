import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTopologySeries,
  normalizeTopologyOption,
  type TopologyNode,
} from "./topologyLayout.ts";

const nodes = (...ids: string[]) => ids.map((id) => ({ id, name: id }));
const edge = (source: string, target: string) => ({ source, target });

test("a rooted topology uses an expanded left-to-right tree without mutating its input", () => {
  const input = [
    { id: "app", name: "Application" },
    { id: "db", name: "Database", itemStyle: { color: "#ef4444" }, symbolSize: 42, value: 7 },
  ];
  const links = [{
    ...edge("app", "db"), value: "<depends on>",
    lineStyle: { width: 3, opacity: 0.8 },
  }];
  const before = JSON.stringify({ input, links });
  const series = buildTopologySeries(input, links);
  assert.equal(series.type, "tree");
  assert.equal(series.orient, "LR");
  assert.equal(series.layout, "orthogonal");
  assert.equal(series.initialTreeDepth, -1);
  assert.equal(series.expandAndCollapse, true);
  assert.equal(series.animation, false);
  assert.equal(series.roam, true);
  assert.equal(series.force, undefined);
  const child = series.data[0].children![0];
  assert.equal(child.id, "db");
  assert.equal(child.value, 7);
  assert.equal(child.symbolSize, 42);
  assert.deepEqual(child.itemStyle, { color: "#ef4444" });
  assert.deepEqual(child.lineStyle, links[0].lineStyle);
  assert.deepEqual(child.relation, links[0]);
  assert.match(String((child.tooltip as Record<string, unknown>).formatter), /&lt;depends on&gt;/);
  assert.equal(JSON.stringify({ input, links }), before);
});

test("the actual upstream root wins over node order or display names", () => {
  const series = buildTopologySeries(nodes("db", "service", "app"), [
    edge("service", "db"), edge("app", "service"),
  ]);
  assert.equal(series.type, "tree");
  assert.equal(series.data[0].id, "app");
  assert.equal(series.data[0].children![0].id, "service");
  assert.equal(series.data[0].children![0].children![0].id, "db");
});

test("numeric edge indexes and unique node-name references resolve to real IDs", () => {
  const series = buildTopologySeries([
    { id: "10", name: "Application" }, { id: "20", name: "Service" }, { id: "30", name: "Database" },
  ], [{ source: 0, target: 1 }, { source: "Service", target: "Database" }]);
  assert.equal(series.type, "tree");
  assert.equal(series.data[0].children![0].children![0].id, "30");
});

test("multi-parent DAGs keep every node and edge in fixed longest-path layers", () => {
  const input = nodes("app", "short", "long", "middle", "shared");
  const links = [
    edge("app", "short"), edge("app", "long"), edge("long", "middle"),
    edge("middle", "shared"), edge("short", "shared"),
  ];
  const series = buildTopologySeries(input, links);
  assert.equal(series.type, "graph");
  assert.equal(series.layout, "none");
  assert.equal(series.preserveAspect, "contain");
  assert.equal(series.draggable, false);
  assert.equal(series.force, undefined);
  assert.deepEqual(series.edgeSymbol, ["none", "arrow"]);
  assert.equal(series.data.length, input.length);
  assert.deepEqual(series.links, links);
  const byId = new Map(series.data.map((node) => [node.id, node]));
  for (const link of links) {
    assert.ok(Number(byId.get(link.source)!.x) < Number(byId.get(link.target)!.x));
  }
  assert.deepEqual(buildTopologySeries(input, links), series);
});

test("cycles share a layer, and upstream/downstream edges still advance horizontally", () => {
  const input = nodes("entry", "a", "b", "exit");
  const links = [edge("entry", "a"), edge("a", "b"), edge("b", "a"), edge("b", "exit")];
  const series = buildTopologySeries(input, links);
  assert.equal(series.type, "graph");
  assert.deepEqual(series.links, links);
  const byId = new Map(series.data.map((node) => [node.id, node]));
  assert.equal(byId.get("a")!.x, byId.get("b")!.x);
  assert.notEqual(byId.get("a")!.y, byId.get("b")!.y);
  assert.ok(Number(byId.get("entry")!.x) < Number(byId.get("a")!.x));
  assert.ok(Number(byId.get("b")!.x) < Number(byId.get("exit")!.x));
});

test("all three-node graph shapes advance every non-cyclic edge to a later layer", () => {
  const ids = ["a", "b", "c"];
  const candidates = ids.flatMap((source) => ids.filter((target) => target !== source).map((target) => edge(source, target)));
  for (let mask = 0; mask < 2 ** candidates.length; mask += 1) {
    const links = candidates.filter((_, index) => mask & (1 << index));
    const series = buildTopologySeries(nodes(...ids), links);
    if (series.type === "tree") continue;
    const reachable = ids.map((source) => ids.map((target) => source === target || links.some((link) => link.source === source && link.target === target)));
    for (let k = 0; k < ids.length; k += 1) {
      for (let i = 0; i < ids.length; i += 1) {
        for (let j = 0; j < ids.length; j += 1) {
          reachable[i][j] ||= reachable[i][k] && reachable[k][j];
        }
      }
    }
    const positions = new Map(series.data.map((node) => [node.id, Number(node.x)]));
    for (const link of links) {
      if (reachable[ids.indexOf(link.target)][ids.indexOf(link.source)]) {
        assert.equal(positions.get(link.source), positions.get(link.target));
      } else {
        assert.ok(positions.get(link.source)! < positions.get(link.target)!);
      }
    }
  }
});

test("rootless cycles, self-loops and parallel relationships are not coerced into trees", () => {
  for (const [input, links] of [
    [nodes("a", "b"), [edge("a", "b"), edge("b", "a")]],
    [nodes("a"), [edge("a", "a")]],
    [nodes("a", "b"), [{ ...edge("a", "b"), value: "owns" }, { ...edge("a", "b"), value: "uses" }]],
  ] as const) {
    const series = buildTopologySeries(input, links);
    assert.equal(series.type, "graph");
    assert.deepEqual(series.links, links);
    assert.equal(series.data.length, input.length);
  }
});

test("disconnected components stay separate without invented root nodes or edges", () => {
  const input = nodes("a", "b", "c", "isolated");
  const links = [edge("a", "b"), edge("a", "c")];
  const series = buildTopologySeries(input, links);
  assert.equal(series.type, "graph");
  assert.deepEqual(series.data.map((node) => node.id), input.map((node) => node.id));
  assert.deepEqual(series.links, links);
});

test("empty, singleton and deeply nested inputs terminate without recursive traversal", () => {
  assert.deepEqual(buildTopologySeries([], []).data, []);
  const singleton = buildTopologySeries(nodes("a"), []);
  assert.equal(singleton.type, "tree");
  const size = 2000;
  const input = nodes(...Array.from({ length: size }, (_, i) => String(i)));
  const links = input.slice(1).map((node, i) => edge(String(i), node.id));
  let node: TopologyNode | undefined = buildTopologySeries(input, links).data[0];
  let count = 0;
  while (node) {
    count += 1;
    node = node.children?.[0];
  }
  assert.equal(count, size);
});

test("incomplete topology retains unresolved links and logs the data problem", (t) => {
  const warn = t.mock.method(console, "warn", () => {});
  const links = [edge("a", "missing")];
  const series = buildTopologySeries(nodes("a"), links);
  assert.equal(series.type, "graph");
  assert.deepEqual(series.links, links);
  assert.equal(warn.mock.callCount(), 1);
});

test("named force topology code blocks are upgraded without altering unrelated series", () => {
  const bars = { type: "bar", data: [1, 2] };
  const option = {
    title: [{ text: "Application topology" }],
    tooltip: { trigger: "item" },
    series: [
      { type: "graph", layout: "force", nodes: nodes("a", "b"), edges: [edge("a", "b")], label: { color: "red" } },
      bars,
    ],
  };
  const before = JSON.stringify(option);
  const result = normalizeTopologyOption(option);
  assert.ok(Array.isArray(result.series));
  const first = result.series[0] as Record<string, unknown>;
  assert.equal(first.type, "tree");
  assert.equal(first.orient, "LR");
  assert.equal(first.force, undefined);
  assert.equal(first.nodes, undefined);
  assert.equal((first.label as Record<string, unknown>).color, "red");
  assert.equal(result.series[1], bars);
  assert.equal(result.tooltip, option.tooltip);
  assert.equal(JSON.stringify(option), before);
});

test("series names also identify topology in single-series shorthand", () => {
  const option = { series: { name: "服务依赖", type: "graph", layout: "force", data: nodes("a"), links: [] } };
  const result = normalizeTopologyOption(option);
  assert.ok(Array.isArray(result.series));
  assert.equal(result.series[0].type, "tree");
});

test("unrelated force diagrams, explicit fixed coordinates and existing trees are untouched", () => {
  for (const option of [
    { title: { text: "关系社群" }, series: [{ type: "graph", layout: "force", data: nodes("a") }] },
    { title: { text: "网络拓扑" }, series: [{ type: "graph", layout: "none", data: nodes("a") }] },
    { title: { text: "网络拓扑" }, series: [{ type: "tree", orient: "TB", data: nodes("a") }] },
  ]) {
    assert.equal(normalizeTopologyOption(option), option);
  }
});

test("unsupported graph data is reported and left unchanged", (t) => {
  const warn = t.mock.method(console, "warn", () => {});
  const option = { title: { text: "网络拓扑" }, series: [{ type: "graph", layout: "force", data: [1, 2] }] };
  assert.equal(normalizeTopologyOption(option), option);
  assert.equal(warn.mock.callCount(), 1);
});
