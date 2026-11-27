/**
 * Opus-style WDN map (Leaflet CRS.Simple), aligned with
 * Web_Application_Opus LID_WebApp network viewers (swmm_dashboard / agent3 / swmm.html):
 * dark water background, conduit/junction styling, map-lbl tooltips, Labels Auto|All|Off.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { n2 } from "./format.js";

const MAP_BG = "#0c1b24";

/** Opus LINK_STYLE / NODE_STYLE (swmm_dashboard.js) — EPANET pipes ≈ conduits. */
const LINK_STYLE = {
  conduit: { c: "#7f97a2", w: 2 },
};
const NODE_STYLE = {
  Junction: { c: "#8fa6b3", r: 4 },
  Reservoir: { c: "#2C7BE5", r: 7 },
  Tank: { c: "#1FA971", r: 8 },
};

function ll(x, y) {
  return [y, x];
}

function criticalityColor(v) {
  if (v === undefined || Number.isNaN(v)) return null;
  const t = Math.max(0, Math.min(1, Number(v) / 100));
  const r = Math.round(127 + t * 100);
  const g = Math.round(151 - t * 110);
  const b = Math.round(162 - t * 100);
  return `rgb(${r},${g},${b})`;
}

const SCORE_COLS = [
  ["Composite_Criticality", "composite"],
  ["Resilience_Reduction_%", "resilience reduction"],
  ["Path_Frequency_%", "path frequency"],
  ["Flow_Criticality_%", "flow criticality"],
  ["Betweenness_Centrality_%", "betweenness"],
  ["Demand_Coverage_%", "demand coverage"],
];

