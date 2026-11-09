// ── Hero parallax: mouse only, desktop only, one write per frame ──
(function () {
    const title = document.querySelector('.hero-title'), sub = document.querySelector('.hero-sub'),
        logo = document.querySelector('.hero-logo-wrap');
    if (!title) return;
    let px = 0, py = 0, queued = false;
    const apply = () => {
        queued = false;
        const x = (window.innerWidth / 2 - px) * 0.01, y = (window.innerHeight / 2 - py) * 0.01;
        title.style.transform = `translate(${x}px, ${y}px)`;
        if (sub) sub.style.transform = `translate(${x * 1.5}px, ${y * 1.5}px)`;
        if (logo) logo.style.transform = `translate(${x * 0.5}px, ${y * 0.5}px)`;
    };
    document.addEventListener('pointermove', e => {
        if (e.pointerType !== 'mouse' || window.innerWidth <= 1024 || window.scrollY > window.innerHeight) return;
        px = e.clientX; py = e.clientY;
        if (!queued) { queued = true; requestAnimationFrame(apply); }
    }, { passive: true });
})();

// ── Sky: a small tilted spiral galaxy + slowly forming "digital constellations" ──
// One canvas (#particles-canvas) behind every page. Everything is scoped to this
// function: no globals, no debug hooks. It stops at once where there is no 2D
// context (jsdom in Eye-Describe/bytemap-test.js), before any other browser API.
(function crowSky() {
    'use strict';
    var canvas = document.getElementById('particles-canvas');
    if (!canvas || !canvas.getContext) return;
    var ctx = null;
    try { ctx = canvas.getContext('2d'); } catch (e) { ctx = null; }
    if (!ctx || typeof ctx.fillRect !== 'function') return;
    // data-no-galaxy (sentinel.html): the sky stays, the galaxy is replaced by the
    // Earth drawn on #sentinel-globe. The constellations keep out of the globe the
    // way they keep out of the galaxy, from the centre/radius that canvas publishes.
    var NOGAL = canvas.hasAttribute('data-no-galaxy');
    // the page's centrepiece (Sentinel globe, CFR system, Eye, ...): any canvas with data-centerpiece
    var GLOBE = NOGAL ? document.querySelector('[data-centerpiece]') : null, GLOBE_R = 0;

    var TAU = Math.PI * 2;
    var CFG = {
        FPS: 30,
        DPR_MAX: 1.5,                          // gov 0; gov >= 1 caps it at 1 (see dprFor). Stars are quads now, so HiDPI keeps them crisp
        // galaxy
        R_K: 0.487, R_MIN: 223, R_MAX: 1061,   // disk radius (CSS px) = clamp(R_K*sqrt(W*H)): the reference, +30% twice, +20%
        PITCH: 3.1,                            // log-spiral pitch of the two arms
        PATTERN_W: TAU / 480,                  // arm pattern: one turn in 8 minutes
        ORBIT_K: 0.026, ORBIT_C: 0.15,         // material: w(r) = K/(r+C)  (inner faster)
        STREAM: 0.004,                         // arm stars lose 0.4% of radius per second
        TWIST_A: 0.28, TWIST_T: 170,           // wind/unwind: 0.28*sin(2pi t/170)*(r-0.4)
        BREATH_T: 9,                           // core breathing period (s)
        SPIN_MAX: 0.62,                        // extra rad/s at full scroll speed
        STREAK_T: 0.22, STREAK_MAX: 18,       // fast scroll: star trails along the rotation (s of travel, px cap)
        GAS_ALPHA: 0.8, STAR_ALPHA: 0.85,
        GALAXY_ALPHA: 0.58, GALAXY_ALPHA_SMALL: 0.52,   // ~30% less light than the first 0.9 / 0.8 (the outer arms carry a little more gas)
        STARS: 840, STARS_SMALL: 546, GLOW_MAX: 18,
        GAS_HZ: 8,
        POLAR_A: 1024, POLAR_R: 192,           // gas textures, polar (angle x radius), built at this size and read 2x finer (upsampled)
        FLOW_A: 2048, FLOW_U: 512,             // gas streak texture, spiral coords (arm phase x log radius); fine across the arms
        FLOW_TILE: 1.5, FLOW_V: 0.022,         // log-radius per tile; inflow along the arms (log-radius per s)
        KNOTS: 50,                             // HII knots on the arms
        PRECESS_T: 150,                        // the tilt's slow precession (s)
        // sky + constellations
        FIELD_AREA: 24000, FIELD_MIN: 16, FIELD_MAX: 90,
        GROUPS: 2, LINK: 140, MIN_SIZE: 3, MAX_SIZE: 7,
        CONVERT_T: 4, LINK_T: 3, GROW_MIN: 4, GROW_MAX: 7,
        LIFE_MIN: 55, LIFE_MAX: 70, DOWN_STEP: 2, NEXT_MIN: 8, NEXT_MAX: 14,
        PULSE_SPEED: 30, PULSES: 2, GALAXY_KEEP_OUT: 1.4,
        CELL: 24,
        // deep sky: three parallax layers + shooting stars (the previous star-field)
        DEEP: [{ n: 60, rMin: 0.3, rMax: 0.7, aMin: 0.08, aMax: 0.20, sp: 2.4, par: 0.04 },
               { n: 45, rMin: 0.7, rMax: 1.3, aMin: 0.15, aMax: 0.32, sp: 5.4, par: 0.09 },
               { n: 26, rMin: 1.2, rMax: 2.2, aMin: 0.28, aMax: 0.50, sp: 9.6, par: 0.16 }],
        SHOOT_MIN: 4, SHOOT_MAX: 9, SHOOTERS: 2
    };

    // ---- helpers ---------------------------------------------------------------
    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    function lerp(a, b, t) { return a + (b - a) * t; }
    function smooth(a, b, x) { var t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }
    function ease(t) { return t * t * (3 - 2 * t); }
    function rng(seed) {                              // mulberry32
        var s = seed >>> 0;
        return function () {
            s = (s + 0x6D2B79F5) >>> 0;
            var t = Math.imul(s ^ (s >>> 15), 1 | s);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }
    var R0 = rng(0xC0E1E);                           // deterministic galaxy shape
    var RND = Math.random;                           // sky / constellations
    function gauss(r) { var u = 1 - r(), v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(TAU * v); }
    function hash(a, b) {                             // stateless byte values (as cp-docs.js)
        var h = Math.imul(a ^ 0x27d4eb2d, 0x165667b1) ^ Math.imul(b + 0x3c6ef372, 0x9e3779b1);
        h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
        h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
        return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
    }

    // value noise (2D), seeded, quintic fade, plus fbm
    var PERM = new Uint8Array(512), VAL = new Float32Array(256);
    (function () {
        var p = [], i, j, t;
        for (i = 0; i < 256; i++) { p[i] = i; VAL[i] = R0(); }
        for (i = 255; i > 0; i--) { j = (R0() * (i + 1)) | 0; t = p[i]; p[i] = p[j]; p[j] = t; }
        for (i = 0; i < 512; i++) PERM[i] = p[i & 255];
    })();
    function noise(x, y) {
        var xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
        var X = xi & 255, Y = yi & 255;
        var u = xf * xf * xf * (xf * (xf * 6 - 15) + 10), v = yf * yf * yf * (yf * (yf * 6 - 15) + 10);
        var a = VAL[PERM[PERM[X] + Y]], b = VAL[PERM[PERM[X + 1] + Y]];
        var c = VAL[PERM[PERM[X] + Y + 1]], d = VAL[PERM[PERM[X + 1] + Y + 1]];
        return lerp(lerp(a, b, u), lerp(c, d, u), v);
    }
    function fbm(x, y) {
        var s = 0, a = 0.5, f = 1;
        for (var o = 0; o < 4; o++) { s += a * noise(x * f, y * f); f *= 2.03; a *= 0.5; }
        return s / 0.9375;
    }

    // ---- canvas placement safety net ----------------------------------------------
    if (document.body && document.body.firstElementChild !== canvas) document.body.insertBefore(canvas, document.body.firstChild);
    try {
        if (getComputedStyle(canvas).position !== 'fixed') {
            canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100vh;z-index:-1;pointer-events:none;display:block';
        }
    } catch (e) { /* ignore */ }

    // ---- view ----------------------------------------------------------------------
    var W = 0, H = 0, DPR = 1, small = false, R = 80;
    // backing-store scale: the governor trades sharpness first (sizes stay in CSS px - DPR only
    // ever enters through the transform in render() and the gas buffer's size)
    function dprFor(l) { return Math.min(l >= 1 ? 1 : CFG.DPR_MAX, window.devicePixelRatio || 1); }
    function measure() {
        var w = canvas.clientWidth || window.innerWidth, h = canvas.clientHeight || window.innerHeight;
        return { w: Math.max(1, Math.round(w)), h: Math.max(1, Math.round(h)) };
    }
    function applySize(w, h) {
        W = w; H = h; small = W < 700;
        DPR = dprFor(govLevel);
        canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
        R = clamp(CFG.R_K * Math.sqrt(W * H), CFG.R_MIN, CFG.R_MAX);
    }

    // ---- input ---------------------------------------------------------------------
    var mouse = { x: -1e4, y: -1e4, on: false, dx: 0, dy: 0, still: 0, mouse: false };
    function onPointerMove(e) {
        var isMouse = e.pointerType === 'mouse' || !e.pointerType;
        if (!isMouse && !mouse.down) return;
        mouse.dx += e.clientX - (mouse.on ? mouse.x : e.clientX);
        mouse.dy += e.clientY - (mouse.on ? mouse.y : e.clientY);
        mouse.x = e.clientX; mouse.y = e.clientY; mouse.on = true; mouse.mouse = isMouse; mouse.still = 0;
    }
    function pointerOff() { mouse.on = false; mouse.down = false; mouse.x = mouse.y = -1e4; }
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerdown', function (e) { if (e.pointerType !== 'mouse') { mouse.down = true; onPointerMove(e); } }, { passive: true });
    window.addEventListener('pointerup', function (e) { if (e.pointerType !== 'mouse') pointerOff(); }, { passive: true });
    window.addEventListener('pointercancel', pointerOff, { passive: true });
    window.addEventListener('blur', pointerOff);
    document.addEventListener('mouseleave', pointerOff);
    var scrollY = window.scrollY || 0, lastScrollY = scrollY, scrollEndTimer = 0;
    var smoothY = scrollY, scrollVel = 0, lastScrollAt = -1e9;   // eased scroll the sky follows
    window.addEventListener('scroll', function () {
        scrollY = window.scrollY || 0;
        lastScrollAt = performance.now();
        if (reduced) { clearTimeout(scrollEndTimer); scrollEndTimer = setTimeout(onScrollEnd, 180); }
    }, { passive: true });

    // ---- background slicer (long jobs in <= 4 ms steps) --------------------------
    function idle(fn) {
        if (window.requestIdleCallback) window.requestIdleCallback(fn, { timeout: 200 });
        else setTimeout(fn, 16);
    }
    function runSliced(step, done) {          // step() returns true when finished
        (function tick() {
            // A time budget AND a step cap: under a virtualised clock (headless
            // capture) performance.now() can stand still inside one task.
            var t0 = performance.now();
            for (var n = 0; n < 8 && (n === 0 || performance.now() - t0 < 4); n++) {
                if (step()) { if (done) done(); return; }
            }
            idle(tick);
        })();
    }

    // ---- text map: where page content is (replaces per-point elementFromPoint) ------
    var TEXT_SEL = 'h1,h2,h3,h4,h5,h6,p,li,dt,dd,blockquote,pre,table,figure,img,svg,video,iframe,' +
        'canvas:not(#particles-canvas),button,input,textarea,select,label,code,.mermaid,' +
        '[class*="card"],[class*="pill"],[class*="chip"],.spec-item,.code-window,.map-container,' +
        '#main-nav,nav,footer,.doc-sidebar,.page-toc,.hero-logo-wrap';
    var CONTAINER_SEL = '[class*="card"],[class*="pill"],.spec-item,table,pre,figure,nav,footer,' +
        '.doc-sidebar,.page-toc,.code-window,.map-container,.mermaid,svg';
    var rects = new Float32Array(0), nRects = 0, fixedEls = [], textReady = false, indexPending = false;
    var cols = 0, rows = 0, grid = new Uint8Array(0), gridScroll = -1e9, gridDirty = true;
    function buildIndex(done) {
        var els;
        try { els = document.querySelectorAll(TEXT_SEL); } catch (e) { els = []; }
        var n = els.length, i = 0, out = new Float32Array(n * 4), k = 0, fx = [];
        var sy = window.scrollY || 0;
        runSliced(function () {
            for (var c = 0; c < 120 && i < n; c++, i++) {
                var el = els[i];
                if (el === canvas) continue;
                var par = el.parentElement;
                if (par && par.closest && par.closest(CONTAINER_SEL)) continue;
                var r = el.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                if (el.matches && el.matches('#main-nav,nav,.doc-sidebar,.page-toc,header')) {
                    var pos = '';
                    try { pos = getComputedStyle(el).position; } catch (e) { pos = ''; }
                    if (pos === 'fixed' || pos === 'sticky') { fx.push(el); continue; }
                }
                out[k++] = r.left; out[k++] = r.top + sy; out[k++] = r.width; out[k++] = r.height;
            }
            return i >= n;
        }, function () {
            rects = out; nRects = k / 4; fixedEls = fx; textReady = true; gridDirty = true; measureDoc(); measureHero();
            if (done) done();
        });
    }
    var indexTimer = 0;
    function requestIndex() {
        clearTimeout(indexTimer);
        indexTimer = setTimeout(function () {
            if (indexPending) { requestIndex(); return; }
            indexPending = true;
            buildIndex(function () { indexPending = false; if (reduced) drawStill(); });
        }, 250);
    }
    function rebuildGrid() {
        measureNav();                                 // nav edge, read here (every 12 px / resize) not every tick
        var C = CFG.CELL;
        cols = Math.ceil(W / C) + 1; rows = Math.ceil(H / C) + 1;
        if (grid.length !== cols * rows) grid = new Uint8Array(cols * rows); else grid.fill(0);
        var sy = scrollY, pad = 8, i, x0, y0, x1, y1, cx, cy;
        function mark(l, t, w, h) {
            if (t + h + pad < 0 || t - pad > H || l + w + pad < 0 || l - pad > W) return;
            x0 = clamp(Math.floor((l - pad) / C), 0, cols - 1); x1 = clamp(Math.floor((l + w + pad) / C), 0, cols - 1);
            y0 = clamp(Math.floor((t - pad) / C), 0, rows - 1); y1 = clamp(Math.floor((t + h + pad) / C), 0, rows - 1);
            for (cy = y0; cy <= y1; cy++) for (cx = x0; cx <= x1; cx++) grid[cy * cols + cx] = 1;
        }
        for (i = 0; i < nRects; i++) mark(rects[i * 4], rects[i * 4 + 1] - sy, rects[i * 4 + 2], rects[i * 4 + 3]);
        for (i = 0; i < fixedEls.length; i++) {
            var r = fixedEls[i].getBoundingClientRect();
            if (r.width > 1 && r.height > 1) mark(r.left, r.top, r.width, r.height);
        }
        gridScroll = sy; gridDirty = false;
    }
    function occupied(x, y) {
        if (!textReady) return true;
        var cx = Math.floor(x / CFG.CELL), cy = Math.floor(y / CFG.CELL);
        if (cx < 0 || cy < 0 || cx >= cols || cy >= rows) return false;
        return grid[cy * cols + cx] === 1;
    }
    function occupancyIn(x0, y0, x1, y1) {
        if (!textReady) return 1;
        var C = CFG.CELL, a = clamp(Math.floor(x0 / C), 0, cols - 1), b = clamp(Math.floor(x1 / C), 0, cols - 1);
        var c = clamp(Math.floor(y0 / C), 0, rows - 1), d = clamp(Math.floor(y1 / C), 0, rows - 1), n = 0, f = 0;
        for (var y = c; y <= d; y++) for (var x = a; x <= b; x++) { n++; f += grid[y * cols + x]; }
        return n ? f / n : 0;
    }
    function freeDir(x, y, out) {               // unit vector toward empty space
        var C = CFG.CELL, bx = 0, by = 0;
        for (var dy = -3; dy <= 3; dy++) for (var dx = -3; dx <= 3; dx++) {
            if (!dx && !dy) continue;
            if (!occupied(x + dx * C, y + dy * C)) { var w = 1 / (dx * dx + dy * dy); bx += dx * w; by += dy * w; }
        }
        var m = Math.hypot(bx, by) || 1; out[0] = bx / m; out[1] = by / m;
        return out;
    }

    // ---- galaxy: gas ---------------------------------------------------------------
    // Polar textures (angle x radius): ARM and LANE ride the arm PATTERN, CLUMP and KNOT ride
    // the MATERIAL, which orbits faster inside (w(r) = K/(r+C)) and so passes through the arms;
    // FLOW is a streak texture in spiral coordinates (arm phase x log radius) that slides inward
    // along the arms. updateGas() composes them at the gas rate into gasCan through a per-pixel
    // LUT, so none of this is per-frame work. The arms trail the rotation.
    var A = CFG.POLAR_A, NR = CFG.POLAR_R, FA = CFG.FLOW_A, FU = CFG.FLOW_U;
    var ARM = new Uint8Array(A * NR), LANE = new Uint8Array(A * NR), CLUMP = new Uint8Array(A * NR),
        KNOT = new Uint8Array(A * NR), FLOW = new Uint8Array(FA * FU), gasReady = false, gasFade = 0;
    // updateGas reads finer copies: ARM/LANE and CLUMP/KNOT upsampled UP x in angle and radius,
    // bilinearly, once the gas is built (packed pairs, one read each). Read nearest, a cell must
    // stay under ~1 buffer px at the rim or its edges show as a zigzag along the arms: 4x for a
    // desktop's near-native buffer (up to 1400 px), 2x for a phone's (650). The coarse textures
    // stay for building, the stars and the knots
    var DESK = !!(window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches);
    var UP = DESK ? 4 : 2;
    var AF = A * UP, NRF = NR * UP, AFS = Math.round(Math.log2(AF));
    var AL16 = new Uint16Array(AF * NRF), CK16 = new Uint16Array(AF * NRF);
    var FLB = new Float32Array(NRF), FLK = new Float32Array(NRF);
    var ROWF_R = new Float32Array(NRF), ROWF_RGB = new Uint8Array(NRF * 3), ROWF_INV = new Float32Array(NRF);
    var ROW_R = new Float32Array(NR), ROW_RGB = new Uint8Array(NR * 3), ROW_INV = new Float32Array(NR);
    (function rowColors() {
        // warm core -> lavender -> indigo -> cyan rim
        var stops = [[0.00, 255, 226, 196], [0.07, 236, 196, 214], [0.16, 176, 146, 246], [0.30, 150, 132, 250],
                     [0.50, 99, 102, 241], [0.72, 34, 211, 238], [1.0, 110, 232, 249]];
        for (var j = 0; j < NR; j++) {
            var r = (j + 0.5) / NR, s = 0;
            ROW_R[j] = r;
            while (s < stops.length - 2 && r > stops[s + 1][0]) s++;
            var p = stops[s], q = stops[s + 1], t = smooth(p[0], q[0], r);
            ROW_RGB[j * 3] = lerp(p[1], q[1], t); ROW_RGB[j * 3 + 1] = lerp(p[2], q[2], t); ROW_RGB[j * 3 + 2] = lerp(p[3], q[3], t);
        }
    })();
    function matW(r) { return CFG.ORBIT_K / (r + CFG.ORBIT_C) - CFG.PATTERN_W; }   // material vs pattern (rad/s)
    // star-forming knots: small complexes of HII regions, fixed in the material frame
    var NK = 0, kR = new Float32Array(CFG.KNOTS), kA = new Float32Array(CFG.KNOTS), kAmp = new Float32Array(CFG.KNOTS);
    (function makeKnots() {
        for (var c = 0; NK < CFG.KNOTS; c++) {
            var r0 = 0.24 + 0.6 * Math.pow(R0(), 0.85), a0 = R0() * TAU, m = 1 + ((R0() * 3.2) | 0);
            for (var q = 0; q < m && NK < CFG.KNOTS; q++, NK++) {
                var r = clamp(r0 + gauss(R0) * 0.014, 0.2, 0.88), j = Math.min(NR - 1, (r * NR) | 0);
                kR[NK] = ROW_R[j];                         // on a row centre: sprite and texture orbit alike
                kA[NK] = a0 + gauss(R0) * 0.035 / r0; kAmp[NK] = 0.55 + 0.45 * R0();
            }
        }
    })();
    function splatKnots() {
        for (var k = 0; k < NK; k++) {
            var r = kR[k], sg = 0.0075 + 0.004 * kAmp[k], sa = sg / r;
            var j0 = Math.max(0, ((r - 3 * sg) * NR) | 0), j1 = Math.min(NR - 1, ((r + 3 * sg) * NR) | 0);
            var c = kA[k] / TAU * A, w = Math.ceil(3 * sa / TAU * A);
            for (var j = j0; j <= j1; j++) {
                var dr = (ROW_R[j] - r) / sg;
                for (var i = -w; i <= w; i++) {
                    var da = (i / A * TAU) / sa, col = (((Math.round(c) + i) % A) + A) % A;
                    var v = 255 * kAmp[k] * Math.exp(-0.5 * (dr * dr + da * da)), o = j * A + col;
                    KNOT[o] = Math.min(255, KNOT[o] + v);
                }
            }
        }
    }
    function pnoise(x, y, px, py) {                   // value noise that tiles with period (px, py)
        var xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
        var X0 = ((xi % px) + px) % px, Y0 = ((yi % py) + py) % py, X1 = (X0 + 1) % px, Y1 = (Y0 + 1) % py;
        var u = xf * xf * xf * (xf * (xf * 6 - 15) + 10), v = yf * yf * yf * (yf * (yf * 6 - 15) + 10);
        var a = VAL[PERM[PERM[X0] + Y0]], b = VAL[PERM[PERM[X1] + Y0]];
        var c = VAL[PERM[PERM[X0] + Y1]], d = VAL[PERM[PERM[X1] + Y1]];
        return lerp(lerp(a, b, u), lerp(c, d, u), v);
    }
    function buildGas() {
        if (NOGAL) { gasReady = true; return; }
        splatKnots();
        var j = 0, phase = 0;
        runSliced(function () {
            if (phase === 1) {                         // FLOW: streaks long along the arm, fine across it
                for (var n = 0; n < 2 && j < FU; n++, j++) {
                    for (var i = 0; i < FA; i++) {
                        var x = i / FA * 18, y = j / FU * 3, s = 0, amp = 0.5, f = 1;
                        for (var o = 0; o < 4; o++) { s += amp * pnoise(x * f, y * f, 18 * f, 3 * f); f *= 2; amp *= 0.5; }
                        FLOW[j * FA + i] = clamp(smooth(0.26, 0.80, s / 0.9375) * 255, 0, 255);
                    }
                }
                return j >= FU;
            }
            var r = ROW_R[j], disk = Math.exp(-r / 0.42), bulge = Math.exp(-r * r / 0.013);
            var lr = Math.log(r + 0.05), rowMax = 1, base = j * A;
            for (var i2 = 0; i2 < A; i2++) {
                var th = TAU * i2 / A, cx = r * Math.cos(th), cy = r * Math.sin(th);
                var n1 = fbm(cx * 3.2 + 11, cy * 3.2 + 7), n2 = fbm(cx * 7.5 + 31, cy * 7.5 + 3), n3 = noise(cx * 21 + 5, cy * 21 + 17);
                // the noise that shapes the arms eases off outward, so the outer spirals run on
                // as continuous arms instead of kinked, blotchy fragments
                var ro = smooth(0.40, 0.90, r), pa = lerp(0.60, 0.28, ro);
                var phi = th + CFG.PITCH * lr + (n1 - 0.5) * lerp(0.95, 0.45, ro);
                // a defined crest over a soft skirt: the arm reads sharp and still melts into the disk
                // (the outer arms keep their broader crest, so they stay a continuous band)
                var ca = 0.5 + 0.5 * Math.cos(2 * phi), arm = 0.72 * Math.pow(ca, lerp(4.5, 3, ro)) + 0.28 * Math.pow(ca, 1.4);
                // feathery spurs leaving the outer edge of each arm
                var spur = Math.pow(0.5 + 0.5 * Math.cos(2 * phi - 0.85 + (n2 - 0.5) * 2.2), 6) * smooth(0.28, 0.7, r) * smooth(0.45, 0.75, n2);
                arm = Math.max(arm, 0.5 * spur);
                // dust lane: a dark filament on the inner (concave) edge, rarely broken by noise
                var lane = Math.pow(0.5 + 0.5 * Math.cos(2 * (phi + 0.34)), 9) * smooth(0.09, 0.30, r) * (1 - smooth(0.78, 0.98, r)) *
                    smooth(0.15, 0.48, 0.6 * n2 + 0.4 * n3);
                var rimN = 1 - smooth(0.60, 1.0, r + (n1 - 0.5) * 0.16);
                var dens = 0.24 * bulge + disk * (0.07 + 0.93 * arm) * (1 - pa / 2 + pa * n2) * (0.85 + 0.85 * smooth(0.35, 0.8, r)) * (0.9 + 0.2 * n3);
                var av = clamp(dens * rimN * 255 * 1.35, 0, 255);
                ARM[base + i2] = av; if (av > rowMax) rowMax = av;
                LANE[base + i2] = clamp(lane * 255 * 1.35, 0, 255);
                var cl = smooth(0.56, 0.84, n2) * disk * (1 - smooth(0.70, 1.0, r)) * smooth(0.12, 0.3, r);
                CLUMP[base + i2] = clamp(cl * 255 * 2.2, 0, 255);
            }
            ROW_INV[j] = 1 / rowMax;
            if (++j >= NR) { phase = 1; j = 0; }
            return false;
        }, function () { upsampleGas(function () { gasReady = true; }); });
    }
    function upsampleGas(done) {                      // coarse -> fine, bilinear (angle wraps)
        var jf = 0;
        runSliced(function () {
            for (var n = 0; n < 12 / UP && jf < NRF; n++, jf++) {
                var y = clamp((jf + 0.5) / UP - 0.5, 0, NR - 1), j0 = y | 0, j1 = Math.min(NR - 1, j0 + 1), fy = y - j0;
                var r0 = j0 * A, r1 = j1 * A, out = jf * AF;
                ROWF_R[jf] = (jf + 0.5) / NRF;
                // the flow streaks' contrast, same mean (~0.75): full inside, gentler on the outer arms
                var fo = smooth(0.40, 0.90, ROWF_R[jf]);
                FLB[jf] = lerp(0.45, 0.62, fo); FLK[jf] = lerp(0.0023, 0.0016, fo);
                ROWF_INV[jf] = lerp(ROW_INV[j0], ROW_INV[j1], fy);
                for (var c = 0; c < 3; c++) ROWF_RGB[jf * 3 + c] = lerp(ROW_RGB[j0 * 3 + c], ROW_RGB[j1 * 3 + c], fy);
                for (var i = 0; i < AF; i++) {
                    var x = (i + 0.5) / UP - 0.5, i0 = Math.floor(x), fx = x - i0, a0 = (i0 + A) % A, a1 = (i0 + 1) % A;
                    var w00 = (1 - fx) * (1 - fy), w10 = fx * (1 - fy), w01 = (1 - fx) * fy, w11 = fx * fy;
                    var p00 = r0 + a0, p10 = r0 + a1, p01 = r1 + a0, p11 = r1 + a1;
                    var arm = ARM[p00] * w00 + ARM[p10] * w10 + ARM[p01] * w01 + ARM[p11] * w11;
                    var lane = LANE[p00] * w00 + LANE[p10] * w10 + LANE[p01] * w01 + LANE[p11] * w11;
                    var clump = CLUMP[p00] * w00 + CLUMP[p10] * w10 + CLUMP[p01] * w01 + CLUMP[p11] * w11;
                    var knot = KNOT[p00] * w00 + KNOT[p10] * w10 + KNOT[p01] * w01 + KNOT[p11] * w11;
                    AL16[out + i] = ((arm + 0.5) | 0) | (((lane + 0.5) | 0) << 8);
                    CK16[out + i] = ((clump + 0.5) | 0) | (((knot + 0.5) | 0) << 8);
                }
            }
            return jf >= NRF;
        }, done);
    }
    // two gas canvases: each refresh goes into the older one and becomes the current; on a large
    // buffer the previous one fades out under it (see gasMix)
    var gasCans = [document.createElement('canvas'), document.createElement('canvas')];
    var gasCtxs = [gasCans[0].getContext('2d'), gasCans[1].getContext('2d')], gasCur = 0;
    var gasCan = gasCans[0], gasCtx = gasCtxs[0], gasImg = null, gasU32 = null, gasPrevOK = false, gasBlank = true, gasPubT = -1e9;
    var S = 0, lutIdx = null, lutRC = null, lutEdge = null, lutFl = null, lutDith = null, lutN = 0;
    var haloCan = document.createElement('canvas'), haloCtx = haloCan.getContext('2d');
    var armShift = new Int32Array(NRF), clumpShift = new Int32Array(NRF), flowPhi = new Int32Array(NRF), rowGain = new Float32Array(NRF);
    var NEAR = new Float32Array(AF);
    // The buffer: a desktop draws it near its on-screen size (k 1, up to 1400 px: a 3440 px wide
    // screen stretched a 650 px buffer 3.2x and the gas read soft); a phone keeps 0.6 and 650.
    // Its LUT is built in slices while the old buffer keeps drawing, then swapped in whole
    var lutJob = 0, pendS = 0;
    function ensureGasBuffer() {
        if (NOGAL) return;
        var big = DESK && !small;
        var want = clamp(Math.round(2 * R * DPR * (big ? 1 : 0.6)), 192, big ? 1400 : 650), have = pendS || S;
        if (have && Math.abs(want - have) / have < 0.15) return;
        var job = ++lutJob, NS2 = want, max = NS2 * NS2, idx = new Uint32Array(max), rw = new Uint16Array(max), cl = new Uint16Array(max),
            ed = new Uint8Array(max), fl = new Uint32Array(max), di = new Uint8Array(max), n = 0, y = 0;
        pendS = NS2;
        runSliced(function () {
            if (job !== lutJob) return true;          // a newer size took over
            for (var rows = 0; rows < 24 && y < NS2; rows++, y++) lutRow(y);
            return y >= NS2;
        }, function () {
            if (job !== lutJob) return;
            var rc = new Uint32Array(n);
            for (var q = 0; q < n; q++) rc[q] = (rw[q] << AFS) | cl[q];   // row and column in one read
            S = NS2; pendS = 0;
            gasCans[0].width = gasCans[0].height = gasCans[1].width = gasCans[1].height = S;
            gasPrevOK = false; gasBlank = true;       // nothing at this size to fade from yet
            haloCan.width = haloCan.height = Math.max(32, S >> 2);
            gasImg = gasCtx.createImageData(S, S); gasU32 = new Uint32Array(gasImg.data.buffer);
            lutIdx = idx; lutRC = rc; lutEdge = ed; lutFl = fl; lutDith = di; lutN = n;
            gasPar = -1; gasP = gasEnd = 0;          // a refresh in flight was for the old LUT
            updateGas(T);                             // the new buffer is never shown empty
            if (reduced) drawStill();
        });
        function lutRow(y) {                          // one buffer row of the LUT
            for (var x = 0; x < NS2; x++) {
                var u = (x + 0.5) / NS2 * 2 - 1, v = (y + 0.5) / NS2 * 2 - 1, r = Math.sqrt(u * u + v * v);
                if (r >= 1) continue;
                var th = Math.atan2(v, u);
                // soft, slightly ragged rim: the disc dissolves instead of ending on a pixel circle
                var feather = 1 - smooth(0.78 + 0.06 * (noise(Math.cos(th) * 3 + 5, Math.sin(th) * 3 + 9) - 0.5), 1.0, r);
                if (feather <= 0.004) continue;
                idx[n] = y * NS2 + x; rw[n] = Math.min(NRF - 1, (r * NRF) | 0);
                cl[n] = ((((th / TAU) + 1) % 1) * AF) & (AF - 1); ed[n] = (feather * 255) | 0;
                var lr = Math.log(r + 0.05), ph = (th + CFG.PITCH * lr) / TAU;
                fl[n] = (((((lr + 3.1) / CFG.FLOW_TILE) % 1 + 1) % 1 * FU) & (FU - 1)) * FA + ((((ph % 1) + 1) % 1 * FA) & (FA - 1));
                di[n] = (((x * 0.7548776662 + y * 0.5698402910) % 1) * 255) | 0;   // ordered dither: no banding in faint gas
                n++;
            }
        }
    }
    // half: a running tick (not the still frame). It caps the flow clock's step, and on a phone
    // refreshes every other pixel in turn (see gasStep below).
    // gasFlow: the gas's own flow clock; on a running tick it follows G.flow but moves at most
    // GAS_FLOW_STEP, so a long gap between ticks never jumps the streaks.
    // A refresh is begun at the gas rate (gasBegin: every per-row term fixed for it) and run in
    // slices over the frames that follow (gasRun), into the ImageData; only a finished refresh is
    // put to gasCan, so the gas always changes whole - no seams, no comb - and a 1400 px buffer
    // costs ~1 ms a frame instead of one 20 ms frame
    var gasPar = 0, gasFlow = 0, gasFlowSeen = -1, GAS_FLOW_STEP = 0.3;
    var gasP = 0, gasEnd = 0, gasStep = 1, gasFuR = 0;
    function updateGas(t, half) { if (gasBegin(t, half)) gasRun(lutN); }   // a whole refresh at once
    function gasBegin(t, half) {
        if (!gasReady || !lutN) return false;
        var breath = Math.sin(TAU * t / CFG.BREATH_T), twist = CFG.TWIST_A * Math.sin(TAU * t / CFG.TWIST_T);
        var k = AF / TAU, j, c;
        for (j = 0; j < NRF; j++) {
            var r = ROWF_R[j];
            armShift[j] = Math.round(twist * (r - 0.4) * k);
            flowPhi[j] = ((Math.round(twist * (r - 0.4) / TAU * FA) % FA) + FA) % FA;
            // the material overtakes the pattern, most inside; at the coarse row's radius, which the
            // knot sprites sit on, so sprite and texture still orbit alike
            var rel = matW(ROW_R[(j / UP) | 0]) * t;
            clumpShift[j] = Math.round(((rel % TAU) + TAU) * k);
            rowGain[j] = (1 + 0.14 * breath * Math.exp(-r / 0.14)) * (0.93 + 0.07 * Math.sin(t * 0.37 + r * 4));
        }
        // near side of the tilted disk (screen-down): dust lanes darker, glow a touch dimmer
        for (c = 0; c < AF; c++) NEAR[c] = Math.sin(TAU * c / AF + G.rot);
        var dfl = gasFlowSeen < 0 ? 0 : G.flow - gasFlowSeen;
        gasFlowSeen = G.flow;
        gasFlow += half && gasPar >= 0 ? Math.min(dfl, GAS_FLOW_STEP) : dfl;
        var fuS = Math.round(gasFlow * CFG.FLOW_V / CFG.FLOW_TILE * FU) & (FU - 1);   // the gas clock: faster while it spins
        gasFuR = fuS * FA;
        if (gasPar < 0) half = false;              // a new buffer is filled whole first
        // every pixel, every refresh. Refreshing every 2nd/3rd pixel in turn left neighbours a tick
        // or two apart while the gas moved, a 1 px comb along every edge that the stretched buffer
        // showed as a zigzag on large screens. A phone keeps the half refresh: its buffer is
        // barely stretched (no visible comb) and its CPU is the one that needs the saving
        gasStep = half && small ? 2 : 1;
        gasPar = gasPar < 0 ? 0 : (gasPar + 1) % gasStep;
        gasP = gasPar; gasEnd = lutN;
        return true;
    }
    // A large (desktop) buffer is ~4x the pixels: it refreshes at half the rate, and each refresh
    // fades in over the next period on top of the one before (gasMix), so the gas moves on
    // continuously instead of stepping, at about twice the old 650 px buffer's script cost
    function gasRate() { return S > 700 ? gasHz / 2 : gasHz; }
    function gasMix() { return gasPrevOK && S > 700 && !reduced ? clamp((T - gasPubT) * gasRate(), 0, 1) : 1; }
    function gasRun(budget) {
        if (gasP >= gasEnd) return;
        var j, step = gasStep, stop = Math.min(gasEnd, gasP + budget * step), fuR = gasFuR;
        // flowPhi holds the column (arm phase) offset only, wrapped inside its row; the inflow is
        // a whole-row offset (a multiple of FA), so neither carries into the other
        var m = AF - 1, flm = FA * FU - 1, fam = FA - 1, frm = flm & ~fam, i255 = 1 / 255;
        // closure arrays into locals: the hot loop then reads registers, not context slots
        var LRC = lutRC, LFL = lutFl, LED = lutEdge, LDI = lutDith, LIX = lutIdx, AL = AL16, CK = CK16, FLW = FLOW,
            NE = NEAR, ASH = armShift, CSH = clumpShift, FPH = flowPhi, RG = rowGain, RI = ROWF_INV, RGB = ROWF_RGB, OUT = gasU32, FB = FLB, FK = FLK;
        for (var p = gasP; p < stop; p += step) {
            var rc = LRC[p], c0 = rc & m;
            j = rc >>> AFS;
            var row = j * AF, al2 = AL[row + ((c0 + ASH[j]) & m)], a = al2 & 255;
            if (a < 2) { OUT[LIX[p]] = 0; continue; }
            var nr = NE[c0], ln = al2 >>> 8;
            var dust = ln ? 1 - ln * (0.0034 + 0.0005 * nr) : 1;
            var lf = LFL[p], al = a * dust * (FB[j] + FK[j] * FLW[((lf + FPH[j]) & fam) | ((lf + fuR) & frm)]), j3 = j * 3;
            var R8 = RGB[j3], G8 = RGB[j3 + 1], B8 = RGB[j3 + 2];
            var ck = CK[row + ((c0 - CSH[j]) & m)];
            if (ck) {
                var cv = ck & 255, kv = ck >>> 8;
                var g = a * RI[j];                      // 0..1: how deep in the arm this point is
                if (cv) {
                    var ce = cv * (0.15 + 0.85 * g) * dust, f = ce * 0.0022;
                    al += ce * 0.6;
                    R8 += (225 - R8) * f; G8 += (230 - G8) * f; B8 += (255 - B8) * f;
                }
                if (kv) {                               // HII: rose
                    var ke = kv * g * g, kr = ke * 0.0052;
                    if (kr > 0.85) kr = 0.85;
                    al += ke * 0.75;
                    R8 += (252 - R8) * kr; G8 += (112 - G8) * kr; B8 += (150 - B8) * kr;
                }
            }
            al = al * RG[j] * (1 - 0.08 * nr) * LED[p] * i255 + LDI[p] * i255;
            if (al < 1) { OUT[LIX[p]] = 0; continue; }
            OUT[LIX[p]] = ((al > 255 ? 255 : al) << 24) | ((B8 & 255) << 16) | ((G8 & 255) << 8) | (R8 & 255);
        }
        gasP = p;
        if (gasP < gasEnd) return;
        // publish: the older canvas takes the new gas, the current one becomes the fading previous
        gasCur ^= 1; gasCan = gasCans[gasCur]; gasCtx = gasCtxs[gasCur];
        gasPrevOK = !gasBlank; gasBlank = false; gasPubT = T;
        gasCtx.putImageData(gasImg, 0, 0);
        // soft glow around the arms: a quarter-resolution copy blended back into the buffer,
        // here at the gas rate instead of as a second full-size draw every frame
        haloCtx.clearRect(0, 0, haloCan.width, haloCan.height);
        haloCtx.drawImage(gasCan, 0, 0, haloCan.width, haloCan.height);
        gasCtx.globalCompositeOperation = 'lighter'; gasCtx.globalAlpha = 0.30;
        gasCtx.drawImage(haloCan, 0, 0, S, S);
        gasCtx.globalCompositeOperation = 'source-over'; gasCtx.globalAlpha = 1;
    }

    // ---- galaxy: stars (typed arrays) ----------------------------------------------
    // kinds: 0 bulge, 1 arm (streams inward along the arm), 2 disk, 3 halo, 4 knot (HII, first NK)
    var NS = 0, sKind, sR, sTh, sOff, sZ, sSize, sAlpha, sTw, sTwA, sPh, sCol, sFade, sX, sY, sDX, sDY, sBucket, nDraw = 0;
    var kArm = new Float32Array(CFG.KNOTS), kFlT = new Float32Array(CFG.KNOTS), kNext = new Float32Array(CFG.KNOTS), kFl = new Float32Array(CFG.KNOTS);
    var bkStart = null, bkFill = null, bkOrder = null;          // drawGalaxy's per-bucket index lists
    // bulge warm, arm blue-white, disk white, rose giant, HII rose, halo grey-lilac, young cyan-white
    var STAR_RGB = ['255,226,192', '196,214,255', '232,234,255', '255,170,196', '255,138,172', '208,202,232', '190,242,252'];
    var ALEVELS = 6, BUCKET_STYLE = [];
    for (var ci = 0; ci < STAR_RGB.length; ci++) for (var ai = 0; ai < ALEVELS; ai++) {
        BUCKET_STYLE.push('rgba(' + STAR_RGB[ci] + ',' + (((ai + 1) / ALEVELS) * CFG.STAR_ALPHA).toFixed(3) + ')');
    }
    // ---- galaxy: bytes (the Data Galaxy) ----------------------------------------------
    // The galaxy is the digital space, so its arms are made of data. A share of the arm stars
    // (crest-weighted) resolves into byte cells as it streams inward past its own radius sBy,
    // so the inner disk and the arm crests read as data while the rim stays stars; a sparse
    // ring of cream bytes orbits just outside the bulge. Same particles, re-skinned: none are
    // added. Every byte is a square cap. Near side of the tilted disk: crisp, a hot core on the
    // bright ones; the far side and the core haze: softer - fainter, a little larger, over one
    // dim square 1.2 px wider (desktop at gov 0; flat caps elsewhere). The arm bytes draw
    // inside the stars' own bucket paths (no extra fill); only cream / cyan / rose / lime get
    // their own three-level paths. Each byte re-rolls its value 0.6-2.2 times a second, a
    // +-9% shimmer (cp-docs' rate, under the 3 Hz rule). Read currents, 2-3 at once, run out
    // (reading) and in (condensing toward the core) along the arms, a new one every 3-5 s; a
    // slow swell of byte brightness turns around the disk; every 20-25 s one byte is found
    // (rose), lifts, a rose wave and then a lime wave run through its neighbours' tint. No gas
    // yet (or faded): no bytes.
    var RB = rng(0xB17E5);                           // byte choices: the galaxy's own R0 sequence is untouched
    var B_ARM = 1;                                   // STAR_RGB index the arm bytes draw with (196,214,255)
    // special tints: cream (the ring by the bulge), cyan (being read), rose (found), lime (understood)
    var SP_RGB = ['243,230,207', '103,232,249', '251,113,133', '190,242,100'], SLV = 3, SP_STYLE = [];
    for (ci = 0; ci < SP_RGB.length; ci++) for (ai = 0; ai < SLV; ai++) {
        SP_STYLE.push('rgba(' + SP_RGB[ci] + ',' + (((ai + 1) / SLV) * 0.9).toFixed(3) + ')');
    }
    var NBS = BUCKET_STYLE.length, NBT = NBS + SP_STYLE.length;   // bucket keys: stars and arm bytes < NBS <= special < NBT
    function headSprite(rgb) {                       // as cp-docs.js capSprite level 0: a crisp core with a short skirt
        var c = document.createElement('canvas');
        c.width = c.height = 24;
        var g = c.getContext('2d'), h = 12, gr = g.createRadialGradient(h, h, 0, h, h, h);
        gr.addColorStop(0, 'rgba(255,255,255,0.95)');
        gr.addColorStop(0.14, 'rgba(' + rgb + ',0.95)');
        gr.addColorStop(0.3, 'rgba(' + rgb + ',0.32)');
        gr.addColorStop(0.62, 'rgba(' + rgb + ',0.05)');
        gr.addColorStop(1, 'rgba(' + rgb + ',0)');
        g.fillStyle = gr; g.fillRect(0, 0, 24, 24);
        return c;
    }
    var HEAD = headSprite(SP_RGB[1]);                 // the read current's head (8 px)
    // per particle: sBy resolve radius (0 never, 9 always), sZb cell size, sFr/sFp flicker rate
    // and phase, sBOff phase offset along the arm, sArm arm (-1 none), sDev offset from the arm
    // crest; per frame: sM byte mix (before the frame's gas/governor factor), sCur the read
    // current, sSn/sPu/sPw/sFE the projection and alpha factor the star loop hands the byte
    // pass, sBB/sBK the byte's and its soft skirt's bucket (255 none, 254 the finding), sBz the
    // cap size, sHot its hot core; sFn/sFv the flicker slot and value
    var sFn, sFv, sBy, sZb, sFr, sFp, sBOff, sArm, sDev, sM, sCur, sSn, sPu, sPw, sFE, sBB, sBK, sBz, sHot;
    var AIDX = null, nAI = 0, bList = null, nB = 0, bytesK = 1, mK = 0, skinDue = 0;
    var hbx0 = 0, hby0 = 0, hbx1 = 0, hby1 = 0, hbSY = -1;   // the hero copy's box (screen, padded): heroFade only inside it
    function placeArmStar(i, rim) {
        sR[i] = rim ? 0.86 + R0() * 0.06 : 0.08 + Math.pow(R0(), 0.8) * 0.84;
        // just downstream of the dust lane, where the young stars are
        sOff[i] = (R0() < 0.5 ? 0 : Math.PI) + 0.06 + gauss(R0) * 0.20;
        sFade[i] = rim ? 0 : 1;
        var arm = sOff[i] > 1.57 ? 1 : 0, dev = sOff[i] - 0.06 - arm * Math.PI;
        sArm[i] = arm; sDev[i] = dev;
        // crest-weighted: about 55% of arm stars (33% on a phone) may become bytes, each once it is inside its radius
        sBy[i] = RB() < (small ? 0.55 : 0.92) * Math.exp(-dev * dev / 0.0512) ? 0.45 + 0.53 * RB() : 0;   // a phone: fewer, it is a small disk
        sM[i] = 0; sCur[i] = 0;
    }
    function buildStars() {
        NS = NK + (small ? CFG.STARS_SMALL : CFG.STARS);
        sKind = new Uint8Array(NS); sR = new Float32Array(NS); sTh = new Float32Array(NS); sOff = new Float32Array(NS);
        sZ = new Float32Array(NS); sSize = new Float32Array(NS); sAlpha = new Float32Array(NS); sTw = new Float32Array(NS);
        sTwA = new Float32Array(NS); sPh = new Float32Array(NS); sCol = new Uint8Array(NS); sFade = new Float32Array(NS);
        sX = new Float32Array(NS); sY = new Float32Array(NS); sDX = new Float32Array(NS); sDY = new Float32Array(NS); sBucket = new Uint8Array(NS);
        sBy = new Float32Array(NS); sZb = new Float32Array(NS); sFr = new Float32Array(NS);
        sFp = new Float32Array(NS); sBOff = new Float32Array(NS); sArm = new Int8Array(NS); sDev = new Float32Array(NS);
        sM = new Float32Array(NS); sCur = new Float32Array(NS); sSn = new Float32Array(NS); sPu = new Float32Array(NS);
        sPw = new Float32Array(NS); sFE = new Float32Array(NS); sBB = new Uint8Array(NS); sBK = new Uint8Array(NS);
        sBz = new Float32Array(NS); sHot = new Uint8Array(NS); sFn = new Int32Array(NS); sFv = new Float32Array(NS);
        sFn.fill(-1); sBB.fill(255); sBK.fill(255);
        sArm.fill(-1); fI = -1;
        for (var i = 0; i < NS; i++) {
            if (i < NK) {                              // HII knots lead the array: the governor never drops them
                sKind[i] = 4; sR[i] = kR[i]; sOff[i] = kA[i]; sCol[i] = 4; sFade[i] = 1; sZ[i] = gauss(R0) * 0.006;
                sSize[i] = 0.9 + 0.3 * kAmp[i]; sAlpha[i] = 0.8; sTw[i] = 0.5 + R0(); sTwA[i] = 0.1; sPh[i] = R0() * TAU;
                kFlT[i] = -1e4; kNext[i] = 4 + R0() * 40; kArm[i] = 0;
                continue;
            }
            var u = R0();
            if (u < 0.11) {                            // bulge: a puffy spheroid
                sKind[i] = 0; sR[i] = 0.015 + Math.abs(gauss(R0)) * 0.085; sTh[i] = R0() * TAU; sCol[i] = 0; sFade[i] = 0.6;
                sZ[i] = gauss(R0) * 0.045 * (1.2 - sR[i] * 4);
            } else if (u < 0.68) {
                sKind[i] = 1; placeArmStar(i, false); var cu = R0(); sCol[i] = cu < 0.10 ? 3 : cu < 0.26 ? 6 : 1;
                sZ[i] = gauss(R0) * 0.012;
            } else if (u < 0.95) {
                sKind[i] = 2; sR[i] = Math.min(0.95, -Math.log(1 - R0()) * 0.27); sTh[i] = R0() * TAU; sCol[i] = 2; sFade[i] = 1;
                sZ[i] = gauss(R0) * 0.022;
            } else {                                   // sparse old halo
                sKind[i] = 3; sR[i] = 0.35 + Math.pow(R0(), 0.7) * 1.0; sTh[i] = R0() * TAU; sCol[i] = 5; sFade[i] = 0.55;
                sZ[i] = gauss(R0) * 0.40;
            }
            var z = R0();
            sSize[i] = z < 0.025 ? 2.05 + R0() * 0.4 : z < 0.12 ? 1.3 + R0() * 0.3 : 0.55 + R0() * 0.7;
            sAlpha[i] = sSize[i] > 1.3 ? 0.7 + R0() * 0.3 : 0.28 + R0() * 0.62;
            if (sKind[i] === 3) { sSize[i] = Math.min(sSize[i], 1.2); sAlpha[i] *= 0.7; }
            sTw[i] = 0.5 + R0() * 2.0; sTwA[i] = R0() < 0.18 ? 0.34 : 0.12; sPh[i] = R0() * TAU;
        }
        // byte skins, from RB only. A sparse ring of disk stars moves just outside the bulge
        // and is always a byte: the centre reads as where the data condenses
        nAI = 0; AIDX = new Uint16Array(NS);
        for (i = NK; i < NS; i++) {
            if (sKind[i] === 2 && RB() < 0.06) {
                sR[i] = 0.155 + 0.07 * RB(); sZ[i] = gauss(RB) * 0.006; sBy[i] = 9; sM[i] = 1;
                sAlpha[i] = Math.max(sAlpha[i], 0.4 + 0.2 * RB());
            }
            if (sKind[i] === 1) AIDX[nAI++] = i;      // arm stars: their mix is refreshed per frame (they stream, respawn, get read)
            sZb[i] = clamp(1.6 + 0.85 * sSize[i], 1.8, 3.4) * (small ? 0.86 : 1);
            sFr[i] = 0.6 + 1.6 * RB(); sFp[i] = RB() * 64; sBOff[i] = (RB() - 0.5) * 0.08;
        }
        nDraw = NS;
    }
    var GLINT = document.createElement('canvas');
    (function () {
        GLINT.width = GLINT.height = 48;
        var g = GLINT.getContext('2d');
        [[48, 2.2], [2.2, 48]].forEach(function (d) {
            var gr = d[0] > d[1] ? g.createLinearGradient(0, 24, 48, 24) : g.createLinearGradient(24, 0, 24, 48);
            gr.addColorStop(0, 'rgba(220,230,255,0)'); gr.addColorStop(0.5, 'rgba(240,245,255,0.9)'); gr.addColorStop(1, 'rgba(220,230,255,0)');
            g.fillStyle = gr; g.fillRect(24 - d[0] / 2, 24 - d[1] / 2, d[0], d[1]);
        });
    })();
    // the core: warm nucleus -> cream -> lilac -> indigo, compact (no wide halo)
    var BLOOM = document.createElement('canvas');
    (function () {
        BLOOM.width = BLOOM.height = 256;           // drawn ~600 px wide on a large screen
        var g = BLOOM.getContext('2d'), gr = g.createRadialGradient(128, 128, 0, 128, 128, 128);
        gr.addColorStop(0, 'rgba(255,246,232,1)'); gr.addColorStop(0.06, 'rgba(255,232,206,0.82)');
        gr.addColorStop(0.18, 'rgba(250,206,196,0.40)'); gr.addColorStop(0.36, 'rgba(196,170,250,0.16)');
        gr.addColorStop(0.62, 'rgba(129,140,248,0.05)'); gr.addColorStop(1, 'rgba(99,102,241,0)');
        g.fillStyle = gr; g.fillRect(0, 0, 256, 256);
    })();
    var GLOW = document.createElement('canvas');
    (function () {
        GLOW.width = GLOW.height = 32;
        var g = GLOW.getContext('2d'), gr = g.createRadialGradient(16, 16, 0, 16, 16, 16);
        gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.25, 'rgba(205,222,255,0.55)');
        gr.addColorStop(1, 'rgba(205,222,255,0)');
        g.fillStyle = gr; g.fillRect(0, 0, 32, 32);
    })();
    var KGLOW = document.createElement('canvas');      // an HII knot: a small rose bead
    (function () {
        KGLOW.width = KGLOW.height = 32;
        var g = KGLOW.getContext('2d'), gr = g.createRadialGradient(16, 16, 0, 16, 16, 16);
        gr.addColorStop(0, 'rgba(255,236,242,1)'); gr.addColorStop(0.16, 'rgba(255,150,182,0.75)');
        gr.addColorStop(0.42, 'rgba(244,63,94,0.22)'); gr.addColorStop(1, 'rgba(244,63,94,0)');
        g.fillStyle = gr; g.fillRect(0, 0, 32, 32);
    })();
    // Round stars are a disc sprite per fill style, drawn with drawImage; square ones fillRect.
    // Hundreds of arcs/rects gathered into one path per bucket and filled at once made the GPU
    // cover the whole path's bounds per fill: on a 3440 px wide screen that alone held the sky
    // to ~30 fps (33 ms frames, 6 of every 8 s in raster) and the native scroll juddered against
    // it. Sprites and rects batch into a few quads (5.6 ms frames on the same screen)
    var DOTS = {};
    function dot(style) {
        var c = DOTS[style];
        if (!c) {
            c = DOTS[style] = document.createElement('canvas');
            c.width = c.height = 16;
            var g = c.getContext('2d');
            g.fillStyle = style; g.beginPath(); g.arc(8, 8, 8, 0, TAU); g.fill();
        }
        return c;
    }
    // Each gives off the light the path fill did, so the sky looks as before. The path covered a
    // sub-pixel square ~1/1.35 of what fillRect does (-> 1/1.02 at 4 px), and a disc under
    // r 0.62 about half its area; measured, CPU and GPU raster alike. The caller sets fillStyle
    function square(x, y, z, ga) {
        ctx.globalAlpha = ga / (1 + 0.35 / Math.max(1, z * z));
        ctx.fillRect(x - z / 2, y - z / 2, z, z);
    }
    function disc(style, x, y, r, ga) {
        if (r < 0.75) {                                 // too small for the sprite: a square of its area
            ctx.globalAlpha = ga * (r <= 0.62 ? 0.49 : r >= 0.7 ? 0.735 : 0.49 + (r - 0.62) * 3.06);
            var s = r * 1.7725;
            ctx.fillRect(x - s / 2, y - s / 2, s, s);
        } else {
            ctx.globalAlpha = ga * 0.95;
            ctx.drawImage(dot(style), x - r, y - r, r * 2, r * 2);
        }
    }

    // ---- galaxy: motion ------------------------------------------------------------
    // spin/spinV: kept at 0 (scrolling used to spin the disk up; it no longer moves it at all);
    // focus/focusV: how far the galaxy is in focus (scrolling up brings it
    // forward), fWant the last scroll direction's wish, swell the core's arrival swell at the top;
    // flow is the gas clock, which runs faster along the arms while the galaxy spins. carry stays
    // 0 (the galaxy no longer drifts with the page) for its readers
    var G = { x: 0, y: 0, vx: 0, vy: 0, carry: 0, rot: 0, spin: 0, spinV: 0, focus: 1, focusV: 0, fWant: 0, swell: 0, home: true, flow: 30, incl: 0.5, pa: -0.45, ph: 0, placed: false, dim: 1, alpha: 0 };
    var T = 30, stepDt = 1 / 30;                    // sky clock (s), the last step's length
    var NAV = document.getElementById('main-nav'), navB = 0;
    function measureNav() {
        if (!NAV) { navB = 0; return; }
        var r = NAV.getBoundingClientRect();
        navB = r.bottom > 0 && r.bottom < H * 0.4 ? r.bottom : 0;
    }
    function navBottom() { return navB; }
    // hero copy (title, subtitle, actions, scroll cue) in document coordinates, read with the
    // text index (load / resize), not per frame: the core dims while it sits behind them
    var heroR = new Float32Array(16), nHero = 0, gAtt = 1;
    function measureHero() {
        nHero = 0; hbSY = -1;
        if (NOGAL) return;
        var els;
        try { els = document.querySelectorAll('.hero-title,.hero-sub,.hero-actions,.scroll-hint'); } catch (e) { return; }
        var sy = window.scrollY || 0;
        for (var i = 0; i < els.length && nHero < 4; i++) {
            var r = els[i].getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            heroR[nHero * 4] = r.left; heroR[nHero * 4 + 1] = r.top + sy;
            heroR[nHero * 4 + 2] = r.right; heroR[nHero * 4 + 3] = r.bottom + sy; nHero++;
        }
    }
    function behindHero(x, y) {                     // screen point within 0.35 R of the hero copy
        var pd = 0.35 * R, yd = y + scrollY;
        for (var h = 0; h < nHero; h++) {
            var o = h * 4;
            if (x > heroR[o] - pd && x < heroR[o + 2] + pd && yd > heroR[o + 1] - pd && yd < heroR[o + 3] + pd) return true;
        }
        return false;
    }
    function heroBox() {
        hbx0 = hby0 = 1e9; hbx1 = hby1 = -1e9;
        var pd = 0.12 * R;
        for (var h = 0; h < nHero; h++) {
            var o = h * 4;
            if (heroR[o] - pd < hbx0) hbx0 = heroR[o] - pd;
            if (heroR[o + 2] + pd > hbx1) hbx1 = heroR[o + 2] + pd;
            if (heroR[o + 1] - pd - scrollY < hby0) hby0 = heroR[o + 1] - pd - scrollY;
            if (heroR[o + 3] + pd - scrollY > hby1) hby1 = heroR[o + 3] + pd - scrollY;
        }
    }
    function heroFade(x, y) {                       // bytes dim behind the hero copy: 0.4 inside, eased to 1 at 0.12 R
        if (!nHero) return 1;
        var pd = 0.12 * R, yd = y + scrollY, f = 1;
        for (var h = 0; h < nHero; h++) {
            var o = h * 4, dx = heroR[o] - x, dy = heroR[o + 1] - yd, ex = x - heroR[o + 2], ey = yd - heroR[o + 3];
            dx = dx > ex ? dx : ex; dy = dy > ey ? dy : ey;
            if (dx >= pd || dy >= pd) continue;
            dx = dx > 0 ? dx : 0; dy = dy > 0 ? dy : 0;
            var d = Math.sqrt(dx * dx + dy * dy);
            if (d >= pd) continue;
            var g = d / pd; g = g * g * (3 - 2 * g);
            if (g < f) f = g;
        }
        return 0.4 + 0.6 * f;
    }
    if (NAV) NAV.addEventListener('transitionend', function () { gridDirty = true; });
    var docH = 1, gmx = 0, gmy = 0;
    function measureDoc() { docH = Math.max(1, (document.documentElement.scrollHeight || H) - H); }
    function galaxyTarget(t, out) {                  // slow figure-eight across the screen, on time only:
        // scrolling never moves the galaxy (it used to shift the phase with the scroll fraction)
        // the roam narrows as the disk grows, so the larger galaxy is never pushed far off-screen
        var ax = clamp(0.36 - 0.16 * R / W, 0.2, 0.32), ay = clamp(0.30 - 0.14 * R / H, 0.16, 0.25);
        out[0] = W * (0.5 + ax * Math.sin(t / 240)) + gmx * 30;
        out[1] = H * (0.5 + ay * Math.sin(t / 180 + 1.1)) + gmy * 20;
        return out;
    }
    function focusWant() { return Math.max(G.fWant, 1 - smooth(0, 0.7 * H, scrollY)); }   // the top is always in focus
    var TMP = [0, 0];
    function placeGalaxy() {
        if (NOGAL) { measureDoc(); readGlobe(); return; }
        measureDoc();
        galaxyTarget(T, TMP);
        G.x = TMP[0]; G.y = TMP[1]; G.vx = G.vy = 0; G.placed = true;
        G.focus = focusWant(); G.focusV = 0; G.home = scrollY < 0.3 * H;
    }
    function readGlobe() {                          // NOGAL: the galaxy's place is the globe's
        var d = GLOBE && GLOBE.dataset;
        if (d && d.r) { G.x = +d.cx; G.y = +d.cy; GLOBE_R = +d.r * 0.85; }
        else { G.x = -1e5; G.y = -1e5; GLOBE_R = 1; }
        G.carry = 0; G.placed = true;
    }
    function galaxyDist(x, y) {                     // distance in the tilted disk, in units of R
        if (NOGAL) return Math.hypot(x - G.x, y - G.y) / GLOBE_R;
        var dx = x - G.x, dy = y - (G.y + G.carry), c = Math.cos(-G.pa), s = Math.sin(-G.pa);
        var u = dx * c - dy * s, v = (dx * s + dy * c) / G.incl;
        return Math.sqrt(u * u + v * v) / R;
    }
    function stepGalaxy(dt, dScroll) {
        if (NOGAL) { readGlobe(); return; }
        var tmx = mouse.on && mouse.mouse ? mouse.x / W - 0.5 : 0, tmy = mouse.on && mouse.mouse ? mouse.y / H - 0.5 : 0;
        gmx += (tmx - gmx) * Math.min(1, dt * 1.2); gmy += (tmy - gmy) * Math.min(1, dt * 1.2);
        galaxyTarget(T, TMP);
        var om = 0.35;
        G.vx += (om * om * (TMP[0] - G.x) - 2 * om * G.vx) * dt;
        G.vy += (om * om * (TMP[1] - G.y) - 2 * om * G.vy) * dt;
        G.x += G.vx * dt; G.y += G.vy * dt;
        // The galaxy holds its place while the page scrolls: no carry, no sway, no scroll term in
        // the roam. What scrolling changes is focus - light and depth, never position. Scrolling up
        // brings it forward (brighter, the sky around it softens), scrolling down lets it
        // step back; between the thresholds the last direction holds, so a pause doesn't flicker.
        // A critically damped spring, quicker into focus (~1 s) than out of it
        if (scrollVel < -120) G.fWant = 1; else if (scrollVel > 120) G.fWant = 0;
        var fw = focusWant(), fn = fw > G.focus ? 2.2 : 1.4;
        G.focusV += (fn * fn * (fw - G.focus) - 2 * fn * G.focusV) * dt;
        G.focus = clamp(G.focus + G.focusV * dt, 0, 1);
        if (dt <= 0) { G.focus = fw; G.focusV = 0; }          // the still frame snaps
        // arriving back at the top while moving up: the core swells once (1.4 s)
        if (!G.home && scrollY < 0.15 * H && scrollVel < -60) { G.home = true; G.swell = 1; }
        else if (scrollY > 0.3 * H) G.home = false;
        G.swell = Math.max(0, G.swell - dt / 1.4);
        // spin: scrolling no longer spins the galaxy up (nor streaks its stars) - it turns at its
        // own pace whatever the page does. G.spin stays 0 for the readers that scale with it
        G.spin = 0; G.spinV = 0;
        var aSpin = Math.abs(G.spin);
        G.rot += dt * (CFG.PATTERN_W + CFG.SPIN_MAX * G.spin);
        G.flow += dt * (1 + 2.4 * aSpin);
        // slow precession: the disk's axis walks a small cone (tilt and position angle together)
        var pr = TAU * T / CFG.PRECESS_T;
        G.incl = Math.max(0.3, 0.50 + 0.065 * Math.cos(pr) - 0.10 * gmy);
        G.pa = -0.45 + 0.10 * Math.sin(pr) + 0.18 * gmx + clamp(0.0008 * G.vx, -0.25, 0.25);
        G.alpha = Math.min(1, G.alpha + dt / 1.5);
        var attW = behindHero(G.x, G.y + G.carry) ? 0.6 : 1;   // eased over ~1 s; the still frame snaps
        gAtt = dt > 0 ? gAtt + (attW - gAtt) * (1 - Math.exp(-dt * 2.5)) : attW;
        // stars
        var twist = CFG.TWIST_A * Math.sin(TAU * T / CFG.TWIST_T), i, r;
        for (i = 0; i < NS; i++) {
            var k = sKind[i];
            r = sR[i];
            if (k === 1) {
                r -= r * CFG.STREAM * dt * (1 + 2.4 * aSpin);   // the arms stream faster while it spins
                if (r < 0.07) { placeArmStar(i, true); r = sR[i]; }
                sR[i] = r;
                sFade[i] = Math.min(1, sFade[i] + dt / 2);
                sTh[i] = sOff[i] - CFG.PITCH * Math.log(r + 0.05) - twist * (r - 0.4);
            } else if (k === 4) {
                sTh[i] = (sOff[i] + matW(r) * T) % TAU;  // orbits with the knot texture exactly
            } else {
                sTh[i] += (k === 3 ? 0.35 : 1) * matW(r) * dt;
            }
        }
        // knots light up while their gas crosses an arm; now and then one flares
        var kk = A / TAU;
        for (i = 0; i < NK; i++) {
            r = sR[i];
            var j = Math.min(NR - 1, (r * NR) | 0), col = Math.round(sTh[i] * kk + armShift[j]) & (A - 1);
            var g = smooth(0.30, 0.76, ARM[j * A + col] * ROW_INV[j]);
            kArm[i] += (g - kArm[i]) * Math.min(1, dt * 1.5);
            if (T >= kNext[i]) {
                if (kArm[i] > 0.55) { kFlT[i] = T; kNext[i] = T + 35 + RND() * 80; } else kNext[i] = T + 2 + RND() * 6;
            }
            var e = T - kFlT[i];
            kFl[i] = e < 0 || e > 8 ? 0 : e < 0.6 ? ease(e / 0.6) : Math.exp(-(e - 0.6) / 1.5);
        }
    }
    // ---- galaxy events: the read currents, the swell and the finding (no allocation) ----
    // currents: CN fixed slots, 2-3 in flight. Each head runs along one arm's log spiral at a
    // steady pace in log radius, a bright head with a long tail; bytes it passes rise toward cyan
    // and settle back. Two directions: out (read, 0.42 R -> 1.0 R) and in (condensing toward the
    // core, 1.0 R -> 0.2 R). A new one starts every 3-5 s on the arm that lies more outside the
    // hero copy and carries fewer currents; it waits if neither arm is clear
    var CN = 3, C_LN0 = Math.log(0.42), C_LN1 = Math.log(1.0), C_LNI = Math.log(0.2);
    var cT0 = new Float64Array(CN), cDur = new Float32Array(CN), cArmS = new Int8Array(CN), cDir = new Int8Array(CN);
    var cEnvS = new Float32Array(CN), cLnS = new Float32Array(CN), cOnS = new Uint8Array(CN);
    var cNext = T + 1.2, cOn = false, cWait = 0, cLastDir = -1;
    for (var cs = 0; cs < CN; cs++) cT0[cs] = -1e4;
    // swell: one broad lopsided density wave that winds out across the arms and turns around the
    // disk once in ~28 s; it scales byte alpha 0.75-1.0 (off at gov 2, and in the still frame)
    var SW_W = TAU / 28, swPh = 0, swK = 0;
    function cMax() { return govLevel >= 3 ? 0 : govLevel === 2 ? 1 : govLevel === 1 || small ? 2 : 3; }
    // finding: F_DUR s from rose to lime and back into the arm; fWant asks the byte pass to pick one
    var F_DUR = 7.6, fNext = T + 7, fT0 = -1e4, fI = -1, fWant = false, fU = 0, fW = 0;
    var fRise = 0, fRose = 0, fLime = 0, fPingR = 0, fPingA = 0, fRingR = 0, fRingA = 0;
    function armPoint(arm, r, out) {                // screen point of an arm's crest at radius r
        var twist = CFG.TWIST_A * Math.sin(TAU * T / CFG.TWIST_T), cp = Math.cos(G.pa), sp = Math.sin(G.pa);
        var t = arm * Math.PI + 0.06 - CFG.PITCH * Math.log(r + 0.05) - twist * (r - 0.4) + G.rot;
        var u = r * R * Math.cos(t), v = r * R * Math.sin(t) * G.incl;
        out[0] = G.x + u * cp - v * sp; out[1] = G.y + G.carry + u * sp + v * cp;
        return out;
    }
    var APT = [0, 0];
    function armScore(arm) {                        // how much of the arm's outer half is clear of the copy, on screen
        var n = 0;
        for (var r = 0.5; r < 0.96; r += 0.075) {
            armPoint(arm, r, APT);
            var x = APT[0], y = APT[1];
            if (x > 30 && x < W - 30 && y > navB + 20 && y < H - 20 && heroFade(x, y) > 0.97) n++;
        }
        return n;
    }
    function stepEvents(dt) {
        if (NOGAL) return;
        // the bytes fade out over 0.5 s when the governor takes them (gov 3), and back in
        bytesK = clamp(bytesK + (govLevel < 3 ? dt : -dt) * 2, 0, 1);
        swPh += dt * SW_W;
        swK = clamp(swK + (govLevel < 2 ? dt : -dt) * 0.5, 0, 1);   // the swell eases in and out over 2 s
        var k = 0, n = 0, n0 = 0, n1 = 0, free = -1;
        for (k = 0; k < CN; k++) {
            if (!cOnS[k]) { if (free < 0) free = k; continue; }
            n++; if (cArmS[k]) n1++; else n0++;
        }
        if (T >= cNext) {
            if (free < 0 || n >= cMax() || bytesK < 0.5) cNext = T + 0.5;
            else {
                // an arm that already carries a current counts as less clear, so the currents spread
                var s0 = armScore(0), s1 = armScore(1), e0 = s0 - 2 * n0, e1 = s1 - 2 * n1;
                if (Math.max(s0, s1) < 3 && cWait < 3) { cNext = T + 2; cWait++; }
                else {
                    var dir = RND() < 0.7 ? -cLastDir : cLastDir;   // mostly alternating, out and in
                    cT0[free] = T; cArmS[free] = e0 > e1 ? 0 : e1 > e0 ? 1 : (n0 > n1 ? 1 : n1 > n0 ? 0 : (RND() < 0.5 ? 0 : 1));
                    cDir[free] = dir; cLastDir = dir; cOnS[free] = 1;
                    cDur[free] = dir > 0 ? 6.4 + 1.2 * RND() : 7.6 + 1.2 * RND();
                    cNext = T + 3 + 2 * RND(); cWait = 0;
                }
            }
        }
        cOn = false;
        for (k = 0; k < CN; k++) {
            if (!cOnS[k]) continue;
            var ca = T - cT0[k], cd = cDur[k];
            if (ca >= cd || ca < 0) { cOnS[k] = 0; cEnvS[k] = 0; continue; }
            cOn = true;
            cEnvS[k] = smooth(0, 0.8, ca) * (1 - smooth(cd - 1.2, cd, ca));
            var q = ca / cd;
            cLnS[k] = cDir[k] > 0 ? C_LN0 + (C_LN1 - C_LN0) * q : C_LN1 + (C_LNI - C_LN1) * q;
        }
        if (fI < 0 && T >= fNext) fWant = true;
        var fa = T - fT0;
        if (fI >= 0 && fa > F_DUR) { fI = -1; fRose = fLime = fRise = fPingA = fRingA = 0; }
        if (fI < 0) return;
        // rise like a struck key, hold, sink back into the arm
        fRise = (1 - Math.exp(-5 * fa) * Math.cos(5.5 * fa)) * (1 - smooth(6.0, F_DUR, fa));
        fRose = smooth(0, 0.35, fa) * (1 - smooth(2.6, 3.4, fa));
        fLime = smooth(2.6, 3.4, fa) * (1 - smooth(6.2, F_DUR, fa));
        var pp = (fa - 0.15) / 1.8, rp = (fa - 2.8) / 2.8;            // the rose wave, then the lime wave
        fPingA = pp > 0 && pp < 1 ? Math.pow(1 - pp, 1.5) : 0;
        fPingR = 0.01 + 0.045 * (1 - Math.pow(1 - clamp(pp, 0, 1), 3));
        fRingA = rp > 0 && rp < 1 ? Math.pow(1 - rp, 1.3) * smooth(0, 0.08, rp) : 0;
        fRingR = 0.015 + 0.125 * (1 - Math.pow(1 - clamp(rp, 0, 1), 3));
    }

    // ---- sky: field stars ---------------------------------------------------------
    var NF = 0, fHx, fHy, fOx, fOy, fVx, fVy, fHead, fTurn, fSpd, fSize, fAlpha, fTw, fPh, fGroup, fX, fY;
    var F_STYLE = ['rgba(199,210,254,0.14)', 'rgba(199,210,254,0.24)', 'rgba(199,210,254,0.36)'];
    function buildField() {
        NF = clamp(Math.round(W * H / CFG.FIELD_AREA), CFG.FIELD_MIN, CFG.FIELD_MAX);
        fHx = new Float32Array(NF); fHy = new Float32Array(NF); fOx = new Float32Array(NF); fOy = new Float32Array(NF);
        fVx = new Float32Array(NF); fVy = new Float32Array(NF); fHead = new Float32Array(NF); fTurn = new Float32Array(NF);
        fSpd = new Float32Array(NF); fSize = new Float32Array(NF); fAlpha = new Float32Array(NF); fTw = new Float32Array(NF);
        fPh = new Float32Array(NF); fGroup = new Int8Array(NF); fX = new Float32Array(NF); fY = new Float32Array(NF);
        for (var i = 0; i < NF; i++) {
            fHx[i] = RND() * W; fHy[i] = RND() * H; fHead[i] = RND() * TAU; fTurn[i] = (RND() - 0.5) * 0.3;
            fSpd[i] = 3 + RND() * 5; fSize[i] = 0.6 + RND() * 0.8; fAlpha[i] = 0.10 + RND() * 0.28;
            fTw[i] = 0.4 + RND() * 1.2; fPh[i] = RND() * TAU; fGroup[i] = -1;
        }
    }
    function rescaleField(sx, sy) {
        for (var i = 0; i < NF; i++) { fHx[i] *= sx; fHy[i] *= sy; }
    }
    function stepField(dt, dScroll) {
        var stir = mouse.on && mouse.mouse, mdx = mouse.dx, mdy = mouse.dy;
        mouse.dx = mouse.dy = 0;
        for (var i = 0; i < NF; i++) {
            var g = fGroup[i];
            if (g < 0) {                                    // free stars wander
                if (RND() < 0.08 * dt) fTurn[i] = (RND() - 0.5) * 0.3;
                fHead[i] += fTurn[i] * dt;
                fHx[i] += Math.cos(fHead[i]) * fSpd[i] * dt;
                fHy[i] += Math.sin(fHead[i]) * fSpd[i] * dt;
            }
            fHy[i] -= dScroll * 0.12;                        // scroll parallax
            if (g < 0) {                                    // only free stars wrap
                if (fHx[i] < -40) fHx[i] += W + 80; else if (fHx[i] > W + 40) fHx[i] -= W + 80;
                if (fHy[i] < -40) fHy[i] += H + 80; else if (fHy[i] > H + 40) fHy[i] -= H + 80;
            }
            if (stir) {                                     // mouse stirs the sky
                var dx = fHx[i] + fOx[i] - mouse.x, dy = fHy[i] + fOy[i] - mouse.y, d = Math.hypot(dx, dy);
                if (d < 150) {
                    var f = 1 - d / 150;
                    fVx[i] += (mdx * 0.55 * f) / Math.max(dt, 0.016) * 0.03 + (dx / (d || 1)) * f * f * 260 * dt;
                    fVy[i] += (mdy * 0.55 * f) / Math.max(dt, 0.016) * 0.03 + (dy / (d || 1)) * f * f * 260 * dt;
                }
            }
            fVx[i] += (-5 * fOx[i] - 3.2 * fVx[i]) * dt; fVy[i] += (-5 * fOy[i] - 3.2 * fVy[i]) * dt;
            fOx[i] = clamp(fOx[i] + fVx[i] * dt, -220, 220); fOy[i] = clamp(fOy[i] + fVy[i] * dt, -220, 220);
            fX[i] = fHx[i] + fOx[i]; fY[i] = fHy[i] + fOy[i];
        }
    }

    // ---- deep sky: parallax star layers + shooting stars ---------------------------
    var ND = 0, dX, dY, dVx, dVy, dRad, dBase, dAmp, dPh, dTw, dCol, dLay;
    var D_RGB = ['99,102,241', '34,211,238', '226,232,240'], D_STYLE = [];
    for (var dc = 0; dc < 3; dc++) for (var da = 1; da <= 6; da++) D_STYLE.push('rgba(' + D_RGB[dc] + ',' + (da / 6 * 0.55).toFixed(3) + ')');
    function buildDeep() {
        var k = clamp(W * H / (1440 * 900), 0.6, 1.6), L, i, n = 0;
        for (L = 0; L < 3; L++) n += Math.round(CFG.DEEP[L].n * k);
        ND = n;
        dX = new Float32Array(n); dY = new Float32Array(n); dVx = new Float32Array(n); dVy = new Float32Array(n);
        dRad = new Float32Array(n); dBase = new Float32Array(n); dAmp = new Float32Array(n); dPh = new Float32Array(n);
        dTw = new Float32Array(n); dCol = new Uint8Array(n); dLay = new Uint8Array(n);
        var j = 0;
        for (L = 0; L < 3; L++) {
            var c = CFG.DEEP[L], m = Math.round(c.n * k);
            for (i = 0; i < m; i++, j++) {
                dX[j] = RND() * W; dY[j] = RND() * H;
                dVx[j] = (RND() - 0.5) * c.sp; dVy[j] = (RND() - 0.5) * c.sp;
                dRad[j] = c.rMin + RND() * (c.rMax - c.rMin);
                dBase[j] = c.aMin + RND() * (c.aMax - c.aMin); dAmp[j] = dBase[j] * 0.5;
                dPh[j] = RND() * TAU; dTw[j] = 0.6 + RND() * 1.2;
                var u = RND(); dCol[j] = u < 0.67 ? 0 : u < 0.84 ? 1 : 2; dLay[j] = L;
            }
        }
    }
    function rescaleDeep(sx, sy) { for (var i = 0; i < ND; i++) { dX[i] *= sx; dY[i] *= sy; } }
    function stepDeep(dt, dScroll) {
        for (var i = 0; i < ND; i++) {
            dX[i] += dVx[i] * dt; dY[i] += dVy[i] * dt - dScroll * CFG.DEEP[dLay[i]].par;
            if (dX[i] < 0) dX[i] += W; else if (dX[i] > W) dX[i] -= W;
            if (dY[i] < 0) dY[i] += H; else if (dY[i] > H) dY[i] -= H;
        }
    }
    var dBk = new Uint8Array(0);
    function drawDeep(still) {
        // each star's style bucket once per tick (was: its sine re-evaluated for every bucket)
        if (dBk.length < ND) dBk = new Uint8Array(ND);
        for (var i = 0; i < ND; i++) {
            var a = still ? dBase[i] : Math.max(0, dBase[i] + dAmp[i] * Math.sin(T * dTw[i] + dPh[i]));
            dBk[i] = dCol[i] * 6 + clamp(Math.round(a / 0.55 * 6) - 1, 0, 5);
        }
        var ga = ctx.globalAlpha;
        for (var b = 0; b < D_STYLE.length; b++) {
            ctx.fillStyle = D_STYLE[b];
            for (i = 0; i < ND; i++) if (dBk[i] === b) disc(D_STYLE[b], dX[i], dY[i], dRad[i], ga);
        }
        ctx.globalAlpha = ga;
    }
    var shooters = [], nextShoot = 2.5 + RND() * 4;
    // NOGAL: keep a shooting star (head and tail) outside 1.2 x the globe's radius. A path
    // that would reach the globe ends early instead - its flight is cut just before the
    // keep-out circle - and is dropped only if less than 0.45 s of it would be left.
    function shooterClear(s) {
        var d = GLOBE && GLOBE.dataset;
        if (!d || !d.r) return true;
        var keep = +d.r * 1.2 + s.len, dx = s.x - +d.cx, dy = s.y - +d.cy;
        var ex = s.vx * s.max, ey = s.vy * s.max;     // whole flight as one segment, t in [0,1]
        var a = ex * ex + ey * ey, b = 2 * (dx * ex + dy * ey), c = dx * dx + dy * dy - keep * keep;
        if (c <= 0) return false;                     // starts inside the keep-out circle
        var disc = b * b - 4 * a * c;
        if (disc < 0) return true;                    // the line never comes that close
        var t = (-b - Math.sqrt(disc)) / (2 * a);     // first entry into the circle
        if (t <= 0 || t > 1) return true;             // only behind it, or after the flight ends
        s.max *= t * 0.97;
        return s.max >= 0.45;
    }
    function stepShooters(dt) {
        if (T >= nextShoot) {
            nextShoot = T + CFG.SHOOT_MIN + RND() * (CFG.SHOOT_MAX - CFG.SHOOT_MIN);
            // NOGAL: a shooting star never crosses the Earth - try a few paths, keep the
            // first that stays clear of the globe for its whole flight, else skip this one
            for (var tries = NOGAL ? 6 : 1; tries > 0 && shooters.length < CFG.SHOOTERS; tries--) {
                var left = RND() < 0.5, dir = left ? 1 : -1, ang = 0.28 + RND() * 0.30, sp = (9 + RND() * 6) * 60;
                var s = { x: left ? -40 : W + 40, y: RND() * H * 0.5, vx: dir * Math.cos(ang) * sp, vy: Math.sin(ang) * sp,
                          life: 0, max: (55 + RND() * 30) / 60, len: 90 + RND() * 70 };
                if (!NOGAL || shooterClear(s)) { shooters.push(s); break; }
            }
        }
        for (var i = shooters.length - 1; i >= 0; i--) {
            var o = shooters[i];
            o.x += o.vx * dt; o.y += o.vy * dt; o.life += dt;
            if (o.life >= o.max || o.x < -200 || o.x > W + 200 || o.y > H + 200) shooters.splice(i, 1);
        }
    }
    function drawShooters(a) {                       // a: the sky's alpha (it softens around a galaxy in focus)
        for (var i = 0; i < shooters.length; i++) {
            var o = shooters[i], k = Math.max(0, 1 - o.life / o.max), h = Math.hypot(o.vx, o.vy) || 1;
            var tx = o.x - o.vx / h * o.len, ty = o.y - o.vy / h * o.len;
            var g = ctx.createLinearGradient(o.x, o.y, tx, ty);
            g.addColorStop(0, 'rgba(226,232,240,' + (0.9 * k).toFixed(3) + ')');
            g.addColorStop(0.3, 'rgba(34,211,238,' + (0.5 * k).toFixed(3) + ')');
            g.addColorStop(1, 'rgba(34,211,238,0)');
            ctx.strokeStyle = g; ctx.lineWidth = 2; ctx.lineCap = 'round';
            ctx.globalAlpha = a;
            ctx.beginPath(); ctx.moveTo(o.x, o.y); ctx.lineTo(tx, ty); ctx.stroke();
            ctx.globalAlpha = a * k; ctx.drawImage(GLOW, o.x - 4, o.y - 4, 8, 8); ctx.globalAlpha = 1;
        }
    }

    // ---- constellations --------------------------------------------------------
    function makeGroup() {
        return {
            on: false, side: '', state: 0, birth: 0, lifeEnd: 0, nextGrow: 0, nextDown: 0, fails: 0, target: 0,
            n: 0, mem: new Int16Array(CFG.MAX_SIZE), conv: new Float32Array(CFG.MAX_SIZE),
            ping: new Float32Array(CFG.MAX_SIZE), flash: new Float32Array(CFG.MAX_SIZE),
            ne: 0, ea: new Int8Array(16), eb: new Int8Array(16), ep: new Float32Array(16),
            np: 0, pe: new Int8Array(CFG.PULSES), pd: new Int8Array(CFG.PULSES), pp: new Float32Array(CFG.PULSES),
            vx: 0, vy: 0, bx: 0, by: 0, bad: 0, downN: 0
        };
    }
    var groups = [makeGroup(), makeGroup()], nextGroupAt = 3, lastSpot = { L: null, R: null, A: null };
    var STATE_GROW = 1, STATE_LIVE = 2, STATE_DOWN = 3;
    function maxGroups() { return small ? 1 : CFG.GROUPS; }
    function bandTop() { return navBottom() + 40; }
    function sideOf(x, y) {
        if (y < bandTop() || y > H - 72) return '';
        if (maxGroups() === 1) return x > 56 && x < W - 56 ? 'A' : '';
        if (x > 56 && x < 0.38 * W) return 'L';
        if (x > 0.62 * W && x < W - 56) return 'R';
        return '';
    }
    function sideFree(side) {
        for (var g = 0; g < groups.length; g++) if (groups[g].on && groups[g].side === side) return false;
        return true;
    }
    function starOk(i, side, keep) {
        return fGroup[i] < 0 && sideOf(fX[i], fY[i]) === side && !occupied(fX[i], fY[i]) &&
            galaxyDist(fX[i], fY[i]) >= keep;
    }
    function startGroup(seed, side, instant) {
        var gi = -1;
        for (var g = 0; g < groups.length; g++) if (!groups[g].on) { gi = g; break; }
        if (gi < 0) return null;
        var G2 = groups[gi];
        G2.on = true; G2.side = side; G2.state = STATE_GROW; G2.birth = T; G2.n = 0; G2.ne = 0; G2.np = 0; G2.fails = 0;
        G2.lifeEnd = T + CFG.LIFE_MIN + RND() * (CFG.LIFE_MAX - CFG.LIFE_MIN);
        G2.target = CFG.MIN_SIZE + ((RND() * (CFG.MAX_SIZE - CFG.MIN_SIZE + 1)) | 0);
        G2.nextGrow = T + (instant ? 0 : CFG.GROW_MIN + RND() * (CFG.GROW_MAX - CFG.GROW_MIN));
        G2.vx = G2.vy = 0; G2.bx = (RND() - 0.5) * 4; G2.by = (RND() - 0.5) * 3; G2.bad = 0; G2.downN = 0;
        addMember(G2, gi, seed, instant);
        lastSpot[side] = [fX[seed], fY[seed]];
        return G2;
    }
    function addMember(G2, gi, i, instant) {
        var k = G2.n++;
        G2.mem[k] = i; G2.conv[k] = instant ? 1 : 0; G2.ping[k] = instant ? 9 : 0; G2.flash[k] = 9;
        fGroup[i] = gi;
        if (k > 0) {                                     // link to the nearest member
            var best = -1, bd = 1e9;
            for (var m = 0; m < k; m++) {
                var j = G2.mem[m], d = Math.hypot(fX[j] - fX[i], fY[j] - fY[i]);
                if (d < bd) { bd = d; best = m; }
            }
            addEdge(G2, best, k, instant);
            if (k > 1 && RND() < 0.35) {                  // sometimes close a loop
                var other = -1, od = 1e9;
                for (var m2 = 0; m2 < k; m2++) {
                    if (m2 === best) continue;
                    var j2 = G2.mem[m2], d2 = Math.hypot(fX[j2] - fX[i], fY[j2] - fY[i]);
                    if (d2 < od && d2 < CFG.LINK * 1.6) { od = d2; other = m2; }
                }
                if (other >= 0) addEdge(G2, other, k, instant);
            }
        }
    }
    function addEdge(G2, a, b, instant) {
        if (G2.ne >= 16) return;
        G2.ea[G2.ne] = a; G2.eb[G2.ne] = b; G2.ep[G2.ne] = instant ? 1 : 0; G2.ne++;
    }
    function pickSeed(side) {
        var keep = CFG.GALAXY_KEEP_OUT, bestI = -1, bestN = 0, i, j;
        for (i = 0; i < NF; i++) {
            if (!starOk(i, side, keep)) continue;
            if (lastSpot[side] && Math.hypot(fX[i] - lastSpot[side][0], fY[i] - lastSpot[side][1]) < W * 0.25) continue;
            var nb = 0;
            for (j = 0; j < NF; j++) {
                if (j === i || !starOk(j, side, keep)) continue;
                if (Math.hypot(fX[j] - fX[i], fY[j] - fY[i]) < CFG.LINK) nb++;
            }
            if (nb >= 2 && (nb > bestN || (nb === bestN && RND() < 0.5))) { bestN = nb; bestI = i; }
        }
        return bestI;
    }
    function nearestFree(G2) {
        var best = -1, bd = CFG.LINK;
        for (var i = 0; i < NF; i++) {
            if (!starOk(i, G2.side, 1.3)) continue;
            for (var m = 0; m < G2.n; m++) {
                var j = G2.mem[m], d = Math.hypot(fX[j] - fX[i], fY[j] - fY[i]);
                if (d < bd) { bd = d; best = i; }
            }
        }
        return best;
    }
    function releaseGroup(G2) {
        for (var m = 0; m < G2.n; m++) fGroup[G2.mem[m]] = -1;
        G2.on = false; G2.n = 0; G2.ne = 0; G2.np = 0;
        nextGroupAt = Math.max(nextGroupAt, T + CFG.NEXT_MIN + RND() * (CFG.NEXT_MAX - CFG.NEXT_MIN));
    }
    function powerDown(G2) {
        if (G2.state === STATE_DOWN) return;
        G2.state = STATE_DOWN; G2.nextDown = T;
    }
    var FD = [0, 0];
    function stepGroups(dt) {
        // new groups
        if (T >= nextGroupAt) {
            nextGroupAt = T + 10 + RND() * 5;
            var active = 0, g;
            for (g = 0; g < groups.length; g++) if (groups[g].on) active++;
            if (active < maxGroups() && textReady) {
                var sides = maxGroups() === 1 ? ['A'] : (RND() < 0.5 ? ['L', 'R'] : ['R', 'L']);
                for (var s = 0; s < sides.length; s++) {
                    if (!sideFree(sides[s])) continue;
                    var seed = pickSeed(sides[s]);
                    if (seed >= 0) { startGroup(seed, sides[s], false); break; }
                }
            }
        }
        // mouse resting on a star starts one there
        if (mouse.on && mouse.mouse && textReady) {
            mouse.still += dt;
            if (mouse.still > 0.6) {
                mouse.still = -1e9;
                var side = sideOf(mouse.x, mouse.y), act = 0;
                for (var q = 0; q < groups.length; q++) if (groups[q].on) act++;
                if (side && sideFree(side) && act < maxGroups()) {
                    for (var i = 0; i < NF; i++) {
                        if (Math.hypot(fX[i] - mouse.x, fY[i] - mouse.y) < 36 && starOk(i, side, CFG.GALAXY_KEEP_OUT)) {
                            startGroup(i, side, false); break;
                        }
                    }
                }
            }
        }
        for (var gi = 0; gi < groups.length; gi++) {
            var G2 = groups[gi];
            if (!G2.on) continue;
            var m, j;
            // grow
            if (G2.state === STATE_GROW && T >= G2.nextGrow) {
                G2.nextGrow = T + CFG.GROW_MIN + RND() * (CFG.GROW_MAX - CFG.GROW_MIN);
                if (G2.n >= G2.target) G2.state = STATE_LIVE;
                else {
                    var cand = nearestFree(G2);
                    if (cand >= 0) addMember(G2, gi, cand, false);
                    else if (++G2.fails > 4) {
                        if (G2.n < CFG.MIN_SIZE) { powerDown(G2); } else { G2.target = G2.n; G2.state = STATE_LIVE; }
                    }
                }
            }
            if (G2.state !== STATE_DOWN && T >= G2.lifeEnd) powerDown(G2);
            // conversion / links / pings
            for (m = 0; m < G2.n; m++) {
                if (G2.state === STATE_DOWN && m >= G2.n - G2.downN) continue;
                G2.conv[m] = Math.min(1, G2.conv[m] + dt / CFG.CONVERT_T);
                if (G2.conv[m] >= 1) G2.ping[m] += dt;
                G2.flash[m] += dt;
            }
            for (var e = 0; e < G2.ne; e++) {
                var a = G2.ea[e], b = G2.eb[e];
                var up = G2.conv[a] >= 1 && G2.conv[b] >= 0.6 && !(G2.state === STATE_DOWN && (a >= G2.n - G2.downN || b >= G2.n - G2.downN));
                G2.ep[e] = clamp(G2.ep[e] + (up ? dt / CFG.LINK_T : -dt / 1.5), 0, 1);
            }
            // power-down: one node every DOWN_STEP s, newest first; nodes fade over 4 s
            if (G2.state === STATE_DOWN) {
                if (T >= G2.nextDown && G2.downN < G2.n) { G2.downN += 1; G2.nextDown = T + CFG.DOWN_STEP; }
                var alive = 0;
                for (m = 0; m < G2.n; m++) {
                    if (m >= G2.n - G2.downN) G2.conv[m] = Math.max(0, G2.conv[m] - dt / 4);
                    if (G2.conv[m] > 0) alive++;
                }
                if (alive === 0) { releaseGroup(G2); continue; }
            }
            // pulses
            if (G2.state !== STATE_DOWN) {
                for (e = 0; e < G2.ne; e++) {
                    if (G2.ep[e] >= 1 && G2.np < CFG.PULSES && RND() < dt / 9) {
                        G2.pe[G2.np] = e; G2.pd[G2.np] = RND() < 0.5 ? 1 : -1; G2.pp[G2.np] = 0; G2.np++;
                    }
                }
            }
            for (var p = G2.np - 1; p >= 0; p--) {
                var ee = G2.pe[p], A1 = G2.mem[G2.ea[ee]], B1 = G2.mem[G2.eb[ee]];
                var len = Math.hypot(fX[B1] - fX[A1], fY[B1] - fY[A1]) || 1;
                G2.pp[p] += CFG.PULSE_SPEED * dt / len;
                if (G2.pp[p] >= 1 || G2.ep[ee] < 1) {
                    if (G2.pp[p] >= 1) G2.flash[G2.pd[p] > 0 ? G2.eb[ee] : G2.ea[ee]] = 0;
                    G2.np--; G2.pe[p] = G2.pe[G2.np]; G2.pd[p] = G2.pd[G2.np]; G2.pp[p] = G2.pp[G2.np];   // swap-remove
                }
            }
            // drift: away from the galaxy, toward empty space, back into its band
            var cx = 0, cy = 0, deepest = 9, onText = false, off = false;
            for (m = 0; m < G2.n; m++) {
                j = G2.mem[m]; cx += fX[j]; cy += fY[j];
                var gd = galaxyDist(fX[j], fY[j]); if (gd < deepest) deepest = gd;
                if (G2.conv[m] > 0.3 && occupied(fX[j], fY[j])) onText = true;
                if (fX[j] < -10 || fX[j] > W + 10 || fY[j] < -10 || fY[j] > H + 10) off = true;
            }
            if (off && G2.state !== STATE_DOWN) { powerDown(G2); G2.downN = G2.n; }   // never wrap: fade out
            cx /= G2.n; cy /= G2.n;
            var ax = (G2.bx - G2.vx) * 0.5, ay = (G2.by - G2.vy) * 0.5;
            if (deepest < CFG.GALAXY_KEEP_OUT) {
                var dx = cx - G.x, dy = cy - G.y, dd = Math.hypot(dx, dy) || 1, push = (CFG.GALAXY_KEEP_OUT - deepest) * 60;
                ax += dx / dd * push; ay += dy / dd * push;
            }
            if (onText) { freeDir(cx, cy, FD); ax += FD[0] * 30; ay += FD[1] * 30; }
            if (G2.side === 'L' && cx > 0.38 * W) ax -= 12; else if (G2.side === 'R' && cx < 0.62 * W) ax += 12;
            G2.vx += ax * dt; G2.vy += ay * dt;
            var sp = Math.hypot(G2.vx, G2.vy);
            if (sp > 12) { G2.vx *= 12 / sp; G2.vy *= 12 / sp; }
            for (m = 0; m < G2.n; m++) { j = G2.mem[m]; fHx[j] += G2.vx * dt; fHy[j] += G2.vy * dt; }
            G2.bad = (onText || deepest < 1.05) ? G2.bad + dt : 0;
            if (G2.bad > 2) powerDown(G2);
        }
    }
    function groupsStillGood() {
        var any = false;
        for (var g = 0; g < groups.length; g++) {
            var G2 = groups[g];
            if (!G2.on) continue;
            any = true;
            for (var m = 0; m < G2.n; m++) {
                var j = G2.mem[m];
                if (occupied(fX[j], fY[j]) || fX[j] < 0 || fX[j] > W || fY[j] < 0 || fY[j] > H ||
                    galaxyDist(fX[j], fY[j]) < CFG.GALAXY_KEEP_OUT) return false;
            }
        }
        return any;
    }
    function instantGroups() {                       // reduced motion: finished constellations
        for (var g = 0; g < groups.length; g++) if (groups[g].on) { var o = groups[g]; for (var mm = 0; mm < o.n; mm++) fGroup[o.mem[mm]] = -1; o.on = false; o.n = o.ne = o.np = 0; }
        var sides = maxGroups() === 1 ? ['A'] : ['L', 'R'];
        lastSpot = { L: null, R: null, A: null };
        for (var s = 0; s < sides.length; s++) {
            var seed = pickSeed(sides[s]);
            if (seed < 0) continue;
            var G2 = startGroup(seed, sides[s], true), gi = groups.indexOf(G2);
            while (G2.n < G2.target) { var c = nearestFree(G2); if (c < 0) break; addMember(G2, gi, c, true); }
            if (G2.n < CFG.MIN_SIZE) releaseGroup(G2); else G2.state = STATE_LIVE;
        }
    }

    // ---- drawing ---------------------------------------------------------------
    var CYAN = 'rgb(103,232,249)', PALE = '#ecfeff';
    var fLv = new Int8Array(0);
    function drawField() {
        // each star's level once per tick (was: sin + hypot repeated in all three passes)
        if (fLv.length < NF) fLv = new Int8Array(NF);
        var hover = mouse.on && mouse.mouse, i;
        for (i = 0; i < NF; i++) {
            if (fGroup[i] >= 0) { fLv[i] = -1; continue; }
            var tw = 0.6 + 0.4 * Math.sin(T * fTw[i] + fPh[i]), a = fAlpha[i] * tw;
            var hb = hover ? 1 + 0.8 * Math.max(0, 1 - Math.hypot(fX[i] - mouse.x, fY[i] - mouse.y) / 120) : 1;
            fLv[i] = clamp(Math.round(a * hb / 0.38 * 2.5) - 1, 0, 2);
        }
        var ga = ctx.globalAlpha;
        for (var b = 0; b < 3; b++) {
            ctx.fillStyle = F_STYLE[b];
            for (i = 0; i < NF; i++) if (fLv[i] === b) square(fX[i], fY[i], fSize[i], ga);
        }
        ctx.globalAlpha = ga;
    }
    function diamond(x, y, h) { ctx.moveTo(x, y - h); ctx.lineTo(x + h, y); ctx.lineTo(x, y + h); ctx.lineTo(x - h, y); ctx.closePath(); }
    function drawGroups() {
        var maxLen = CFG.LINK * 1.8;
        for (var g = 0; g < groups.length; g++) {
            var G2 = groups[g];
            if (!G2.on) continue;
            var e, m, j, a, b;
            // member stars that are still converting fade out under their node
            ctx.fillStyle = 'rgba(199,210,254,0.35)';
            for (m = 0; m < G2.n; m++) {
                if (G2.conv[m] >= 1) continue;
                j = G2.mem[m]; ctx.globalAlpha = 1 - G2.conv[m];
                ctx.fillRect(fX[j] - fSize[j] / 2, fY[j] - fSize[j] / 2, fSize[j], fSize[j]);
            }
            // links
            ctx.strokeStyle = CYAN; ctx.lineCap = 'round';
            for (e = 0; e < G2.ne; e++) {
                var p = G2.ep[e];
                if (p <= 0) continue;
                a = G2.mem[G2.ea[e]]; b = G2.mem[G2.eb[e]];
                var len = Math.hypot(fX[b] - fX[a], fY[b] - fY[a]);
                if (len > maxLen) continue;                   // guard against any stretched link
                var t = ease(p), ex = lerp(fX[a], fX[b], t), ey = lerp(fY[a], fY[b], t);
                ctx.globalAlpha = 0.10 * p; ctx.lineWidth = 2.2;
                ctx.beginPath(); ctx.moveTo(fX[a], fY[a]); ctx.lineTo(ex, ey); ctx.stroke();
                ctx.globalAlpha = 0.35 * Math.min(1, p * 1.5); ctx.lineWidth = 0.8;
                ctx.stroke();
                if (p < 1) { ctx.globalAlpha = 0.6; ctx.drawImage(GLOW, ex - 4, ey - 4, 8, 8); }
            }
            // pulses
            for (var q = 0; q < G2.np; q++) {
                e = G2.pe[q]; a = G2.mem[G2.ea[e]]; b = G2.mem[G2.eb[e]];
                var pp = G2.pd[q] > 0 ? G2.pp[q] : 1 - G2.pp[q];
                var dxp = fX[b] - fX[a], dyp = fY[b] - fY[a], L = Math.hypot(dxp, dyp) || 1;
                var px = fX[a] + dxp * pp, py = fY[a] + dyp * pp, ux = dxp / L * G2.pd[q], uy = dyp / L * G2.pd[q];
                ctx.globalAlpha = 0.5; ctx.drawImage(GLOW, px - 3, py - 3, 6, 6);
                ctx.fillStyle = PALE; ctx.globalAlpha = 0.9; ctx.fillRect(px - 0.8, py - 0.8, 1.6, 1.6);
                ctx.fillStyle = CYAN;
                for (var tr = 1; tr <= 3; tr++) {
                    ctx.globalAlpha = 0.45 - tr * 0.12;
                    ctx.fillRect(px - ux * tr * 3 - 0.6, py - uy * tr * 3 - 0.6, 1.2, 1.2);
                }
            }
            // nodes
            for (m = 0; m < G2.n; m++) {
                var cv = G2.conv[m];
                if (cv <= 0) continue;
                j = G2.mem[m];
                var x = fX[j], y = fY[j], shimmer = cv < 1 ? 0.75 + 0.25 * Math.sin(T * 20 + m) : 1;
                var aN = ease(cv) * shimmer;
                ctx.globalAlpha = 0.25 * aN; ctx.drawImage(GLOW, x - 4.5, y - 4.5, 9, 9);
                ctx.globalAlpha = 0.9 * aN; ctx.fillStyle = CYAN; ctx.beginPath(); diamond(x, y, 2.6); ctx.fill();
                ctx.fillStyle = PALE; ctx.fillRect(x - 0.7, y - 0.7, 1.4, 1.4);
                // corner brackets: bright while converting, faint once live
                ctx.globalAlpha = (cv < 1 ? 0.85 : 0.3) * aN; ctx.strokeStyle = CYAN; ctx.lineWidth = 0.7;
                ctx.beginPath();
                ctx.moveTo(x - 5, y - 3); ctx.lineTo(x - 5, y - 5); ctx.lineTo(x - 3, y - 5);
                ctx.moveTo(x + 3, y - 5); ctx.lineTo(x + 5, y - 5); ctx.lineTo(x + 5, y - 3);
                ctx.moveTo(x + 5, y + 3); ctx.lineTo(x + 5, y + 5); ctx.lineTo(x + 3, y + 5);
                ctx.moveTo(x - 3, y + 5); ctx.lineTo(x - 5, y + 5); ctx.lineTo(x - 5, y + 3);
                ctx.stroke();
                if (G2.ping[m] > 0 && G2.ping[m] < 2.5) {        // boot ping
                    var pr = G2.ping[m] / 2.5;
                    ctx.globalAlpha = 0.4 * (1 - pr); ctx.lineWidth = 0.8;
                    ctx.beginPath(); ctx.arc(x, y, 4 + 12 * pr, 0, TAU); ctx.stroke();
                }
                if (G2.flash[m] < 1.2) {                         // a pulse arrived
                    var fr = G2.flash[m] / 1.2;
                    ctx.globalAlpha = 0.5 * (1 - fr); ctx.lineWidth = 0.8;
                    ctx.beginPath(); ctx.arc(x, y, 4.5 + 3 * fr, 0, TAU); ctx.stroke();
                }
            }
            ctx.globalAlpha = 1;
        }
    }
    // ---- the bytes: small functions around the star loop (each stays optimised, no boxing) ----
    // byteBase: the arm stars' byte mix from their radius (they stream inward and respawn)
    function byteBase() {
        for (var o = 0; o < nAI; o++) {
            var i = AIDX[o], by = sBy[i];
            var t = by > 0 ? (sR[i] - by + 0.05) * 20 : 1;   // 1 - smooth(by - 0.05, by, r), inlined
            t = t < 0 ? 0 : t > 1 ? 1 : t;
            sM[i] = 1 - t * t * (3 - 2 * t);
            sCur[i] = 0;
        }
    }
    // litCurrent: along its arm, each current is a head in log radius with a long tail behind it
    // (inward for an outward current, outward for an inward one); what it passes is read: a star
    // it lights resolves into a cyan byte for a moment. Outward currents light r > 0.3 only,
    // inward ones fade out by 0.15 R, before the bulge. One pass over the arm stars, a loop over
    // the 1-3 live currents inside it; a byte two currents cross takes the brighter
    var lcA = new Int8Array(CN), lcD = new Int8Array(CN), lcL = new Float32Array(CN), lcE = new Float32Array(CN);
    var lcLo = new Float32Array(CN), lcHi = new Float32Array(CN), lcW0 = new Float32Array(CN), lcWi = new Float32Array(CN);
    function litCurrent() {
        var tK = small ? 3.2 : 2.2, nc = 0, k = 0, rLo = 1e9, rHi = 0;
        for (k = 0; k < CN; k++) {
            if (!cOnS[k] || cEnvS[k] < 0.01) continue;
            var ln = cLnS[k], rH = Math.exp(ln), d = cDir[k];
            lcA[nc] = cArmS[k]; lcD[nc] = d; lcL[nc] = ln; lcE[nc] = cEnvS[k];
            if (d > 0) { lcHi[nc] = rH * 1.15; lcLo[nc] = Math.max(0.3, rH * Math.exp(-3 / tK)); lcW0[nc] = 0.3; lcWi[nc] = 8.333; }
            else { lcLo[nc] = Math.max(0.15, rH / 1.15); lcHi[nc] = rH * Math.exp(3 / tK); lcW0[nc] = 0.15; lcWi[nc] = 9.09; }
            if (lcLo[nc] < rLo) rLo = lcLo[nc];
            if (lcHi[nc] > rHi) rHi = lcHi[nc];
            nc++;
        }
        if (!nc) return;
        for (var o = 0; o < nAI; o++) {
            var i = AIDX[o], dv = sDev[i];
            if (dv > 0.5 || dv < -0.5) continue;
            var r = sR[i];
            if (r > rHi || r < rLo) continue;              // outside every current's reach
            var a = sArm[i], lr = 0, best = 0, dvK = Math.exp(-dv * dv * 25);
            for (k = 0; k < nc; k++) {
                if (lcA[k] !== a || r > lcHi[k] || r < lcLo[k]) continue;   // ahead of the head, or past the tail's end
                if (lr === 0) lr = Math.log(r);
                var dx = (lcL[k] - lr) * lcD[k], w = (r - lcW0[k]) * lcWi[k];
                w = w < 0 ? 0 : w > 1 ? 1 : w * w * (3 - 2 * w);   // smooth(w0, w0 + 0.12, r), inlined
                var cu = (dx < 0 ? Math.exp(-dx * dx * 120) : Math.exp(-dx * tK)) * dvK * lcE[k] * w;
                if (cu > best) best = cu;
            }
            if (best <= 0) continue;
            sCur[i] = best;
            if (best > 0.12 && !small) { var mc = smooth(0.12, 0.45, best); if (mc > sM[i]) sM[i] = mc; }   // a phone: it only tints the bytes already there
        }
    }
    // a finding's waves reach 0.14 R in the disk plane: its byte must sit that far (+12 px)
    // clear of the copy, the hero block and the scroll cue
    function clearOfCopy(x, y, RD) {
        var rx = 0.14 * RD + 12, ry = rx;
        if (occupancyIn(x - rx, y - ry, x + rx, y + ry) > 0) return false;
        var yd = y + scrollY;
        for (var h = 0; h < nHero; h++) {
            var o = h * 4;
            if (x + rx > heroR[o] && x - rx < heroR[o + 2] && yd + ry > heroR[o + 1] && yd - ry < heroR[o + 3]) return false;
        }
        return true;
    }
    // skinBytes: per byte its value (flicker), alpha, depth of field, tint and bucket; picks a finding
    function skinBytes(RD, mOn, rot) {
        var frK = govLevel >= 1 ? 0.5 : 1, soft = govLevel < 1 && !small, hotOk = govLevel < 2 && !small;
        var att = 0.3 + 0.7 * gAtt, fOn = fI >= 0, fTake = fWant && fI < 0 && mK > 0.5;
        var fBest = -1, fSeen = 0, mgn = 60, o = 0, i = 0, fn = 0, m = 0, ab = 0, sf = 0, z = 0, ac = 0, sk = 0, hf = 1;
        var tn = 0, lv = 0, rg = 0, cu = 0, x = 0, y = 0, sn = 0, r = 0, dm = 0, bc = 0, cb = 0;
        var du = 0, dw = 0, dd = 0, rq = 0, rl = 0, tr = 0, tl = 0, cc = 0;
        var swA = 0.125 * swK, swO = rot - swPh;          // the swell: alpha x (1 - swA + swA cos), 0.75-1.0 at full
        for (o = 0; o < nB; o++) {
            i = bList[o]; x = sX[i]; y = sY[i]; sn = sSn[i]; r = sR[i]; m = sM[i] * mK;
            fn = Math.floor(T * sFr[i] * frK + sFp[i]);
            if (fn !== sFn[i]) { sFn[i] = fn; sFv[i] = hash(i, fn); }   // re-rolled only when its slot changes
            ab = sAlpha[i] * (0.82 + 0.18 * sFv[i]) * sFE[i] * m * att;
            if (swA > 0.001) ab *= 1 - swA + swA * Math.cos(sTh[i] + swO - 2.4 * r);
            hf = x > hbx0 && x < hbx1 && y > hby0 && y < hby1 ? heroFade(x, y) : 1;
            if (mOn) { dm = Math.hypot(x - mouse.x, y - mouse.y); if (dm < 110) ab *= 1 + 0.6 * (1 - dm / 110); }
            // depth of field: the near side in focus, the far side and the core haze soft
            sf = (-sn - 0.05) * 1.25;
            if (r < 0.16) { bc = 1 - smooth(0.07, 0.16, r); if (bc > sf) sf = bc; }
            sf = sf < 0.15 ? 0 : sf > 1 ? 1 : sf;
            tn = sBy[i] > 5 ? 1 : 0; rg = 0; cu = sCur[i];
            if (cu > 0.28) {                            // being read: cyan, and it keeps its light near the copy
                tn = 2; cb = (0.35 + 0.6 * cu) * m * att; if (cb > ab) ab = cb;
                if (hf > 0.4 && hf < 0.75) hf = 0.75;
            }
            if (fOn && (fPingA > 0.01 || fRingA > 0.01)) {   // the finding's waves run through its neighbours, in the disk plane
                du = (sPu[i] - fU) / RD; dw = (sPw[i] - fW) / RD; dd = Math.sqrt(du * du + dw * dw);
                rq = (dd - fPingR) / 0.014; rl = (dd - fRingR) / 0.02;
                tr = fPingA * Math.exp(-rq * rq); tl = fRingA * Math.exp(-rl * rl);
                if (tr > 0.22 && tr >= tl) { tn = 3; rg = tr; } else if (tl > 0.22) { tn = 4; rg = tl; }
                if (rg > 0 && (0.3 + 0.65 * rg) * m > ab) ab = (0.3 + 0.65 * rg) * m;
            }
            ab *= hf;
            z = sZb[i]; sk = 0; ac = ab;
            if (sf > 0 && rg === 0) {
                if (soft) { z *= 1 + 0.15 * sf; ac = ab * (1 - 0.45 * sf); sk = ab * 0.32 * sf; }
                else ac = ab * (1 - 0.4 * sf);          // flat caps: only fainter
            }
            sBz[i] = z; sHot[i] = 0; sBB[i] = 255; sBK[i] = 255;
            if (i === fI) { fU = sPu[i]; fW = sPw[i]; sBA = ab; sBB[i] = 254; continue; }
            if (tn === 0 || (small && tn < 4)) {        // a star bucket (a phone: its tints too, no extra fills)
                cc = tn === 0 ? B_ARM : PH_COL[tn];
                lv = Math.round(ac * ALEVELS + 0.2) - 1; if (lv > ALEVELS - 1) lv = ALEVELS - 1;
                if (lv >= 0) sBB[i] = cc * ALEVELS + lv;
                lv = Math.round(sk * ALEVELS + 0.2) - 1;
                if (lv >= 0) sBK[i] = cc * ALEVELS + (lv > ALEVELS - 1 ? ALEVELS - 1 : lv);
            } else {
                lv = Math.round(ac * SLV + 0.2) - 1; if (lv > SLV - 1) lv = SLV - 1;
                if (lv >= 0) sBB[i] = NBS + (tn - 1) * SLV + lv;
                lv = Math.round(sk * SLV + 0.2) - 1;
                if (lv >= 0) sBK[i] = NBS + (tn - 1) * SLV + (lv > SLV - 1 ? SLV - 1 : lv);
            }
            if (hotOk && sf === 0 && ac > 0.5 && z >= 1.8) sHot[i] = 1;
            // a finding surfaces on a crisp arm byte, its waves clear of the copy and the screen edge
            if (fTake && m >= 0.99 && sKind[i] === 1 && sf === 0 && sn > 0.05 && r > 0.25 && r < 0.8 &&
                x > mgn && x < W - mgn && y > navB + mgn && y < H - mgn &&
                !occupied(x, y) && hf > 0.99 && RND() * ++fSeen < 1 && clearOfCopy(x, y, RD)) fBest = i;
        }
        if (fTake) {
            fWant = false;
            if (fBest >= 0) { fI = fBest; fT0 = T; fNext = T + 20 + 5 * RND(); }
            else fNext = T + 1;
        }
    }
    var sBA = 0;                                     // the found byte's own alpha, before it lights
    var PH_COL = [B_ARM, 2, 6, 4];                   // a phone: cream, cyan and rose bytes in the near-white, pale-cyan and pink star buckets
    var HOT = 'rgb(240,248,255)', ROSE = 'rgb(251,113,133)', LIME = 'rgb(190,242,100)', ARMB = 'rgba(' + STAR_RGB[B_ARM] + ',0.85)';
    // after the stars: hot cores, the read current's head, the finding
    function drawByteTops(gal, cp, sp, inc, rot, RD, gy) {
        var o = 0, i = 0, z = 0;
        if (govLevel < 2 && !small) {               // the bright crisp ones carry a hot core
            ctx.fillStyle = HOT; ctx.globalAlpha = gal * 0.72;
            for (o = 0; o < nB; o++) {
                i = bList[o];
                if (!sHot[i]) continue;
                square(sX[i], sY[i], sBz[i] * 0.42, gal * 0.72);
            }
            ctx.globalAlpha = gal * 0.72;
        }
        if (cOn) {                                      // each current's head on its arm's spiral
            var twist = CFG.TWIST_A * Math.sin(TAU * T / CFG.TWIST_T), hz = small ? 7 : 8;
            for (var k = 0; k < CN; k++) {
                if (!cOnS[k] || cEnvS[k] < 0.01) continue;
                var rq = Math.exp(cLnS[k]);
                if (rq >= 0.95) continue;
                var tq = cArmS[k] * Math.PI + 0.06 - CFG.PITCH * Math.log(rq + 0.05) - twist * (rq - 0.4) + rot;
                var uq = rq * RD * Math.cos(tq), vq = rq * RD * Math.sin(tq) * inc;
                var hx = G.x + uq * cp - vq * sp, hy = gy + uq * sp + vq * cp, hf = heroFade(hx, hy);
                if (hf > 0.4 && hf < 0.75) hf = 0.75;
                var ha = gal * cEnvS[k] * 0.9 * hf * mK * (cDir[k] > 0 ? smooth(0.42, 0.5, rq) : smooth(0.2, 0.32, rq));
                if (ha > 0.01) {
                    ctx.globalAlpha = ha > 1 ? 1 : ha;
                    ctx.drawImage(HEAD, hx - hz * 0.5, hy - hz * 0.5, hz, hz);
                }
            }
        }
        // the finding: the byte lifted on a short stem, rose, then lime, then back into the arm
        if (fI >= 0 && sBB[fI] === 254) {
            var fx = sX[fI], fy = sY[fI], hs = small ? 0.78 : 1;
            var lift = 6 * hs * fRise, lx = fx + lift * sp, ly = fy - lift * cp, on = fRose + fLime;
            if (lift > 1.5 && !small) {                 // the stem from its place in the arm (a phone: too short to see)
                ctx.strokeStyle = fLime > fRose ? LIME : ROSE; ctx.globalAlpha = gal * 0.5 * on; ctx.lineWidth = 0.9;
                ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(lx, ly); ctx.stroke();
            }
            if (!small) ctx.globalCompositeOperation = 'source-over';   // the found byte keeps its own colour over the gas
            z = sBz[fI];
            if (on < 1) { ctx.globalAlpha = gal * sBA * (1 - on); ctx.fillStyle = ARMB; ctx.fillRect(lx - z * 0.5, ly - z * 0.5, z, z); }
            var fq = 4.2 * hs, fh = fq * 0.5;
            if (fRose > 0.01) { ctx.globalAlpha = gal * fRose; ctx.fillStyle = ROSE; ctx.fillRect(lx - fh, ly - fh, fq, fq); }
            if (fLime > 0.01) { ctx.globalAlpha = gal * fLime; ctx.fillStyle = LIME; ctx.fillRect(lx - fh, ly - fh, fq, fq); }
            if (!small) ctx.globalCompositeOperation = 'lighter';
        }
        ctx.globalAlpha = gal;
    }
    // the galaxy's per-frame work in small functions: each one stays optimised (a large
    // drawGalaxy ran in a lower tier and boxed its doubles: ~10 MB of garbage per 5 s)
    // project stars once (thin disk: a little height above the plane), bucket by colour x alpha
    function projectStars(cp, sp, inc, rot, RD, sinI, gy, stk, wS, sMax, mOn) {
        var i = 0, mk = mK;
        for (i = 0; i < nDraw; i++) {
            var m = sM[i] * mk;
            var th = sTh[i] + rot + m * sBOff[i], s = Math.sin(th), c = Math.cos(th), rr = sR[i] * RD, u = rr * c, v = rr * s * inc - sZ[i] * RD * sinI;
            sX[i] = G.x + u * cp - v * sp; sY[i] = gy + u * sp + v * cp;
            if (stk > 0) {
                if (sR[i] > 1.05 || sSize[i] < 0.78) { sDX[i] = sDY[i] = 0; }   // inside the disk only, and not the faintest specks
                else {
                var tu = -rr * s * wS, tv = rr * c * inc * wS, tx = tu * cp - tv * sp, ty = tu * sp + tv * cp;
                var tl = tx * tx + ty * ty;
                if (tl > sMax * sMax) { tl = sMax / Math.sqrt(tl); tx *= tl; ty *= tl; }
                sDX[i] = tx; sDY[i] = ty;
                }
            }
            var k = sKind[i], fadeEdge = k === 1 ? smooth(0.06, 0.12, sR[i]) * sFade[i] : sFade[i];
            var a = sAlpha[i] * (1 - sTwA[i] + sTwA[i] * Math.sin(T * sTw[i] + sPh[i])) * fadeEdge * (1 + 0.10 * s);
            if (k === 4) a *= 0.12 + 0.75 * kArm[i] + 0.5 * kFl[i];
            if (mOn) {
                var dm = Math.hypot(sX[i] - mouse.x, sY[i] - mouse.y);
                if (dm < 110) a *= 1 + 0.6 * (1 - dm / 110);
            }
            if (m > 0.004) {                             // a byte: the byte pass skins it; the star crossfades out
                bList[nB++] = i; sSn[i] = s; sPu[i] = u; sPw[i] = rr * s; sFE[i] = fadeEdge * (1 + 0.10 * s);
                a *= 1 - m;
            }
            var lvl = clamp(Math.round(a * ALEVELS) - 1, -1, ALEVELS - 1);
            sBucket[i] = lvl < 0 ? 255 : sCol[i] * ALEVELS + lvl;
        }
    }
    function sortBuckets() {
        var NB = NBT, i = 0, o = 0, q = 0;
        if (!bkStart || bkStart.length < NB + 1) { bkStart = new Int32Array(NB + 1); bkFill = new Int32Array(NB); }
        if (!bkOrder || bkOrder.length < NS * 3) bkOrder = new Uint16Array(NS * 3);
        bkStart.fill(0);
        for (i = 0; i < nDraw; i++) if (sBucket[i] !== 255) bkStart[sBucket[i] + 1]++;
        for (o = 0; o < nB; o++) { i = bList[o]; if (sBB[i] < NB) bkStart[sBB[i] + 1]++; if (sBK[i] < NB) bkStart[sBK[i] + 1]++; }
        for (q = 0; q < NB; q++) { bkStart[q + 1] += bkStart[q]; bkFill[q] = bkStart[q]; }
        for (i = 0; i < nDraw; i++) if (sBucket[i] !== 255) bkOrder[bkFill[sBucket[i]]++] = i;
        for (o = 0; o < nB; o++) {
            i = bList[o];
            if (sBK[i] < NB) bkOrder[bkFill[sBK[i]]++] = i | 0x4000;
            if (sBB[i] < NB) bkOrder[bkFill[sBB[i]]++] = i | 0x8000;
        }
    }
    function fillBuckets(gal) {
        var NB = NBT, i = 0, o = 0, e = 0, bk = 0, from = 0, to = 0, z = 0, st = '';
        ctx.globalAlpha = gal;
        for (bk = 0; bk < NB; bk++) {
            from = bkStart[bk]; to = bkStart[bk + 1];
            if (from === to) continue;
            st = bk < NBS ? BUCKET_STYLE[bk] : SP_STYLE[bk - NBS];
            ctx.fillStyle = st;
            for (o = from; o < to; o++) {
                e = bkOrder[o];
                if (e >= 0x4000) {
                    i = e & 0x3fff;
                    square(sX[i], sY[i], e >= 0x8000 ? sBz[i] : sBz[i] + 1.2, gal);
                    continue;
                }
                i = e;
                z = sSize[i];
                if (z <= 1.3) square(sX[i], sY[i], z, gal);
                else disc(st, sX[i], sY[i], z * 0.42, gal);
            }
        }
        ctx.globalAlpha = gal;
    }
    function drawTrails(gal, stk) {
        var NB = NBT, i = 0, o = 0, e = 0, bk = 0, from = 0, to = 0, pass = 0, tk = 0, ex = 0, ey = 0;
        if (stk > 0) {                                  // the trails: one stroke per bucket, whole + near half
            ctx.lineWidth = 1; ctx.lineCap = 'butt';
            for (pass = 0; pass < 2; pass++) {
                tk = pass ? 0.5 : 1;
                ctx.globalAlpha = gal * stk * (pass ? 0.46 : 0.36);
                for (bk = 0; bk < NB; bk++) {
                    from = bkStart[bk]; to = bkStart[bk + 1];
                    if (from === to) continue;
                    ctx.strokeStyle = bk < NBS ? BUCKET_STYLE[bk] : SP_STYLE[bk - NBS]; ctx.beginPath();
                    for (o = from; o < to; o++) {
                        e = bkOrder[o];
                        if ((e & 0xc000) === 0x4000) continue;     // a skirt: its byte draws the trail
                        i = e & 0x3fff;
                        ex = sDX[i]; ey = sDY[i];
                        if (ex * ex + ey * ey < 2.2) continue;
                        ctx.moveTo(sX[i], sY[i]); ctx.lineTo(sX[i] + ex * tk, sY[i] + ey * tk);
                    }
                    ctx.stroke();
                }
            }
            ctx.globalAlpha = gal;
        }
    }
    function drawGalaxy() {
        if (NOGAL || !G.placed) return;
        // focus: full light in focus, 78% while the reader scrolls on down (it steps back - in
        // light only: no size change, nothing that reads as motion)
        var gal = (small ? CFG.GALAXY_ALPHA_SMALL : CFG.GALAXY_ALPHA) * G.alpha * (0.78 + 0.22 * G.focus);
        if (gal <= 0.01) return;
        var cp = Math.cos(G.pa), sp = Math.sin(G.pa), inc = G.incl, rot = G.rot, RD = R;
        var sinI = Math.sqrt(Math.max(0, 1 - inc * inc)), gy = G.y + G.carry;
        ctx.globalCompositeOperation = 'lighter';
        if (gasReady && S) {
            gasFade = Math.min(1, gasFade + stepDt / 1.5);   // by time: the steps run at the display rate
            ctx.save();
            ctx.translate(G.x, gy); ctx.rotate(G.pa);
            // the bulge is a spheroid: it is flattened less by the tilt than the disk
            var br = 1 + 0.10 * Math.sin(TAU * T / CFG.BREATH_T), cb = RD * 0.30;
            ctx.save(); ctx.scale(1, 0.62 + 0.38 * inc); ctx.rotate(rot);
            // the arrival swell: a quick rise, a slow settle, up to +35% on the core
            var sw = G.swell > 0 ? 0.35 * Math.sin(Math.PI * Math.sqrt(1 - G.swell)) : 0;
            ctx.globalAlpha = Math.min(1, 0.30 * gal * gasFade * br * gAtt * (1 + sw));
            ctx.drawImage(BLOOM, -cb, -cb, 2 * cb, 2 * cb);
            ctx.restore();
            ctx.scale(1, inc); ctx.rotate(rot);
            ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';   // the gas is soft: smooth, never blocky
            var gA = CFG.GAS_ALPHA * gal * gasFade * gAtt, mix = gasMix();   // 'lighter': an exact blend of the two
            if (mix < 1) { ctx.globalAlpha = gA * (1 - mix); ctx.drawImage(gasCans[gasCur ^ 1], -RD, -RD, 2 * RD, 2 * RD); }
            ctx.globalAlpha = gA * mix;
            ctx.drawImage(gasCan, -RD, -RD, 2 * RD, 2 * RD);
            ctx.restore();
        }
        // project stars once (thin disk: a little height above the plane), bucket by colour x alpha
        var glows = 0, i, mOn = mouse.on && mouse.mouse;
        // fast scroll: each star leaves a short trail back along its path (the tangent of its
        // orbit, projected), as long as the extra spin carries it in STREAK_T, capped
        var stk = smooth(0.12, 0.55, Math.abs(G.spin)), wS = -CFG.SPIN_MAX * G.spin * CFG.STREAK_T, sMax = CFG.STREAK_MAX;
        // bytes: the gas brings them (no gas, no bytes) and the governor takes them at gov 3 (a
        // 0.5 s fade); gov 1 halves the re-roll, flattens the soft ones and allows 2 currents,
        // gov 2 drops the hot cores and the swell and allows 1 current
        mK = bytesK * gasFade;
        nB = 0;
        if (!bList || bList.length < NS) bList = new Uint16Array(NS);
        // the steps run as fast as the display: the byte skins (mix, current, value, tint,
        // bucket) refresh at 30 Hz whatever the step rate (a phone: 15 Hz, its bytes are 2 px);
        // positions every step
        var skinNow = reduced || T >= skinDue;
        if (skinNow) skinDue = T + (small ? 1 / 15 : 1 / 30) - 0.004;
        if (mK > 0.004) { if (skinNow) { byteBase(); if (cOn) litCurrent(); } } else mK = 0;
        if (hbSY !== scrollY) { heroBox(); hbSY = scrollY; }
        projectStars(cp, sp, inc, rot, RD, sinI, gy, stk, wS, sMax, mOn);
        if (nB && skinNow) skinBytes(RD, mOn, rot);
        // per colour bucket: sub-pixel stars as squares (a dot either way), the larger ones,
        // which read as squares once the 1x canvas is upscaled, as discs; the bytes join the same
        // buckets as square caps (0x8000), their soft skirts too (0x4000) (see square/disc).
        // Counting sort into per-bucket index lists (stable, so each bucket draws in the same
        // order as before): one pass over the stars instead of one per bucket
        sortBuckets();
        fillBuckets(gal);
        if (stk > 0) drawTrails(gal, stk);
        if (nB) drawByteTops(gal, cp, sp, inc, rot, RD, gy);
        // HII knots: small rose beads, brief flares (dropped with the glows while scrolling)
        for (i = 0; govLevel < 2 && i < NK; i++) {
            var ka = (0.66 * kArm[i] + 0.9 * kFl[i]) * gal * (small ? 0.75 : 1);
            if (ka < 0.15 || sBucket[i] === 255) continue;
            var kz = (3.3 + 4.2 * kFl[i]) * (small ? 0.8 : 1);
            if (small) kz = Math.min(kz, 2.4 + 3.4 * kFl[i]);  // on a phone the knots sit inside the arm light
            ctx.globalAlpha = ka > 1 ? 1 : ka;
            ctx.drawImage(KGLOW, sX[i] - kz, sY[i] - kz, 2 * kz, 2 * kz);
        }
        for (i = NK; govLevel < 2 && i < nDraw && glows < CFG.GLOW_MAX; i++) {
            if (sSize[i] <= 2 || sBucket[i] === 255) continue;
            var lv = ((sBucket[i] % ALEVELS) + 1) / ALEVELS;
            ctx.globalAlpha = 0.55 * gal * lv;
            ctx.drawImage(GLOW, sX[i] - 5, sY[i] - 5, 10, 10);
            if (glows < 7) { ctx.globalAlpha = 0.28 * gal * lv; ctx.drawImage(GLINT, sX[i] - 7, sY[i] - 7, 14, 14); }
            glows++;
        }
        ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
    }
    function render() {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
        // galaxy pages: while it is in focus down the page, the sky around it softens (at the
        // top the sky is as it always was)
        var skyA = NOGAL ? 1 : 1 - 0.3 * G.focus * smooth(0.3 * H, 1.2 * H, scrollY);
        ctx.globalAlpha = skyA;
        drawDeep(reduced);
        if (!reduced) drawShooters(skyA);
        ctx.globalAlpha = skyA;
        drawField();
        ctx.globalAlpha = 1;
        drawGalaxy();
        drawGroups();
    }

    // ---- scheduler ---------------------------------------------------------------
    var mq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
    var reduced = !!(mq && mq.matches), raf = 0, last = 0, acc = 0, FRAME = 1000 / CFG.FPS;
    // Governor. It used to watch script time only, and on a large desktop screen the cost is
    // raster/GPU, which script time never shows (and its levels 1-2 changed a DPR already at its
    // cap of 1; level 3 raised the gas rate). It now watches the real interval between drawn
    // steps against the step it asked for. Level 0 is the full look; under load it steps down -
    // 1: gas at 4 Hz and DPR 1 (from 1.25), 2: no star glows/glints and 30 fps while
    // scrolling, 3: 70% of the galaxy
    // stars - and back up after 10 s of headroom.
    // The gap it expects is the step rounded up to whole display frames (a 90 Hz screen draws a
    // 60 fps step every second frame, 22 ms, and that is not load), so it can react sooner and
    // to a smaller overrun: 1.25x for 1 s instead of 1.4x for 2 s, which let a large screen
    // drop frames for several seconds of scrolling before it stepped down.
    var gasClock = 0, gasHz = CFG.GAS_HZ, govLevel = 0, govEma = 0, govHigh = 0, govLow = 0, ready = false, lastDraw = 0;
    var vsMin = 1e9, vsPrev = 1e9, vsT = 0;           // display period: the shortest rAF interval over 2 s windows
    function governor(gap, step, dt) {
        var per = Math.min(vsMin, vsPrev), want = step;
        if (per < 100) want = Math.max(step, Math.ceil((step - 1) / per - 1e-3) * per);
        var ratio = gap / want;
        govEma = govEma ? govEma * 0.9 + ratio * 0.1 : ratio;
        if (govEma > 1.25) { govHigh += dt; govLow = 0; } else if (govEma < 1.1) { govLow += dt; govHigh = 0; } else { govHigh = govLow = 0; }
        if (govHigh > 1 && govLevel < 3) { setGov(govLevel + 1); govHigh = 0; govEma = 0; }
        else if (govLow > 10 && govLevel > 0) { setGov(govLevel - 1); govLow = 0; govEma = 0; }
    }
    function setGov(l) {
        govLevel = l;
        gasHz = l >= 1 ? 4 : CFG.GAS_HZ;
        nDraw = l >= 3 ? Math.round(NS * 0.7) : NS;
        // reallocate the backing store at the level's DPR (the gas buffer keeps the size it was
        // sampled at for gov 0: rebuilding its LUT mid-run would be the very hitch being shed)
        var d = dprFor(l);
        if (d !== DPR && W) { DPR = d; canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR); }
    }
    function frame(now) {
        raf = requestAnimationFrame(frame);
        if (!last) { last = now; return; }
        var rd = now - last;
        if (rd >= 4 && rd < 100 && rd < vsMin) vsMin = rd;
        vsT += rd;
        if (vsT > 2000) { vsPrev = vsMin; vsMin = 1e9; vsT = 0; }
        acc += Math.min(rd, 250); last = now;
        // A desktop steps on every display frame (90-180 Hz screens included): native scrolling
        // moves the page each frame, and a sky stepping at 60 against a 165 Hz scroll read as
        // judder. A phone, and gov >= 2, keep 60 fps while the page scrolls and while a shooting
        // star flies (540-900 px/s: at 30 fps it jumped 18-30 px a frame), 30 fps otherwise
        var live = now - lastScrollAt < 1200 || Math.abs(scrollY - smoothY) > 0.5 || shooters.length;
        var step = !small && govLevel < 2 ? 0 : govLevel < 2 && live ? 1000 / 60 : FRAME;
        if (step && acc < step - 1) return;
        var n = step ? Math.max(1, Math.floor((acc + 1) / step)) : 1, dt = Math.min(step ? n * step : acc, 100) / 1000;
        acc = step ? Math.max(0, acc - n * step) : 0;
        var gap = lastDraw ? now - lastDraw : step;
        lastDraw = now;
        // critically damped follow of the real scroll: smooth parallax, no 1-step jumps
        var prevY = smoothY, k = 1 - Math.exp(-dt * 9);
        smoothY += (scrollY - smoothY) * k;
        if (Math.abs(scrollY - smoothY) < 0.05) smoothY = scrollY;
        var dScroll = smoothY - prevY; lastScrollY = scrollY;
        scrollVel += ((dt > 0 ? dScroll / dt : 0) - scrollVel) * Math.min(1, dt * 6);
        T += dt;
        if (gridDirty || Math.abs(scrollY - gridScroll) >= 12) rebuildGrid();
        if (textReady && !G.placed) placeGalaxy();
        if (G.placed) { stepGalaxy(dt, dScroll); stepEvents(dt); }
        stepDeep(dt, dScroll);
        stepShooters(dt);
        stepField(dt, dScroll);
        if (G.placed) stepGroups(dt);
        gasClock += dt; stepDt = dt;
        if (!NOGAL) {
            // a refresh every 1/gasHz s, scrolling or not, spread over the frames of that period
            var hz = gasRate();
            if (gasP >= gasEnd && gasClock >= 1 / hz) { gasClock = 0; gasBegin(T, true); }
            if (gasP < gasEnd) gasRun(Math.ceil(lutN * hz * dt * 1.25) + 4096);
        }
        render();
        if (gap < 1000) governor(gap, Math.max(step, 1000 / 60), dt);   // load = missing 60 fps; a long gap is a hidden tab
    }
    function start() { if (!raf && !reduced && !document.hidden) { last = 0; acc = 0; lastDraw = 0; raf = requestAnimationFrame(frame); } }
    function stop() { if (raf) { cancelAnimationFrame(raf); raf = 0; } }
    function drawStill() {
        if (!reduced) return;
        if (!((gasReady || NOGAL) && textReady)) return;   // never a half-made still frame
        measureNav();
        rebuildGrid();
        if (!G.placed) placeGalaxy();
        lastScrollY = scrollY; smoothY = scrollY; scrollVel = 0;
        G.alpha = 1;
        stepGalaxy(0, 0); stepField(0, 0);
        for (var i = 0; i < NF; i++) { fX[i] = fHx[i]; fY[i] = fHy[i]; }
        if (!groupsStillGood()) instantGroups();
        if (!NOGAL) { gasFade = 1; updateGas(T); }
        render();
    }
    function onScrollEnd() { if (reduced) drawStill(); }
    function setReduced(v) {
        reduced = v;
        if (reduced) { stop(); cOn = false; cOnS.fill(0); swK = 0; drawStill(); } else { start(); }   // the still: no current, no swell
    }
    if (mq) {
        if (mq.addEventListener) mq.addEventListener('change', function (e) { setReduced(e.matches); });
        else if (mq.addListener) mq.addListener(function (e) { setReduced(e.matches); });
    }
    document.addEventListener('visibilitychange', function () { if (document.hidden) stop(); else start(); });

    // ---- resize (debounced; a phone URL bar only moves the height a little) ----
    var resizeTimer = 0;
    function onResize() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            var m = measure(), dprNow = dprFor(govLevel);
            if (m.w === W && m.h === H && dprNow === DPR) return;
            var heightOnly = m.w === W && Math.abs(m.h - H) / H < 0.2 && dprNow === DPR;
            var ow = W, oh = H, wasSmall = small;
            applySize(m.w, m.h);
            gridDirty = true; measureDoc(); measureHero();
            if (!heightOnly) {
                rescaleField(W / ow, H / oh);
                rescaleDeep(W / ow, H / oh);
                ensureGasBuffer();
                if (small !== wasSmall) buildStars();
                for (var g = 0; g < groups.length; g++) if (groups[g].on && !sideOf(fX[groups[g].mem[0]], fY[groups[g].mem[0]])) releaseGroup(groups[g]);
                requestIndex();
            }
            if (reduced) drawStill();
        }, 180);
    }
    window.addEventListener('resize', onResize);

    // ---- init -----------------------------------------------------------------
    var m0 = measure();
    applySize(m0.w, m0.h);
    buildStars();
    buildField();
    buildDeep();
    ensureGasBuffer();
    buildGas();
    buildIndex(function () { if (reduced) drawStill(); });
    window.addEventListener('load', requestIndex);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(requestIndex);
    if (window.ResizeObserver && document.body) new ResizeObserver(requestIndex).observe(document.body);
    (function waitGas() {                               // reduced motion: draw once everything is ready
        if (!reduced) return;
        if (gasReady && lutN && textReady) drawStill(); else setTimeout(waitGas, 120);
    })();
    start();
})();

