// Draws the embedded GraphData payload as an interactive, hierarchical SVG
// picture, using the vendored dagre layout engine for positions only -- all
// drawing here is plain SVG, and all interaction (expanding a collapsed
// MapEdge group) is local state over the same payload. Nothing here ever
// calls back into Python: the payload already has everything a click needs.
(function () {
  "use strict";

  var data = JSON.parse(document.getElementById("graph-data").textContent);
  var revealed = new Set(); // ids of GroupEntry the reader has expanded
  var svg = document.getElementById("viz-graph");
  var NS = "http://www.w3.org/2000/svg";

  // Box sizing, in pixels -- named the way tui/graph_browser/render.py names
  // its own display constants (IDENTITY_WIDTH, VALUE_WIDTH, MAP_ROW_CAP).
  var BOX_MIN_WIDTH = 120;
  var BOX_MAX_WIDTH = 340;
  var CHAR_WIDTH = 7;
  var BOX_PADDING = 24;
  var LINE_HEIGHT = 16;
  var BOX_TOP_PADDING = 22;

  function isVisible(ownerGroup) {
    return ownerGroup === null || revealed.has(ownerGroup);
  }

  function nodeLines(entry) {
    var lines = [entry.label].concat(entry.annotations);
    lines.push(
      entry.value_state === "uncomputed"
        ? "(uncomputed)"
        : entry.value + " (" + entry.value_state + ")"
    );
    return lines;
  }

  function groupLines(entry, expanded) {
    var count = entry.members.length;
    var lines = [count + (count === 1 ? " element" : " elements") + (expanded ? " ▾" : " ▸")];
    if (entry.guard) lines.push("if " + entry.guard);
    return lines;
  }

  function measure(lines) {
    var longest = lines.reduce(function (max, line) {
      return Math.max(max, line.length);
    }, 0);
    var width = Math.max(BOX_MIN_WIDTH, Math.min(BOX_MAX_WIDTH, longest * CHAR_WIDTH + BOX_PADDING));
    var height = BOX_TOP_PADDING + lines.length * LINE_HEIGHT;
    return { width: width, height: height };
  }

  // Why an edge named no cells: a map over nothing names none whether or not
  // it is guarded, the same distinction tui/graph_browser/render.py's
  // unresolved_reason keeps apart -- a guard blocking a call site is a real
  // conditional dependency that isn't live, an empty collection never had one.
  function guardedOffLines(edge) {
    if (edge.guard) return ["guarded off", "if " + edge.guard];
    if (edge.kind === "map edge") return ["no elements"];
    return ["not reached"];
  }

  // Builds a dagre graph of exactly what is visible right now -- a plain
  // function of `revealed`, so re-running it after a click is the whole of
  // "instant, client-side expansion".
  function buildLayout() {
    var g = new dagre.graphlib.Graph({ multigraph: true });
    g.setGraph({ rankdir: "LR", nodesep: 18, ranksep: 70, marginx: 24, marginy: 24 });
    g.setDefaultEdgeLabel(function () {
      return {};
    });

    var visibleNodes = {};
    Object.keys(data.nodes).forEach(function (id) {
      var entry = data.nodes[id];
      if (!isVisible(entry.group)) return;
      visibleNodes[id] = entry;
      var lines = nodeLines(entry);
      var size = measure(lines);
      g.setNode(id, {
        width: size.width,
        height: size.height,
        kind: "node",
        lines: lines,
        state: entry.value_state,
      });
    });

    var visibleGroups = {};
    Object.keys(data.groups).forEach(function (id) {
      var entry = data.groups[id];
      if (!isVisible(entry.group)) return;
      visibleGroups[id] = entry;
      var expanded = revealed.has(id);
      var lines = groupLines(entry, expanded);
      var size = measure(lines);
      g.setNode(id, {
        width: size.width,
        height: size.height,
        kind: "group",
        lines: lines,
        expanded: expanded,
        groupId: id,
      });
    });

    var drawEdges = [];
    function addEdge(v, w, edgeData, name) {
      g.setEdge(v, w, { edge: edgeData }, name);
      drawEdges.push({ v: v, w: w, edge: edgeData });
    }

    var stubs = 0;
    data.edges.forEach(function (edge, index) {
      if (!visibleNodes[edge.from_]) return;
      if (edge.to_type === "guarded_off") {
        var stubId = "stub" + stubs++;
        var lines = guardedOffLines(edge);
        var size = measure(lines);
        g.setNode(stubId, { width: size.width, height: size.height, kind: "stub", lines: lines });
        addEdge(edge.from_, stubId, edge, "e" + index);
      } else if (edge.to_type === "group" && visibleGroups[edge.to_id]) {
        addEdge(edge.from_, edge.to_id, edge, "e" + index);
      } else if (edge.to_type === "cell" && visibleNodes[edge.to_id]) {
        addEdge(edge.from_, edge.to_id, edge, "e" + index);
      }
    });

    // A revealed group's members are only connected to it once expanded --
    // drawn straight from the group's own membership list, not stored as an
    // EdgeEntry, since which members are visible is purely UI state.
    revealed.forEach(function (groupId) {
      var group = visibleGroups[groupId];
      if (!group) return;
      group.members.forEach(function (memberId, memberIndex) {
        if (!visibleNodes[memberId]) return;
        addEdge(groupId, memberId, { kind: "map edge" }, "m" + groupId + "-" + memberIndex);
      });
    });

    dagre.layout(g);
    return { g: g, drawEdges: drawEdges };
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function svgEl(tag, attrs) {
    var el = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) {
      el.setAttribute(key, attrs[key]);
    });
    return el;
  }

  function drawNode(id, box) {
    var group = svgEl("g", { class: "viz-box viz-" + box.kind + " viz-state-" + (box.state || "") });
    group.setAttribute(
      "transform",
      "translate(" + (box.x - box.width / 2) + "," + (box.y - box.height / 2) + ")"
    );
    group.appendChild(svgEl("rect", { width: box.width, height: box.height, rx: 6, ry: 6 }));
    box.lines.forEach(function (line, i) {
      var text = svgEl("text", { x: 10, y: 16 + i * 16 });
      text.textContent = line;
      group.appendChild(text);
    });
    if (box.kind === "group") {
      group.classList.add("viz-clickable");
      group.addEventListener("click", function () {
        if (box.expanded) revealed.delete(box.groupId);
        else revealed.add(box.groupId);
        draw();
      });
    }
    svg.appendChild(group);
  }

  function drawEdge(points, edge) {
    var d = points
      .map(function (p, i) {
        return (i === 0 ? "M" : "L") + p.x + "," + p.y;
      })
      .join(" ");
    var classes = ["viz-edge"];
    if (edge.cycle) classes.push("viz-cycle");
    if (edge.kind === "map edge") classes.push("viz-map-edge");
    var path = svgEl("path", { d: d, class: classes.join(" "), "marker-end": "url(#viz-arrow)" });
    svg.appendChild(path);
    if (edge.guard) {
      var mid = points[Math.floor(points.length / 2)];
      var label = svgEl("text", { x: mid.x, y: mid.y - 4, class: "viz-guard-label" });
      label.textContent = "if " + edge.guard;
      svg.appendChild(label);
    }
  }

  function draw() {
    clear(svg);
    svg.appendChild(buildDefs());
    var layout = buildLayout();
    var g = layout.g;

    var maxX = 0;
    var maxY = 0;
    g.nodes().forEach(function (id) {
      var box = g.node(id);
      drawNode(id, box);
      maxX = Math.max(maxX, box.x + box.width / 2);
      maxY = Math.max(maxY, box.y + box.height / 2);
    });
    layout.drawEdges.forEach(function (item) {
      var edgeLayout = g.edge(item);
      drawEdge(edgeLayout.points, item.edge);
    });
    svg.setAttribute("viewBox", "0 0 " + (maxX + 24) + " " + (maxY + 24));
  }

  function buildDefs() {
    var defs = svgEl("defs", {});
    var marker = svgEl("marker", {
      id: "viz-arrow",
      viewBox: "0 0 10 10",
      refX: 9,
      refY: 5,
      markerWidth: 7,
      markerHeight: 7,
      orient: "auto-start-reverse",
    });
    var arrow = svgEl("path", { d: "M0,0 L10,5 L0,10 z", class: "viz-arrowhead" });
    marker.appendChild(arrow);
    defs.appendChild(marker);
    return defs;
  }

  draw();
})();
