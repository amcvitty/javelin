// Draws the embedded GraphData payload as an interactive, hierarchical SVG
// picture, using the vendored dagre layout engine for positions only -- all
// drawing here is plain SVG, and all interaction (expanding a collapsed
// MapEdge group, panning, zooming) is local state over the same payload.
// Nothing here ever calls back into Python: the payload already has
// everything a click needs.
(function () {
  "use strict";

  var data = JSON.parse(document.getElementById("graph-data").textContent);
  var revealed = new Set(); // ids of GroupEntry the reader has expanded
  var svg = document.getElementById("viz-graph");
  var toolbar = document.getElementById("viz-toolbar");
  var NS = "http://www.w3.org/2000/svg";

  // Box sizing, in pixels -- named the way tui/graph_browser/render.py names
  // its own display constants (IDENTITY_WIDTH, VALUE_WIDTH, MAP_ROW_CAP).
  var BOX_MIN_WIDTH = 120;
  var BOX_MAX_WIDTH = 340;
  var CHAR_WIDTH = 7;
  var BOX_PADDING = 24;
  var LINE_HEIGHT = 16;
  var BOX_TOP_PADDING = 22;

  // A cluster's margin on every side is dagre's own nodesep -- tall enough
  // here for its object-name label to fit in the gap above its members
  // without touching them.
  var NODESEP = 30;
  var RANKSEP = 60;

  //: Current pan/zoom, applied as one transform on the viewport group.
  //: `null` until the first draw, which fits the whole (mostly collapsed)
  //: picture to the window; every draw after that leaves it alone, so
  //: revealing a group never resets where the reader is looking.
  var view = null;
  var ZOOM_MIN = 0.05;
  var ZOOM_MAX = 4;

  function isVisible(ownerGroup) {
    return ownerGroup === null || revealed.has(ownerGroup);
  }

  function nodeLines(entry) {
    // The object name is not repeated here -- it is what the surrounding
    // cluster box is labelled with.
    var lines = [entry.method_label].concat(entry.annotations);
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
  // "instant, client-side expansion". A compound graph: every plain cell is
  // parented to a synthetic cluster node per `object_id`, so cells of the
  // same object are laid out (and later drawn) inside one surrounding box.
  // Group and stub boxes are never parented -- a collapsed MapEdge stands
  // for many objects at once, and a guarded-off stub is not a cell at all.
  function buildLayout() {
    var g = new dagre.graphlib.Graph({ multigraph: true, compound: true });
    g.setGraph({ rankdir: "TB", nodesep: NODESEP, ranksep: RANKSEP, marginx: 24, marginy: 24 });
    g.setDefaultEdgeLabel(function () {
      return {};
    });

    var visibleNodes = {};
    var clusterOf = {}; // object_id -> synthetic cluster node id, this draw only
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
        title: entry.label,
      });
      var clusterId = clusterOf[entry.object_id];
      if (!clusterId) {
        clusterId = "cluster-" + entry.object_id;
        clusterOf[entry.object_id] = clusterId;
        g.setNode(clusterId, { kind: "cluster", label: entry.object_label });
      }
      g.setParent(id, clusterId);
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
      // `name` travels with the record: this is a multigraph (a MapEdge can
      // send several members between the same two nodes), so g.edge() needs
      // it back to find the right one rather than the first one stored.
      drawEdges.push({ v: v, w: w, name: name, edge: edgeData });
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

  function drawCluster(viewport, box) {
    var g = svgEl("g", { class: "viz-cluster" });
    g.setAttribute(
      "transform",
      "translate(" + (box.x - box.width / 2) + "," + (box.y - box.height / 2) + ")"
    );
    g.appendChild(svgEl("rect", { width: box.width, height: box.height, rx: 8, ry: 8 }));
    var label = svgEl("text", { x: 8, y: 14, class: "viz-cluster-label" });
    label.textContent = box.label;
    g.appendChild(label);
    viewport.appendChild(g);
  }

  function drawNode(viewport, box) {
    var group = svgEl("g", { class: "viz-box viz-" + box.kind + " viz-state-" + (box.state || "") });
    group.setAttribute(
      "transform",
      "translate(" + (box.x - box.width / 2) + "," + (box.y - box.height / 2) + ")"
    );
    if (box.title) {
      var title = svgEl("title", {});
      title.textContent = box.title;
      group.appendChild(title);
    }
    group.appendChild(svgEl("rect", { width: box.width, height: box.height, rx: 6, ry: 6 }));
    box.lines.forEach(function (line, i) {
      var text = svgEl("text", { x: 10, y: 16 + i * 16 });
      text.textContent = line;
      group.appendChild(text);
    });
    if (box.kind === "group") {
      group.classList.add("viz-clickable");
      group.addEventListener("click", function () {
        if (dragMoved) return; // a drag ending on this box is a pan, not a click
        if (box.expanded) revealed.delete(box.groupId);
        else revealed.add(box.groupId);
        draw();
      });
    }
    viewport.appendChild(group);
  }

  function drawEdge(viewport, points, edge) {
    var d = points
      .map(function (p, i) {
        return (i === 0 ? "M" : "L") + p.x + "," + p.y;
      })
      .join(" ");
    var classes = ["viz-edge"];
    if (edge.cycle) classes.push("viz-cycle");
    if (edge.kind === "map edge") classes.push("viz-map-edge");
    var path = svgEl("path", { d: d, class: classes.join(" "), "marker-end": "url(#viz-arrow)" });
    viewport.appendChild(path);
    if (edge.guard) {
      var mid = points[Math.floor(points.length / 2)];
      var label = svgEl("text", { x: mid.x, y: mid.y - 4, class: "viz-guard-label" });
      label.textContent = "if " + edge.guard;
      viewport.appendChild(label);
    }
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

  function viewportSize() {
    return { width: svg.clientWidth || 800, height: svg.clientHeight || 600 };
  }

  function applyTransform(viewport) {
    viewport.setAttribute(
      "transform",
      "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")"
    );
  }

  function draw() {
    clear(svg);
    svg.setAttribute("viewBox", "0 0 " + viewportSize().width + " " + viewportSize().height);
    svg.appendChild(buildDefs());
    var viewport = svgEl("g", { id: "viz-viewport" });
    svg.appendChild(viewport);

    var layout = buildLayout();
    var g = layout.g;

    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    var clusters = [];
    var boxes = [];
    g.nodes().forEach(function (id) {
      var box = g.node(id);
      if (box.kind === "cluster") {
        clusters.push(box);
      } else {
        boxes.push(box);
      }
      minX = Math.min(minX, box.x - box.width / 2);
      minY = Math.min(minY, box.y - box.height / 2);
      maxX = Math.max(maxX, box.x + box.width / 2);
      maxY = Math.max(maxY, box.y + box.height / 2);
    });
    // Clusters first, as a background; edges next; the cells themselves on
    // top, so a box is always fully readable over whatever passes behind it.
    clusters.forEach(function (box) {
      drawCluster(viewport, box);
    });
    layout.drawEdges.forEach(function (item) {
      var edgeLayout = g.edge(item.v, item.w, item.name);
      drawEdge(viewport, edgeLayout.points, item.edge);
    });
    boxes.forEach(function (box) {
      drawNode(viewport, box);
    });

    if (view === null) {
      view = fitToViewport(minX, minY, maxX, maxY);
    }
    applyTransform(viewport);
  }

  // The initial view: the whole (mostly collapsed) picture, root at the top,
  // scaled to fit the window and never zoomed in past 100%. Only computed
  // once -- expanding a group after this leaves the reader's own pan and
  // zoom exactly where they left it.
  function fitToViewport(minX, minY, maxX, maxY) {
    var size = viewportSize();
    var contentWidth = Math.max(1, maxX - minX);
    var contentHeight = Math.max(1, maxY - minY);
    var margin = 40;
    var k = Math.min(
      1,
      (size.width - margin) / contentWidth,
      (size.height - margin) / contentHeight
    );
    if (!isFinite(k) || k <= 0) k = 1;
    return {
      k: k,
      x: (size.width - contentWidth * k) / 2 - minX * k,
      y: margin / 2 - minY * k,
    };
  }

  // -- pan and zoom -----------------------------------------------------
  //
  // Hand-rolled rather than pulled in as a dependency: the vendored library
  // is a layout engine, not a rendering/interaction one, and this is a
  // small enough amount of arithmetic not to be worth a second vendored
  // file for. Wheel zooms about the cursor; drag pans; both just rewrite
  // `view` and re-apply the one transform.

  var dragging = false;
  var dragMoved = false;
  var dragStart = null;

  svg.addEventListener(
    "wheel",
    function (e) {
      if (view === null) return;
      e.preventDefault();
      var rect = svg.getBoundingClientRect();
      var mx = e.clientX - rect.left;
      var my = e.clientY - rect.top;
      var factor = Math.exp(-e.deltaY * 0.001);
      var newK = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, view.k * factor));
      // Keeps the point under the cursor fixed on screen while it scales.
      view.x = mx - ((mx - view.x) * newK) / view.k;
      view.y = my - ((my - view.y) * newK) / view.k;
      view.k = newK;
      var viewport = document.getElementById("viz-viewport");
      if (viewport) applyTransform(viewport);
    },
    { passive: false }
  );

  svg.addEventListener("mousedown", function (e) {
    if (view === null) return;
    dragging = true;
    dragMoved = false;
    dragStart = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    svg.classList.add("viz-panning");
  });

  window.addEventListener("mousemove", function (e) {
    if (!dragging) return;
    var dx = e.clientX - dragStart.x;
    var dy = e.clientY - dragStart.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMoved = true;
    view.x = dragStart.vx + dx;
    view.y = dragStart.vy + dy;
    var viewport = document.getElementById("viz-viewport");
    if (viewport) applyTransform(viewport);
  });

  window.addEventListener("mouseup", function () {
    dragging = false;
    svg.classList.remove("viz-panning");
    // Cleared on a later tick: the click event that follows mouseup on the
    // same element fires synchronously right after, and still needs to see
    // this drag as having moved.
    setTimeout(function () {
      dragMoved = false;
    }, 0);
  });

  function zoomBy(factor) {
    if (view === null) return;
    var size = viewportSize();
    var newK = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, view.k * factor));
    view.x = size.width / 2 - ((size.width / 2 - view.x) * newK) / view.k;
    view.y = size.height / 2 - ((size.height / 2 - view.y) * newK) / view.k;
    view.k = newK;
    var viewport = document.getElementById("viz-viewport");
    if (viewport) applyTransform(viewport);
  }

  function addToolbarButton(label, title, onClick) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "viz-zoom-button";
    button.textContent = label;
    button.title = title;
    button.addEventListener("click", onClick);
    toolbar.appendChild(button);
  }

  addToolbarButton("−", "Zoom out", function () {
    zoomBy(1 / 1.25);
  });
  addToolbarButton("+", "Zoom in", function () {
    zoomBy(1.25);
  });
  addToolbarButton("⤢", "Fit to window", function () {
    view = null;
    draw();
  });

  window.addEventListener("resize", function () {
    svg.setAttribute("viewBox", "0 0 " + viewportSize().width + " " + viewportSize().height);
  });

  draw();
})();