// ── 3D Tilt & Mouse Glow (glow painted by CSS from --mx/--my) ──
document.querySelectorAll('[data-tilt]').forEach(card => {
    let ev = null, queued = false;
    const apply = () => {
        queued = false;
        if (!ev) return;
        const r = card.getBoundingClientRect();
        const x = ev.clientX - r.left, y = ev.clientY - r.top;
        const dx = (x - r.width / 2) / (r.width / 2), dy = (y - r.height / 2) / (r.height / 2);
        card.style.transform = `perspective(1000px) rotateY(${dx * 3}deg) rotateX(${-dy * 3}deg) translateY(-4px)`;
        card.style.setProperty('--mx', `${x}px`);
        card.style.setProperty('--my', `${y}px`);
    };
    card.addEventListener('pointermove', e => {
        if (e.pointerType !== 'mouse' || window.innerWidth <= 1024) return;
        ev = e;
        if (!queued) { queued = true; requestAnimationFrame(apply); }
    }, { passive: true });
    card.addEventListener('pointerleave', () => {
        ev = null;
        card.style.transform = '';
    });
});

// Mobile Nav Toggle
const navToggle = document.querySelector('.nav-toggle');
const navLinks = document.querySelector('.nav-links-wrap');

if (navToggle && navLinks) {
    navToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        navLinks.classList.toggle('show');
        document.body.classList.toggle('nav-open');
        const icon = navToggle.querySelector('i');
        if (icon) {
            if (navLinks.classList.contains('show')) {
                icon.classList.remove('fa-bars');
                icon.classList.add('fa-times');
            } else {
                icon.classList.remove('fa-times');
                icon.classList.add('fa-bars');
            }
        }
    });
}