export default function NetworkMap({ geometry, pipeScores }) {
  const elRef = useRef(null);
  const mapRef = useRef(null);
  const layersRef = useRef({ links: {}, nodes: {} });
  const fitZoomRef = useRef(0);
  const labelModeRef = useRef("auto");
  const scoreMapRef = useRef({});
  const [labelMode, setLabelMode] = useState("auto");

  const [scoreCol, scoreName] =
    SCORE_COLS.find(([c]) => pipeScores?.[0] && c in pipeScores[0]) || [];
  const scoreMap = useMemo(() => {
    const m = {};
    (pipeScores || []).forEach((p) => {
      if (scoreCol) m[String(p.Pipe_ID)] = Number(p[scoreCol]);
    });
    return m;
  }, [pipeScores, scoreCol]);
  const scoreNameRef = useRef(scoreName);
  scoreNameRef.current = scoreName;

  scoreMapRef.current = scoreMap;
  labelModeRef.current = labelMode;

  const applyLabels = () => {
    const map = mapRef.current;
    if (!map) return;
    const mode = labelModeRef.current;
    const scores = scoreMapRef.current;
    const z = map.getZoom();
    const show = mode === "all" || (mode === "auto" && z >= fitZoomRef.current + 1);
    const permanent = mode !== "off" && show;
    Object.entries(layersRef.current.nodes).forEach(([id, layer]) => {
      layer.unbindTooltip();
      layer.bindTooltip(id, {
        permanent,
        direction: "top",
        className: "map-lbl",
      });
    });
    Object.entries(layersRef.current.links).forEach(([id, layer]) => {
      layer.unbindTooltip();
      const score = scores[id];
      const tip =
        score !== undefined && !Number.isNaN(score)
          ? `${id} · ${scoreNameRef.current} ${n2(score)}`
          : id;
      layer.bindTooltip(tip, {
        permanent,
        direction: "center",
        className: "map-lbl",
      });
    });
  };

  useEffect(() => {
    if (!elRef.current || mapRef.current) return;
    const map = L.map(elRef.current, {
      crs: L.CRS.Simple,
      minZoom: -6,
      maxZoom: 8,
      zoomControl: true,
      attributionControl: false,
    });
    elRef.current.style.background = MAP_BG;
    try {
      L.control.scale({ imperial: false, metric: true, position: "bottomleft" }).addTo(map);
    } catch (_) {
      /* ignore */
    }
    const Reset = L.Control.extend({
      options: { position: "topleft" },
      onAdd() {
        const d = L.DomUtil.create("div", "leaflet-bar reset-view-ctl");
        const a = L.DomUtil.create("a", "", d);
        a.href = "#";
        a.title = "Reset view (fit to content)";
        a.setAttribute("role", "button");
        a.innerHTML =
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M3 12a9 9 0 1 0 3-6.7"/><polyline points="3 4 3 10 9 10"/></svg>';
        a.style.cssText =
          "display:flex;align-items:center;justify-content:center;width:30px;height:30px;color:#12313C";
        L.DomEvent.on(a, "click", L.DomEvent.stop)
          .on(a, "click", L.DomEvent.preventDefault)
          .on(a, "click", () => {
            const b = mapRef.current?._contentBounds;
            if (b && b.isValid()) map.fitBounds(b, { padding: [18, 18] });
          });
        return d;
      },
    });
    map.addControl(new Reset());
    map.on("zoomend", () => {
      if (labelModeRef.current === "auto") applyLabels();
    });
    mapRef.current = map;
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(elRef.current);
    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !geometry?.nodes?.length) return;

    Object.values(layersRef.current.links).forEach((l) => map.removeLayer(l));
    Object.values(layersRef.current.nodes).forEach((l) => map.removeLayer(l));
    layersRef.current = { links: {}, nodes: {} };

    const byId = {};
    geometry.nodes.forEach((n) => {
      byId[n.id] = n;
    });

    const bounds = [];
    (geometry.pipes || []).forEach((p) => {
      const a = byId[p.start];
      const b = byId[p.end];
      if (!a || !b) return;
      const path = [ll(a.x, a.y), ll(b.x, b.y)];
      path.forEach((pt) => bounds.push(pt));
      const score = scoreMap[p.id];
      const crit = criticalityColor(score);
      const st = LINK_STYLE.conduit;
      const pl = L.polyline(path, {
        color: crit || st.c,
        weight: crit ? st.w + 0.5 : st.w,
        opacity: 0.9,
      }).addTo(map);
      layersRef.current.links[p.id] = pl;
    });

    geometry.nodes.forEach((n) => {
      const st = NODE_STYLE[n.type] || NODE_STYLE.Junction;
      const cm = L.circleMarker(ll(n.x, n.y), {
        radius: st.r,
        color: "#28323a",
        weight: 1,
        fillColor: st.c,
        fillOpacity: 0.9,
      }).addTo(map);
      layersRef.current.nodes[n.id] = cm;
      bounds.push(ll(n.x, n.y));
    });

    if (bounds.length) {
      const b = L.latLngBounds(bounds);
      map._contentBounds = b;
      map.fitBounds(b, { padding: [24, 24] });
      fitZoomRef.current = map.getZoom();
    }
    applyLabels();
    setTimeout(() => map.invalidateSize(), 80);
  }, [geometry, scoreMap]);

  useEffect(() => {
    applyLabels();
  }, [labelMode]);

  function cycleLabels() {
    setLabelMode((m) => (m === "off" ? "auto" : m === "auto" ? "all" : "off"));
  }

  if (!geometry?.nodes?.length) {
    return <p className="muted">Upload an .inp file to show the network figure.</p>;
  }

  return (
    <div className="opus-map-wrap">
      <div className="opus-map-toolbar">
        <button
          type="button"
          className={`secondary ${labelMode !== "off" ? "active-lbl" : ""}`}
          onClick={cycleLabels}
          title="Cycle label mode (Opus: Off → Auto → All)"
        >
          Labels: {labelMode.charAt(0).toUpperCase() + labelMode.slice(1)}
        </button>
        <span className="muted opus-map-legend">
          <span className="sw" style={{ background: LINK_STYLE.conduit.c }} /> pipes
          <span className="sw" style={{ background: NODE_STYLE.Junction.c }} /> junctions
          <span className="sw" style={{ background: NODE_STYLE.Reservoir.c }} /> reservoirs
          <span className="sw" style={{ background: NODE_STYLE.Tank.c }} /> tanks
          {scoreName ? ` · pipes tinted by ${scoreName}` : null}
        </span>
      </div>
      <div ref={elRef} className="opus-map" role="img" aria-label="Water distribution network map" />
    </div>
  );
}
