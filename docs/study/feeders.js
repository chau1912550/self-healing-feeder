/* Every test feeder: 2D map, 3D view and zone one-line diagram.
 * Drawing data: feeder_maps.json, copied by scripts/build_study_site.py from results/feeders/feeder_maps.json
 * (written by scripts/export_feeder_maps.py from the official OpenDSS models). Loaded when the figure is near. */
(() => {
  "use strict";
  const box = document.getElementById("fig-feeders");
  if (!box) return;
  const root = document.documentElement;
  const tr = (en, vi) => (root.lang === "vi" ? vi : en);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const nf = x => Math.round(x).toLocaleString("en-US");
  const PAL = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
               "#393b79", "#ad494a", "#637939", "#8c6d31", "#7b4173", "#3182bd", "#e6550d", "#31a354"];
  const sel = box.querySelector("#fm-feeder"), stage = box.querySelector("#fm-stage"), legend = box.querySelector("#fm-legend"),
        info = box.querySelector("#fm-info"), modes = [...box.querySelectorAll("[data-fm-mode]")];
  let DATA = null, cur = null, mode = "map", three = null;

  const load = () => DATA ? Promise.resolve(DATA)
    : fetch(box.dataset.src || "feeder_maps.json").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(d => (DATA = d));

  const zoneColor = i => i < 0 ? "var(--rule)" : PAL[i % PAL.length];
  // colours come from CSS variables on the figure, so the same script works on the paper and on the run report
  const cssColor = c => c.startsWith("var(") ? getComputedStyle(box).getPropertyValue(c.slice(4, -1)).trim() || "#999" : c;

  function drawLegend(f) {
    legend.innerHTML = f.zones.map((z, i) =>
      `<span class="fm-z"><span class="sw" style="background:${zoneColor(i)}"></span><b>${esc(z.name)}</b> ${nf(z.kw)} kW · ${nf(z.buses)} ${tr("buses", "nút")}</span>`).join("");
    info.innerHTML = tr(
      `<b>${esc(f.label)}</b>: ${nf(f.buses_drawn)} buses drawn, ${f.zones.length} zones, source ${f.root_kv_ll} kV, ${f.hz} Hz. Position source: ${esc(f.layout)}.`,
      `<b>${esc(f.label)}</b>: vẽ ${nf(f.buses_drawn)} nút, ${f.zones.length} vùng, nguồn ${f.root_kv_ll} kV, ${f.hz} Hz. Nguồn tọa độ: ${f.layout.startsWith("bus coordinates;") ? "tọa độ nút của mô hình; nút không có tọa độ được vẽ tại nút phía trên gần nhất" : f.layout === "bus coordinates" ? "tọa độ nút của mô hình" : "bố cục dạng cây"}.`);
  }

  function drawMap(f) {
    stage.innerHTML = "";
    const cv = document.createElement("canvas");
    cv.setAttribute("role", "img");
    cv.setAttribute("aria-label", tr(`Map of ${f.label} coloured by zone`, `Bản đồ ${f.label} tô màu theo vùng`));
    stage.appendChild(cv);
    const W = stage.clientWidth || 700, H = Math.round(Math.min(560, Math.max(320, W * 0.62))), dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + "px"; cv.style.height = H + "px";
    const g = cv.getContext("2d"); g.scale(dpr, dpr);
    const xs = f.buses.map(b => b[1]), ys = f.buses.map(b => b[2]);
    const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
    const s = Math.min((W - 30) / ((maxx - minx) || 1), (H - 30) / ((maxy - miny) || 1));
    const ox = (W - s * (maxx - minx)) / 2, oy = (H - s * (maxy - miny)) / 2;
    const P = b => [ox + s * (b[1] - minx), H - (oy + s * (b[2] - miny))];
    const lw = f.buses.length > 2000 ? 0.8 : f.buses.length > 300 ? 1.2 : 2.2;
    const byZone = {};
    f.edges.forEach(e => (byZone[e[2]] = byZone[e[2]] || []).push(e));
    Object.entries(byZone).forEach(([z, es]) => {
      g.strokeStyle = cssColor(zoneColor(+z)); g.lineWidth = lw; g.beginPath();
      es.forEach(([a, b]) => { const p = P(f.buses[a]), q = P(f.buses[b]); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); });
      g.stroke();
    });
    // switching devices: a square at the first bus of each zone
    f.zones.forEach((z, i) => {
      if (z.start == null) return;
      const p = P(f.buses[z.start]);
      g.fillStyle = cssColor(zoneColor(i)); g.strokeStyle = cssColor("var(--fg)"); g.lineWidth = 1.2;
      g.fillRect(p[0] - 5, p[1] - 5, 10, 10); g.strokeRect(p[0] - 5, p[1] - 5, 10, 10);
      g.fillStyle = cssColor("var(--fg)"); g.font = "600 11px system-ui, sans-serif"; g.fillText(z.name, p[0] + 7, p[1] - 6);
    });
    const r = f.buses.find(b => b[0] === f.root);
    if (r) { const p = P(r); g.fillStyle = cssColor("var(--st-fault)"); g.beginPath(); g.arc(p[0], p[1], 6, 0, 7); g.fill(); }
  }

  function drawOneLine(f) {
    // radial single-line diagram at zone level: source on top, one row per zone in depth-first order,
    // each zone hanging from its parent through its switching device (square)
    const kids = {}; f.zones.forEach(z => (kids[z.parent || "__src"] = kids[z.parent || "__src"] || []).push(z.name));
    const zi = Object.fromEntries(f.zones.map((z, i) => [z.name, i]));
    const rows = [], depthOf = {};
    const walk = (n, d) => { rows.push(n); depthOf[n] = d; (kids[n] || []).forEach(k => walk(k, d + 1)); };
    walk("__src", 0);
    const RH = 34, IX = 30, X0 = 16, Y0 = 18;
    const maxD = Math.max(...Object.values(depthOf));
    const W = X0 + maxD * IX + 360, H = Y0 + rows.length * RH + 6;
    const y = n => Y0 + rows.indexOf(n) * RH, x = n => X0 + depthOf[n] * IX;
    let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(tr(`One-line diagram of ${f.label} by zone`, `Sơ đồ một sợi ${f.label} theo vùng`))}" class="fm-ol">`;
    rows.slice(1).forEach(n => {
      const par = f.zones[zi[n]].parent || "__src", px = x(par) + 7, py = y(par) + 14, cx = x(n), cy = y(n) + 7;
      s += `<path d="M${px} ${py}V${cy}H${cx}" class="fm-wire"/>`;
    });
    s += `<circle cx="${x("__src") + 7}" cy="${y("__src") + 7}" r="7" class="fm-src"/>` +
         `<text x="${x("__src") + 20}" y="${y("__src") + 12}" class="fm-t1">${esc(tr("Source", "Nguồn"))} ${esc(f.root)} · ${f.root_kv_ll} kV · ${f.hz} Hz</text>`;
    rows.slice(1).forEach(n => {
      const z = f.zones[zi[n]], i = zi[n], cx = x(n), cy = y(n);
      s += `<rect x="${cx}" y="${cy}" width="14" height="14" class="fm-sw" style="fill:${zoneColor(i)}"><title>${esc(z.name)} · ${esc(tr("line", "đường dây"))} ${esc(z.line)}</title></rect>` +
           `<text x="${cx + 22}" y="${cy + 11}" class="fm-t1">${esc(z.name)}</text>` +
           `<text x="${cx + 58}" y="${cy + 11}" class="fm-t2">${nf(z.kw)} kW · ${nf(z.buses)} ${esc(tr("buses", "nút"))} · ${z.kv_ll} kV</text>`;
    });
    stage.innerHTML = `<div class="fm-olwrap">${s}</svg></div>`;
  }

  function drawThree(f) {
    stage.innerHTML = `<p class="fm-wait">${esc(tr("Loading 3D…", "Đang tải 3D…"))}</p>`;
    const go = THREE => {
      stage.innerHTML = "";
      const W = stage.clientWidth || 700, H = Math.round(Math.min(560, Math.max(320, W * 0.62)));
      const ren = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      ren.setPixelRatio(window.devicePixelRatio || 1); ren.setSize(W, H); stage.appendChild(ren.domElement);
      ren.domElement.setAttribute("aria-label", tr(`3D view of ${f.label}; drag to rotate`, `Hình 3D ${f.label}; kéo để xoay`));
      const scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(40, W / H, 1, 20000);
      const xs = f.buses.map(b => b[1]), ys = f.buses.map(b => b[2]);
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
      // zones are lifted by their depth in the zone tree so the cascade of devices is visible
      const dep = {}; const depthOf = n => n == null ? -1 : dep[n] != null ? dep[n] : (dep[n] = depthOf((f.zones.find(z => z.name === n) || {}).parent) + 1);
      const zh = f.zones.map(z => 26 * depthOf(z.name));
      const pts = [], cols = [], c = new THREE.Color();
      f.edges.forEach(([a, b, z]) => {
        const h = z >= 0 ? zh[z] : 0, A = f.buses[a], B = f.buses[b];
        pts.push(A[1] - cx, h, -(A[2] - cy), B[1] - cx, h, -(B[2] - cy));
        c.set(cssColor(zoneColor(z))); cols.push(c.r, c.g, c.b, c.r, c.g, c.b);
      });
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      geo.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
      scene.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true })));
      f.zones.forEach((z, i) => { if (z.start == null) return; const B = f.buses[z.start];
        const pole = new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10), new THREE.MeshBasicMaterial({ color: cssColor(zoneColor(i)) }));
        pole.position.set(B[1] - cx, zh[i] + 5, -(B[2] - cy)); scene.add(pole); });
      let th = 0.6, ph = 0.6, dist = 1350, drag = null;
      const place = () => { cam.position.set(dist * Math.sin(ph) * Math.sin(th), dist * Math.cos(ph), dist * Math.sin(ph) * Math.cos(th)); cam.lookAt(0, 30, 0); ren.render(scene, cam); };
      ren.domElement.addEventListener("pointerdown", e => { drag = [e.clientX, e.clientY, th, ph]; ren.domElement.setPointerCapture(e.pointerId); });
      ren.domElement.addEventListener("pointermove", e => { if (!drag) return; th = drag[2] - (e.clientX - drag[0]) / 200; ph = Math.min(1.45, Math.max(0.15, drag[3] - (e.clientY - drag[1]) / 200)); place(); });
      ren.domElement.addEventListener("pointerup", () => { drag = null; });
      ren.domElement.addEventListener("wheel", e => { e.preventDefault(); dist = Math.min(4000, Math.max(400, dist * (e.deltaY > 0 ? 1.1 : 0.9))); place(); }, { passive: false });
      three = ren; place();
    };
    if (window.THREE) return go(window.THREE);
    const sc = document.createElement("script");
    sc.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
    sc.onload = () => go(window.THREE);
    sc.onerror = () => { stage.innerHTML = `<p class="fm-wait">${esc(tr("3D could not load; the 2D map shows instead.", "Không tải được 3D; hiện bản đồ 2D thay thế."))}</p>`; setTimeout(() => setMode("map"), 1500); };
    document.head.appendChild(sc);
  }

  function render() {
    if (!DATA || !cur) return;
    const f = DATA.feeders[cur];
    if (three) { try { three.dispose(); } catch (e) { /* ignore */ } three = null; }
    drawLegend(f);
    if (mode === "map") drawMap(f); else if (mode === "oneline") drawOneLine(f); else drawThree(f);
  }
  function setMode(m) { mode = m; modes.forEach(b => b.setAttribute("aria-pressed", String(b.dataset.fmMode === m))); render(); }

  function init() {
    load().then(d => {
      sel.innerHTML = Object.entries(d.feeders).map(([k, f]) => `<option value="${k}">${esc(f.label)}</option>`).join("");
      cur = sel.value; render();
    }).catch(err => { stage.innerHTML = `<p class="fm-wait">feeder_maps.json: ${esc(err.message)}</p>`; });
  }
  sel.addEventListener("change", () => { cur = sel.value; render(); });
  modes.forEach(b => b.addEventListener("click", () => setMode(b.dataset.fmMode)));
  new MutationObserver(() => render()).observe(root, { attributes: true, attributeFilter: ["lang", "data-theme"] });
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (mode === "map") render(); }, 200); });
  const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); init(); } }, { rootMargin: "300px" });
  io.observe(box);
})();