// ── Documentation Interaction ──
document.addEventListener('click', (e) => {
    // 1. Close mobile menu on click outside
    if (navLinks && navLinks.classList.contains('show')) {
        if (!navLinks.contains(e.target) && !navToggle.contains(e.target)) {
            navLinks.classList.remove('show');
            document.body.classList.remove('nav-open');
            const icon = navToggle.querySelector('i');
            if (icon) {
                icon.classList.remove('fa-times');
                icon.classList.add('fa-bars');
            }
        }
    }
    
    // 2. Documentation Sidebar Toggle (Mobile)
    const sidebar = e.target.closest('.doc-sidebar');
    const sidebarTitle = e.target.closest('.doc-sidebar h3');
    
    if (sidebarTitle && window.innerWidth <= 960) {
        sidebar.classList.toggle('active');
    } else if (sidebar && sidebar.classList.contains('active')) {
        const isLink = e.target.tagName === 'A';
        const isOutside = !sidebar.contains(e.target);
        if ((isLink || isOutside) && window.innerWidth <= 960) {
            sidebar.classList.remove('active');
        }
    }

    // 4. File Tree Toggle
    const folder = e.target.closest('.tree-folder');
    if (folder) {
        folder.classList.toggle('open');
        const parent = folder.closest('.tree-item');
        if (parent) {
            const children = parent.querySelector('.tree-children');
            if (children) children.classList.toggle('visible');
        }
    }
});

// ── Terminal Typing Sim ──
const terminalLines = ['tl0', 'tl1', 'tl2', 'tl3', 'tl4', 'tl5'];
function showTerminal() {
    terminalLines.forEach((id, i) => {
        setTimeout(() => {
            const el = document.getElementById(id);
            if (el) el.classList.add('show');
        }, i * 700 + 500);
    });

    setTimeout(() => {
        terminalLines.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.remove('show');
        });
        setTimeout(showTerminal, 1500);
    }, terminalLines.length * 700 + 3000);
}
if (document.getElementById('term-body')) {
    showTerminal();
}

// ── Scroll Reveal ──
const revealObserver = new IntersectionObserver(entries => {
    entries.forEach(e => {
        if (e.isIntersecting) e.target.classList.add('visible');
    });
}, { threshold: 0.1 });
document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

// ── Counter Animation ──
function animCount(el) {
    const target = parseInt(el.dataset.count);
    const suffix = el.dataset.suffix || '';
    let start = 0, duration = 2000, startTime = null;

    function step(ts) {
        if (!startTime) startTime = ts;
        const prog = Math.min((ts - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - prog, 4); 
        el.textContent = Math.round(eased * target) + suffix;
        if (prog < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

const counterObs = new IntersectionObserver(entries => {
    entries.forEach(e => {
        if (e.isIntersecting) {
            animCount(e.target);
            counterObs.unobserve(e.target);
        }
    });
}, { threshold: 0.5 });
document.querySelectorAll('[data-count]').forEach(el => counterObs.observe(el));

// ── Stagger: children of grids rise one after another ──
document.querySelectorAll('.reveal').forEach(group => {
    let i = 0;
    for (const child of group.children) {
        if (!child.classList.contains('reveal')) child.style.setProperty('--i', String(i++ % 8));
    }
});

// ── Sidebar Scroll Spy ──
const spyOptions = { rootMargin: '-20% 0px -70% 0px', threshold: 0 };
const spyObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const id = entry.target.getAttribute('id');
            document.querySelectorAll('.doc-sidebar a').forEach(a => {
                a.classList.toggle('active', a.getAttribute('href') === `#${id}`);
            });
        }
    });
}, spyOptions);

// Observe all elements that have IDs and are targets of sidebar links
document.querySelectorAll('.doc-sidebar a[href^="#"]').forEach(anchor => {
    const id = anchor.getAttribute('href').slice(1);
    if (id) {
        const target = document.getElementById(id);
        if (target) {
            spyObserver.observe(target);
        }
    }
});

// Mobile viewport fix
function setVH() {
    let vh = window.innerHeight * 0.01;
    document.documentElement.style.setProperty('--vh', `${vh}px`);
}
window.addEventListener('resize', setVH);
setVH();

// ── Motion: one scroll scheduler, inertial wheel scrolling, section transitions ──
// Every scroll-driven effect runs from ONE passive listener and ONE rAF, reading all
// layout first and writing only transform/opacity/classes after.
(function ceMotion() {
    'use strict';
    var root = document.documentElement, body = document.body;
    if (!body || !window.requestAnimationFrame) return;
    var calm = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    function wide() { return window.innerWidth > 960; }

    // ---- scheduler -------------------------------------------------------------
    var readers = [], writers = [], queued = false;
    function frame() {
        queued = false;
        var y = window.scrollY, vh = window.innerHeight, i;
        var state = { y: y, vh: vh, docH: Math.max(1, root.scrollHeight - vh) };
        for (i = 0; i < readers.length; i++) readers[i](state);
        for (i = 0; i < writers.length; i++) writers[i](state);
    }
    function schedule() { if (!queued) { queued = true; requestAnimationFrame(frame); } }
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });
    function on(read, write) { if (read) readers.push(read); if (write) writers.push(write); }

    // ---- progress bar + nav shrink + hero fade --------------------------------------
    var bar = document.getElementById('scroll-progress'), nav = document.getElementById('main-nav');
    var hero = document.querySelector('.hero'), heroH = 0, navOn = null;
    on(function () { heroH = hero ? hero.offsetHeight : 0; }, function (s) {
        if (bar) bar.style.transform = 'scaleX(' + (s.y / s.docH).toFixed(4) + ')';
        var want = s.y > 50 && wide();
        if (nav && want !== navOn) { navOn = want; nav.classList.toggle('scrolled', want); }
        if (hero && !hero.classList.contains('pin')) {
            if (calm.matches) { hero.style.transform = ''; hero.style.opacity = ''; }
            else {
                var p = clamp(s.y / (heroH || s.vh), 0, 1);
                hero.style.transform = p ? 'scale(' + (1 - 0.08 * p).toFixed(4) + ')' : '';
                hero.style.opacity = p ? (1 - 0.85 * p).toFixed(3) : '';
            }
        }
    });

    // ---- headline word reveals --------------------------------------------------------
    function splitTitle(el) {
        if (el.dataset.words) return;
        el.dataset.words = '1';
        var out = document.createDocumentFragment(), n = 0;
        function unit(node) {
            var w = document.createElement('span'), wi = document.createElement('span');
            w.className = 'w'; wi.className = 'wi'; wi.style.setProperty('--wi', String(n++));
            wi.appendChild(node); w.appendChild(wi); return w;
        }
        Array.prototype.slice.call(el.childNodes).forEach(function (node) {
            if (node.nodeType === 3) {
                node.textContent.split(/(\s+)/).forEach(function (part) {
                    if (!part) return;
                    if (/^\s+$/.test(part)) out.appendChild(document.createTextNode(' '));
                    else out.appendChild(unit(document.createTextNode(part)));
                });
            } else if (node.nodeName === 'BR') {
                out.appendChild(node);
            } else {
                out.appendChild(unit(node));
            }
        });
        el.textContent = '';
        el.appendChild(out);
    }
    var titles = document.querySelectorAll('.section-title');
    if (!calm.matches && 'IntersectionObserver' in window) {
        var tio = new IntersectionObserver(function (entries) {
            entries.forEach(function (e) {
                if (!e.isIntersecting) return;
                var t = e.target, n = t.querySelectorAll('.wi').length;
                t.classList.add('words-in'); tio.unobserve(t);
                setTimeout(function () {
                    var tr = t.getBoundingClientRect();
                    t.style.setProperty('--tw', String(Math.round(tr.width)));
                    Array.prototype.forEach.call(t.querySelectorAll('.wi'), function (wi) {
                        wi.style.setProperty('--wx', String(Math.round(wi.getBoundingClientRect().left - tr.left)));
                    });
                    t.classList.add('sheen');
                    setTimeout(function () { t.classList.remove('sheen'); }, 1350);
                }, (n - 1) * 60 + 850);
            });
        }, { threshold: 0.2, rootMargin: '0px 0px -8% 0px' });
        Array.prototype.forEach.call(titles, function (t) { splitTitle(t); t.classList.add('words'); tio.observe(t); });
    }

    // ---- home page scenes: sections arrive and leave like scenes ----------------------------
    var scenes = [];
    if (body.classList.contains('home')) {
        Array.prototype.forEach.call(document.querySelectorAll('body.home > section'), function (sec) {
            if (sec.classList.contains('hero') || sec.id === 'loop' || sec.id === 'difference') return;
            var c = sec.querySelector(':scope > .container');
            if (c) scenes.push({ sec: sec, c: c, top: 0, bot: 0 });
        });
    }
    on(function () {
        for (var i = 0; i < scenes.length; i++) { var r = scenes[i].sec.getBoundingClientRect(); scenes[i].top = r.top; scenes[i].bot = r.bottom; }
    }, function (s) {
        for (var i = 0; i < scenes.length; i++) {
            var sc = scenes[i];
            if (calm.matches || !wide()) { sc.c.style.transform = ''; sc.c.style.opacity = ''; sc.c.classList.remove('ce-live'); continue; }
            if (sc.bot < -50 || sc.top > s.vh + 50) continue;
            var e = clamp((s.vh - sc.top) / (s.vh * 0.32), 0, 1);           // entering
            var l = clamp((s.vh * 0.32 - sc.bot) / (s.vh * 0.32), 0, 1);    // leaving
            var ee = 1 - Math.pow(1 - e, 3);
            var op = (0.35 + 0.65 * ee) * (1 - 0.5 * l), sc2 = (0.965 + 0.035 * ee) * (1 - 0.02 * l), ty = 40 * (1 - ee);
            var still = op > 0.995 && sc2 > 0.9995 && ty < 0.2;
            // a layer while it moves, so the big text subtree is composited, not repainted
            // every scroll frame; dropped at rest so layers don't pile up
            sc.c.classList.toggle('ce-live', !still);
            sc.c.style.opacity = op > 0.995 ? '' : op.toFixed(3);
            sc.c.style.transform = (sc2 > 0.9995 && ty < 0.2) ? '' : 'translateY(' + ty.toFixed(1) + 'px) scale(' + sc2.toFixed(4) + ')';
        }
    });

    // ---- pinned "Closed Loop" story ---------------------------------------------------------
    var loop = document.getElementById('loop');
    var track = loop && loop.querySelector('.ce-loop') ? loop.querySelector('.ce-loop').parentElement : null;
    var steps = track ? track.querySelectorAll('.ce-loop-step') : [], lp = { top: 0, h: 1 }, lastStep = -2;
    var loopEl = loop ? loop.querySelector('.ce-loop') : null;   // --lp is read only by .ce-loop::after
    function pinOn() { return track && wide() && !calm.matches; }
    on(function () {
        if (!track) return;
        loop.classList.toggle('pin', pinOn());
        var r = track.getBoundingClientRect(); lp.top = r.top; lp.h = r.height;
    }, function (s) {
        if (!track) return;
        if (!pinOn()) { if (lastStep !== -1) { lastStep = -1; Array.prototype.forEach.call(steps, function (st) { st.classList.add('on'); }); loop.classList.add('done'); } return; }
        var p = clamp((s.vh * 0.12 - lp.top) / Math.max(1, lp.h - s.vh * 0.85), 0, 1);
        var k = Math.min(steps.length - 1, Math.floor(p * steps.length));
        loopEl.style.setProperty('--lp', p.toFixed(4));
        if (k !== lastStep) {
            lastStep = k;
            Array.prototype.forEach.call(steps, function (st, i) { st.classList.toggle('on', i <= k); });
            loop.classList.toggle('done', k >= steps.length - 1);
        }
    });

    // ---- Detection vs Reconstruction wipe -------------------------------------------------
    var diff = document.getElementById('difference');
    var dgrid = diff ? diff.querySelector('.bento') : null, dr = { top: 0, h: 1 };
    on(function () { if (dgrid) { var r = dgrid.getBoundingClientRect(); dr.top = r.top; dr.h = r.height; } }, function (s) {
        if (!dgrid) return;
        var live = wide() && !calm.matches;
        diff.classList.toggle('wipe', live);
        if (!live) return;
        var p = clamp((s.vh * 0.9 - dr.top) / (dr.h * 0.85), 0, 1);
        // set on the grid, the only reader, so each update restyles its subtree, not the section's
        dgrid.style.setProperty('--wa', clamp(p / 0.3, 0, 1).toFixed(3));
        dgrid.style.setProperty('--wq', clamp((p - 0.28) / 0.42, 0, 1).toFixed(4));
        dgrid.style.setProperty('--wb', clamp((p - 0.62) / 0.3, 0, 1).toFixed(3));
    });

    // ---- glide: mouse-wheel notches and same-page anchors (touch, trackpads, keys and the
    // scrollbar stay native) -----------------------------------------------------------------
    // Each notch eases the page from this rAF, in the same frame the sky reads scrollY, so the
    // page and the parallax move in lockstep. fbfc250 took the wheel glide out because the page
    // then waited behind the background canvases (33 ms frames on a 3440 px screen); the sky and
    // the centrepieces now cost 1-2 ms a frame. If one of them gets heavy again, measure the
    // scroll before keeping this. The ease is time-based, the same at 60 and 180 Hz.
    var target = window.scrollY, cur = window.scrollY, set = window.scrollY, running = false, last = 0;
    function maxY() { return Math.max(0, root.scrollHeight - window.innerHeight); }
    function tick(now) {
        var dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now;
        if (Math.abs(window.scrollY - set) > 2) { running = false; root.style.scrollBehavior = ''; return; }   // keys / scrollbar took over
        cur += (target - cur) * (1 - Math.exp(-dt * 8));
        if (Math.abs(target - cur) < 0.5) cur = target;
        window.scrollTo(0, cur);
        set = window.scrollY;
        if (cur !== target) requestAnimationFrame(tick);
        else { running = false; root.style.scrollBehavior = ''; }
    }
    function glide(to) {
        target = clamp(to, 0, maxY());
        if (!running) { cur = set = window.scrollY; running = true; last = performance.now(); root.style.scrollBehavior = 'auto'; requestAnimationFrame(tick); }
    }
    function nestedCanScroll(el, dy) {
        for (; el && el !== body && el !== root; el = el.parentElement) {
            if (el.scrollHeight <= el.clientHeight + 1) continue;
            var oy = getComputedStyle(el).overflowY;
            if (oy !== 'auto' && oy !== 'scroll') continue;
            if (dy > 0 ? el.scrollTop + el.clientHeight < el.scrollHeight - 1 : el.scrollTop > 0) return true;
        }
        return false;
    }
    // A mouse wheel only: its notches come as whole deltas of 50+ px (or lines). A trackpad
    // already scrolls smoothly; its small, fractional or sideways deltas keep it native for 1.5 s
    var tpUntil = 0;
    window.addEventListener('wheel', function (e) {
        if (calm.matches || e.ctrlKey || e.shiftKey || e.defaultPrevented) return;
        var dy = e.deltaY, now = performance.now();
        if (e.deltaMode === 0 && (Math.abs(dy) < 50 || dy !== Math.round(dy) || e.deltaX)) { tpUntil = now + 1500; return; }
        if (now < tpUntil || !dy) return;
        if (e.deltaMode === 1) dy *= 40; else if (e.deltaMode === 2) dy *= window.innerHeight;
        if (body.style.overflow === 'hidden' || root.style.overflow === 'hidden' || (e.target.closest && e.target.closest('[aria-modal="true"]'))) return;
        if (nestedCanScroll(e.target, dy)) return;
        e.preventDefault();
        glide((running ? target : window.scrollY) + dy);
    }, { passive: false });
    // same-page anchors glide, landing below the fixed nav
    document.addEventListener('click', function (e) {
        var a = e.target.closest && e.target.closest('a[href*="#"]');
        if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
        var url = new URL(a.href, location.href);
        if (url.pathname !== location.pathname || !url.hash || url.hash === '#') return;
        var el = document.getElementById(decodeURIComponent(url.hash.slice(1)));
        if (!el) return;
        e.preventDefault();
        var off = nav ? nav.getBoundingClientRect().bottom + 16 : 80;
        // where it sits in the layout, not where a transform draws it: a .reveal card not yet
        // shown is drawn 30px low and slides up after the glide, which left it under the nav
        var to = el.getBoundingClientRect().top + window.scrollY - off;
        if (el.offsetParent) {
            var y = 0;
            for (var p = el; p; p = p.offsetParent) y += p.offsetTop;
            to = y - off;
        }
        if (calm.matches) window.scrollTo(0, to); else glide(to);
        if (history.pushState) history.pushState(null, '', url.hash);
    });

    function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

    // ---- Sentinel: read-along paragraphs light up word by word -------------------------------
    var ras = [];
    if (!calm.matches) {
        Array.prototype.forEach.call(document.querySelectorAll('.read-along'), function (el) {
            var words = [];
            (function walk(node) {
                Array.prototype.slice.call(node.childNodes).forEach(function (c) {
                    if (c.nodeType === 1) { walk(c); return; }
                    if (c.nodeType !== 3 || !c.textContent.trim()) return;
                    var frag = document.createDocumentFragment();
                    c.textContent.split(/(\s+)/).forEach(function (part) {
                        if (!part) return;
                        if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
                        var w = document.createElement('span'); w.className = 'rw'; w.textContent = part;
                        frag.appendChild(w); words.push(w);
                    });
                    node.replaceChild(frag, c);
                });
            })(el);
            el.classList.add('ra');
            ras.push({ el: el, words: words, k: 0, top: 0, h: 1 });
        });
    }
    on(function () {
        for (var i = 0; i < ras.length; i++) { var r = ras[i].el.getBoundingClientRect(); ras[i].top = r.top; ras[i].h = r.height; }
    }, function (s) {
        for (var i = 0; i < ras.length; i++) {
            var ra = ras[i], n = ra.words.length;
            var p = clamp((s.vh * 0.88 - ra.top) / (ra.h + s.vh * 0.25), 0, 1), k = Math.round(p * n), j;
            if (k > ra.k) for (j = ra.k; j < k; j++) ra.words[j].classList.add('lit');
            else if (k < ra.k) for (j = k; j < ra.k; j++) ra.words[j].classList.remove('lit');
            ra.k = k;
        }
    });

    // ---- Sentinel: the numbers count with the scroll -----------------------------------------
    var st = document.querySelector('.s-stats');
    var stItems = st && !calm.matches ? Array.prototype.map.call(st.querySelectorAll('.s-stat'), function (it) {
        var num = it.querySelector('.s-num');
        return { it: it, val: it.querySelector('.s-val'), to: Number(num.dataset.to) || 0, v: -1 };
    }) : [];
    var sts = { on: null, top: 0, h: 1 };
    on(function () {
        if (!stItems.length) return;
        var want = wide();
        if (want !== sts.on) { sts.on = want; st.classList.toggle('pin', want); }
        var r = st.getBoundingClientRect(); sts.top = r.top; sts.h = r.height;
    }, function (s) {
        if (!stItems.length || sts.top > s.vh * 1.2 || sts.top + sts.h < -s.vh * 0.2) return;
        var p = sts.on ? clamp((s.vh * 0.6 - sts.top) / Math.max(1, sts.h - s.vh * 0.4), 0, 1)
                       : clamp((s.vh * 0.92 - sts.top) / (s.vh * 0.6), 0, 1);
        for (var i = 0; i < stItems.length; i++) {
            var x = stItems[i], pi = easeOut(clamp((p - i * 0.07) / 0.4, 0, 1)), v = Math.round(x.to * pi);
            if (v !== x.v) { x.v = v; x.val.textContent = v.toLocaleString('en-US'); }
            x.it.style.opacity = pi >= 1 ? '' : (0.25 + 0.75 * pi).toFixed(3);
            x.it.style.transform = pi >= 1 ? '' : 'scale(' + (0.92 + 0.08 * pi).toFixed(4) + ')';
        }
    });

    frame();                    // first state before first paint: pin, wordmark scale, hint
})();
