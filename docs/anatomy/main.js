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

    var TAU = Math.PI * 2;
    var CFG = {
        FPS: 30,
        DPR_MAX: 1,
        // galaxy
        R_K: 0.312, R_MIN: 143, R_MAX: 680,    // disk radius (CSS px) = clamp(R_K*sqrt(W*H)): the reference, +30%
        PITCH: 3.1,                            // log-spiral pitch of the two arms
        PATTERN_W: TAU / 480,                  // arm pattern: one turn in 8 minutes
        ORBIT_K: 0.022, ORBIT_C: 0.15,         // material: w(r) = K/(r+C)  (inner faster)
        STREAM: 0.004,                         // arm stars lose 0.4% of radius per second
        TWIST_A: 0.28, TWIST_T: 170,           // wind/unwind: 0.28*sin(2pi t/170)*(r-0.4)
        BREATH_T: 9,                           // core breathing period (s)
        SPIN_MAX: 0.35,                        // extra rad/s at full scroll speed
        GAS_ALPHA: 0.8, STAR_ALPHA: 0.85,
        GALAXY_ALPHA: 0.9, GALAXY_ALPHA_SMALL: 0.8,
        STARS: 840, STARS_SMALL: 546, GLOW_MAX: 18,
        GAS_HZ: 8,
        POLAR_A: 1024, POLAR_R: 192,           // gas textures, polar (angle x radius): ~1.3 buffer px per cell at the rim
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
    var W = 0, H = 0, DPR = 1, dprCap = CFG.DPR_MAX, small = false, R = 80;
    function measure() {
        var w = canvas.clientWidth || window.innerWidth, h = canvas.clientHeight || window.innerHeight;
        return { w: Math.max(1, Math.round(w)), h: Math.max(1, Math.round(h)) };
    }
    function applySize(w, h) {
        W = w; H = h; small = W < 700;
        DPR = Math.min(dprCap, window.devicePixelRatio || 1);
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
            rects = out; nRects = k / 4; fixedEls = fx; textReady = true; gridDirty = true; measureDoc();
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
    var A = CFG.POLAR_A, NR = CFG.POLAR_R;
    var ARM = new Uint8Array(A * NR), CLUMP = new Uint8Array(A * NR), gasReady = false, gasFade = 0;
    var ROW_R = new Float32Array(NR), ROW_RGB = new Uint8Array(NR * 3);
    (function rowColors() {
        var stops = [[0.00, 58, 36, 118], [0.14, 96, 66, 180], [0.28, 167, 139, 250], [0.48, 99, 102, 241], [0.70, 34, 211, 238], [1.0, 103, 232, 249]];
        for (var j = 0; j < NR; j++) {
            var r = (j + 0.5) / NR, s = 0;
            ROW_R[j] = r;
            while (s < stops.length - 2 && r > stops[s + 1][0]) s++;
            var p = stops[s], q = stops[s + 1], t = smooth(p[0], q[0], r);
            ROW_RGB[j * 3] = lerp(p[1], q[1], t); ROW_RGB[j * 3 + 1] = lerp(p[2], q[2], t); ROW_RGB[j * 3 + 2] = lerp(p[3], q[3], t);
        }
    })();
    function buildGas() {
        var j = 0;
        runSliced(function () {
            var r = ROW_R[j], disk = Math.exp(-r / 0.46), bulge = Math.exp(-r * r / 0.010);
            var rim = 1 - smooth(0.70, 1.0, r);
            for (var i = 0; i < A; i++) {
                var th = TAU * i / A, x = r * Math.cos(th), y = r * Math.sin(th);
                var n1 = fbm(x * 3.2 + 11, y * 3.2 + 7), n2 = fbm(x * 7.5 + 31, y * 7.5 + 3);
                var phi = th - CFG.PITCH * Math.log(r + 0.05) + (n1 - 0.5) * 1.3;
                var arm = Math.pow(0.5 + 0.5 * Math.cos(2 * phi), 2.4);
                // dust lane: a thin dark band riding just inside each arm
                var lane = Math.pow(0.5 + 0.5 * Math.cos(2 * (phi + 0.38)), 7) * smooth(0.12, 0.38, r) * (0.6 + 0.4 * n2);
                var rimN = 1 - smooth(0.62, 1.0, r + (n1 - 0.5) * 0.18);
                var dens = 0.12 * bulge + disk * (0.16 + 0.84 * arm) * (0.7 + 0.6 * n2) * (0.85 + 0.6 * smooth(0.35, 0.8, r));
                dens *= 1 - 0.6 * lane;
                ARM[j * A + i] = clamp(dens * rimN * 255 * 1.35, 0, 255);
                var cl = smooth(0.56, 0.84, n2) * (0.25 + 0.75 * arm) * disk * rim * smooth(0.12, 0.3, r) * (1 - 0.7 * lane);
                CLUMP[j * A + i] = clamp(cl * 255 * 2.0, 0, 255);
            }
            return ++j >= NR;
        }, function () { gasReady = true; });
    }
    var gasCan = document.createElement('canvas'), gasCtx = gasCan.getContext('2d'), gasImg = null, gasU32 = null;
    var S = 0, lutIdx = null, lutRow = null, lutCol = null, lutEdge = null, lutN = 0;
    var haloCan = document.createElement('canvas'), haloCtx = haloCan.getContext('2d');
    var armShift = new Int32Array(NR), clumpShift = new Int32Array(NR), rowGain = new Float32Array(NR);
    function ensureGasBuffer() {
        var want = clamp(Math.round(2 * R * DPR * 0.6), 192, 420);
        if (S && Math.abs(want - S) / S < 0.15) return;
        S = want; gasCan.width = gasCan.height = S;
        haloCan.width = haloCan.height = Math.max(32, S >> 2);
        gasImg = gasCtx.createImageData(S, S); gasU32 = new Uint32Array(gasImg.data.buffer);
        var max = S * S, idx = new Uint32Array(max), rw = new Uint16Array(max), cl = new Uint16Array(max),
            ed = new Uint8Array(max), n = 0;
        for (var y = 0; y < S; y++) for (var x = 0; x < S; x++) {
            var u = (x + 0.5) / S * 2 - 1, v = (y + 0.5) / S * 2 - 1, r = Math.sqrt(u * u + v * v);
            if (r >= 1) continue;
            var th = Math.atan2(v, u);
            // soft, slightly ragged rim: the disc dissolves instead of ending on a pixel circle
            var feather = 1 - smooth(0.78 + 0.06 * (noise(Math.cos(th) * 3 + 5, Math.sin(th) * 3 + 9) - 0.5), 1.0, r);
            if (feather <= 0.004) continue;
            idx[n] = y * S + x; rw[n] = Math.min(NR - 1, (r * NR) | 0);
            cl[n] = ((((th / TAU) + 1) % 1) * A) & (A - 1); ed[n] = (feather * 255) | 0; n++;
        }
        lutIdx = idx; lutRow = rw; lutCol = cl; lutEdge = ed; lutN = n;
    }
    var gasTimer = 0;
    function updateGas(t) {
        if (!gasReady || !lutN) return;
        var breath = Math.sin(TAU * t / CFG.BREATH_T), twist = CFG.TWIST_A * Math.sin(TAU * t / CFG.TWIST_T);
        var k = A / TAU, j;
        for (j = 0; j < NR; j++) {
            var r = ROW_R[j];
            armShift[j] = Math.round(twist * (r - 0.4) * k);
            var rel = (CFG.ORBIT_K / (r + CFG.ORBIT_C) - CFG.PATTERN_W) * t;   // clouds overtake the pattern inside
            clumpShift[j] = Math.round(((rel % TAU) + TAU) * k);
            rowGain[j] = (1 + 0.14 * breath * Math.exp(-r / 0.14)) * (0.92 + 0.08 * Math.sin(t * 0.37 + r * 4));
        }
        gasU32.fill(0);
        var m = A - 1;
        for (var p = 0; p < lutN; p++) {
            j = lutRow[p];
            var c0 = lutCol[p];
            var a = ARM[j * A + ((c0 + armShift[j]) & m)], c = CLUMP[j * A + ((c0 + clumpShift[j]) & m)];
            var al = (a * 0.75 + c * 0.6) * rowGain[j] * lutEdge[p] / 255;
            if (al < 1.5) continue;
            var f = c / 255, j3 = j * 3;
            var R8 = ROW_RGB[j3] + (225 - ROW_RGB[j3]) * f * 0.55, G8 = ROW_RGB[j3 + 1] + (230 - ROW_RGB[j3 + 1]) * f * 0.55,
                B8 = ROW_RGB[j3 + 2] + (255 - ROW_RGB[j3 + 2]) * f * 0.55;
            gasU32[lutIdx[p]] = ((al > 255 ? 255 : al) << 24) | ((B8 & 255) << 16) | ((G8 & 255) << 8) | (R8 & 255);
        }
        gasCtx.putImageData(gasImg, 0, 0);
        // soft glow around the arms: a quarter-resolution copy blended back into the buffer,
        // here at the gas rate instead of as a second full-size draw every frame
        haloCtx.clearRect(0, 0, haloCan.width, haloCan.height);
        haloCtx.drawImage(gasCan, 0, 0, haloCan.width, haloCan.height);
        gasCtx.globalCompositeOperation = 'lighter'; gasCtx.globalAlpha = 0.3;
        gasCtx.drawImage(haloCan, 0, 0, S, S);
        gasCtx.globalCompositeOperation = 'source-over'; gasCtx.globalAlpha = 1;
    }

    // ---- galaxy: stars (typed arrays) ----------------------------------------------
    var NS = 0, sKind, sR, sTh, sOff, sSize, sAlpha, sTw, sPh, sCol, sFade, sX, sY, sBucket, nDraw = 0;
    var STAR_RGB = ['255,222,196', '198,216,255', '232,234,255', '255,170,196'];   // bulge warm, arms blue-white, rose giants
    var ALEVELS = 6, BUCKET_STYLE = [];
    for (var ci = 0; ci < STAR_RGB.length; ci++) for (var ai = 0; ai < ALEVELS; ai++) {
        BUCKET_STYLE.push('rgba(' + STAR_RGB[ci] + ',' + (((ai + 1) / ALEVELS) * CFG.STAR_ALPHA).toFixed(3) + ')');
    }
    function placeArmStar(i, rim) {
        sR[i] = rim ? 0.86 + R0() * 0.06 : 0.08 + Math.pow(R0(), 0.8) * 0.84;
        sOff[i] = (R0() < 0.5 ? 0 : Math.PI) + gauss(R0) * 0.22;
        sFade[i] = rim ? 0 : 1;
    }
    function buildStars() {
        NS = small ? CFG.STARS_SMALL : CFG.STARS;
        sKind = new Uint8Array(NS); sR = new Float32Array(NS); sTh = new Float32Array(NS); sOff = new Float32Array(NS);
        sSize = new Float32Array(NS); sAlpha = new Float32Array(NS); sTw = new Float32Array(NS); sPh = new Float32Array(NS);
        sCol = new Uint8Array(NS); sFade = new Float32Array(NS); sX = new Float32Array(NS); sY = new Float32Array(NS);
        sBucket = new Uint8Array(NS);
        for (var i = 0; i < NS; i++) {
            var u = R0();
            if (u < 0.10) { sKind[i] = 0; sR[i] = 0.02 + Math.abs(gauss(R0)) * 0.08; sTh[i] = R0() * TAU; sCol[i] = 0; sFade[i] = 0.55; }
            else if (u < 0.70) { sKind[i] = 1; placeArmStar(i, false); sCol[i] = R0() < 0.12 ? 3 : 1; }
            else { sKind[i] = 2; sR[i] = Math.min(0.95, -Math.log(1 - R0()) * 0.27); sTh[i] = R0() * TAU; sCol[i] = 2; sFade[i] = 1; }
            var z = R0();
            sSize[i] = z < 0.03 ? 2.2 : z < 0.15 ? 1.4 : 0.8 + R0() * 0.4;
            sAlpha[i] = 0.35 + R0() * 0.65; sTw[i] = 0.6 + R0() * 2.2; sPh[i] = R0() * TAU;
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
    var BLOOM = document.createElement('canvas');
    (function () {
        BLOOM.width = BLOOM.height = 128;
        var g = BLOOM.getContext('2d'), gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
        gr.addColorStop(0, 'rgba(236,226,255,0.9)'); gr.addColorStop(0.18, 'rgba(176,150,255,0.45)');
        gr.addColorStop(0.5, 'rgba(110,86,210,0.12)'); gr.addColorStop(1, 'rgba(90,70,190,0)');
        g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
    })();
    var GLOW = document.createElement('canvas');
    (function () {
        GLOW.width = GLOW.height = 32;
        var g = GLOW.getContext('2d'), gr = g.createRadialGradient(16, 16, 0, 16, 16, 16);
        gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.25, 'rgba(205,222,255,0.55)');
        gr.addColorStop(1, 'rgba(205,222,255,0)');
        g.fillStyle = gr; g.fillRect(0, 0, 32, 32);
    })();

    // ---- galaxy: motion ------------------------------------------------------------
    var G = { x: 0, y: 0, vx: 0, vy: 0, carry: 0, carryV: 0, rot: 0, spin: 0, incl: 0.5, pa: -0.45, ph: 0, placed: false, dim: 1, alpha: 0 };
    var T = 30;                                     // sky clock (s)
    var NAV = document.getElementById('main-nav'), navB = 0;
    function measureNav() {
        if (!NAV) { navB = 0; return; }
        var r = NAV.getBoundingClientRect();
        navB = r.bottom > 0 && r.bottom < H * 0.4 ? r.bottom : 0;
    }
    function navBottom() { return navB; }
    var docH = 1, scrollFrac = 0, gmx = 0, gmy = 0;
    function measureDoc() { docH = Math.max(1, (document.documentElement.scrollHeight || H) - H); }
    function galaxyTarget(t, out) {                  // slow figure-eight across the screen
        var p = scrollFrac;
        out[0] = W * (0.5 + 0.36 * Math.sin(t / 240 + 0.4 * p)) + gmx * 30;
        out[1] = H * (0.5 + 0.30 * Math.sin(t / 180 + 1.1 + 0.3 * p)) + gmy * 20;
        return out;
    }
    var TMP = [0, 0];
    function placeGalaxy() {
        measureDoc(); scrollFrac = clamp(scrollY / docH, 0, 1);
        galaxyTarget(T, TMP);
        G.x = TMP[0]; G.y = TMP[1]; G.vx = G.vy = 0; G.placed = true;
    }
    function galaxyDist(x, y) {                     // distance in the tilted disk, in units of R
        var dx = x - G.x, dy = y - (G.y + G.carry), c = Math.cos(-G.pa), s = Math.sin(-G.pa);
        var u = dx * c - dy * s, v = (dx * s + dy * c) / G.incl;
        return Math.sqrt(u * u + v * v) / R;
    }
    function stepGalaxy(dt, dScroll) {
        scrollFrac += (clamp(scrollY / docH, 0, 1) - scrollFrac) * Math.min(1, dt * 2.5);
        var tmx = mouse.on && mouse.mouse ? mouse.x / W - 0.5 : 0, tmy = mouse.on && mouse.mouse ? mouse.y / H - 0.5 : 0;
        gmx += (tmx - gmx) * Math.min(1, dt * 1.2); gmy += (tmy - gmy) * Math.min(1, dt * 1.2);
        galaxyTarget(T, TMP);
        var om = 0.35;
        G.vx += (om * om * (TMP[0] - G.x) - 2 * om * G.vx) * dt;
        G.vy += (om * om * (TMP[1] - G.y) - 2 * om * G.vy) * dt;
        G.x += G.vx * dt; G.y += G.vy * dt;
        // carried by scroll on a soft spring: drifts with the page, then floats back
        G.carryV += -dScroll * 0.16 + (-1.6 * G.carry - 2.4 * G.carryV) * dt;
        G.carry += G.carryV * dt;
        G.carry = 0.08 * H * Math.tanh(G.carry / (0.08 * H));
        var want = clamp(scrollVel / 1500, -1, 1);
        G.spin += (want - G.spin) * Math.min(1, dt * (Math.abs(want) > Math.abs(G.spin) ? 3 : 0.8));
        G.rot += dt * (CFG.PATTERN_W + CFG.SPIN_MAX * G.spin);
        G.incl = Math.max(0.3, 0.52 + 0.06 * Math.sin(T / 29) - 0.10 * gmy - 0.14 * Math.abs(G.spin));
        G.pa = -0.45 + 0.08 * Math.sin(T / 41) + 0.18 * gmx + clamp(0.0008 * G.vx, -0.25, 0.25);
        G.alpha = Math.min(1, G.alpha + dt / 1.5);
        // stars
        var twist = CFG.TWIST_A * Math.sin(TAU * T / CFG.TWIST_T);
        for (var i = 0; i < NS; i++) {
            var k = sKind[i], r = sR[i];
            if (k === 1) {
                r -= r * CFG.STREAM * dt;
                if (r < 0.07) { placeArmStar(i, true); r = sR[i]; }
                sR[i] = r;
                sFade[i] = Math.min(1, sFade[i] + dt / 2);
                sTh[i] = sOff[i] + CFG.PITCH * Math.log(r + 0.05) + twist * (r - 0.4);
            } else {
                sTh[i] += (CFG.ORBIT_K / (r + CFG.ORBIT_C) - CFG.PATTERN_W) * dt;
            }
        }
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
    function drawDeep(still) {
        for (var b = 0; b < D_STYLE.length; b++) {
            var col = (b / 6) | 0, lvl = b % 6, any = false;
            for (var i = 0; i < ND; i++) {
                if (dCol[i] !== col) continue;
                var a = still ? dBase[i] : Math.max(0, dBase[i] + dAmp[i] * Math.sin(T * dTw[i] + dPh[i]));
                if (clamp(Math.round(a / 0.55 * 6) - 1, 0, 5) !== lvl) continue;
                if (!any) { ctx.fillStyle = D_STYLE[b]; ctx.beginPath(); any = true; }
                ctx.moveTo(dX[i] + dRad[i], dY[i]); ctx.arc(dX[i], dY[i], dRad[i], 0, TAU);
            }
            if (any) ctx.fill();
        }
    }
    var shooters = [], nextShoot = 2.5 + RND() * 4;
    function stepShooters(dt) {
        if (T >= nextShoot) {
            nextShoot = T + CFG.SHOOT_MIN + RND() * (CFG.SHOOT_MAX - CFG.SHOOT_MIN);
            if (shooters.length < CFG.SHOOTERS) {
                var left = RND() < 0.5, dir = left ? 1 : -1, ang = 0.28 + RND() * 0.30, sp = (9 + RND() * 6) * 60;
                shooters.push({ x: left ? -40 : W + 40, y: RND() * H * 0.5, vx: dir * Math.cos(ang) * sp, vy: Math.sin(ang) * sp,
                                life: 0, max: (55 + RND() * 30) / 60, len: 90 + RND() * 70 });
            }
        }
        for (var i = shooters.length - 1; i >= 0; i--) {
            var o = shooters[i];
            o.x += o.vx * dt; o.y += o.vy * dt; o.life += dt;
            if (o.life >= o.max || o.x < -200 || o.x > W + 200 || o.y > H + 200) shooters.splice(i, 1);
        }
    }
    function drawShooters() {
        for (var i = 0; i < shooters.length; i++) {
            var o = shooters[i], k = Math.max(0, 1 - o.life / o.max), h = Math.hypot(o.vx, o.vy) || 1;
            var tx = o.x - o.vx / h * o.len, ty = o.y - o.vy / h * o.len;
            var g = ctx.createLinearGradient(o.x, o.y, tx, ty);
            g.addColorStop(0, 'rgba(226,232,240,' + (0.9 * k).toFixed(3) + ')');
            g.addColorStop(0.3, 'rgba(34,211,238,' + (0.5 * k).toFixed(3) + ')');
            g.addColorStop(1, 'rgba(34,211,238,0)');
            ctx.strokeStyle = g; ctx.lineWidth = 2; ctx.lineCap = 'round';
            ctx.beginPath(); ctx.moveTo(o.x, o.y); ctx.lineTo(tx, ty); ctx.stroke();
            ctx.globalAlpha = k; ctx.drawImage(GLOW, o.x - 4, o.y - 4, 8, 8); ctx.globalAlpha = 1;
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
    function drawField() {
        for (var b = 0; b < 3; b++) {
            ctx.fillStyle = F_STYLE[b]; ctx.beginPath();
            for (var i = 0; i < NF; i++) {
                if (fGroup[i] >= 0) continue;
                var tw = 0.6 + 0.4 * Math.sin(T * fTw[i] + fPh[i]), a = fAlpha[i] * tw;
                var hb = mouse.on && mouse.mouse ? 1 + 0.8 * Math.max(0, 1 - Math.hypot(fX[i] - mouse.x, fY[i] - mouse.y) / 120) : 1;
                var lvl = clamp(Math.round(a * hb / 0.38 * 2.5) - 1, 0, 2);
                if (lvl !== b) continue;
                var s = fSize[i];
                ctx.rect(fX[i] - s / 2, fY[i] - s / 2, s, s);
            }
            ctx.fill();
        }
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
    function drawGalaxy() {
        if (!G.placed) return;
        var gal = (small ? CFG.GALAXY_ALPHA_SMALL : CFG.GALAXY_ALPHA) * G.alpha;
        if (gal <= 0.01) return;
        var cp = Math.cos(G.pa), sp = Math.sin(G.pa), inc = G.incl, rot = G.rot, RD = R * (1 + 0.03 * Math.abs(G.spin));
        ctx.globalCompositeOperation = 'lighter';
        if (gasReady && S) {
            gasFade = Math.min(1, gasFade + 1 / (CFG.FPS * 1.5));
            ctx.save();
            ctx.translate(G.x, G.y + G.carry); ctx.rotate(G.pa); ctx.scale(1, inc); ctx.rotate(rot);
            ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'medium';   // bilinear: the gas is soft
            ctx.globalAlpha = CFG.GAS_ALPHA * gal * gasFade;
            ctx.drawImage(gasCan, -RD, -RD, 2 * RD, 2 * RD);
            var br = 1 + 0.12 * Math.sin(TAU * T / CFG.BREATH_T);            // core bloom, breathing
            ctx.globalAlpha = 0.20 * gal * gasFade * br;
            ctx.drawImage(BLOOM, -RD * 0.42, -RD * 0.42, RD * 0.84, RD * 0.84);
            ctx.restore();
        }
        // project stars once, bucket by colour x alpha
        var glows = 0, i;
        for (i = 0; i < nDraw; i++) {
            var th = sTh[i] + rot, rr = sR[i] * RD, u = rr * Math.cos(th), v = rr * Math.sin(th) * inc;
            sX[i] = G.x + u * cp - v * sp; sY[i] = G.y + G.carry + u * sp + v * cp;
            var fadeEdge = sKind[i] === 1 ? smooth(0.06, 0.12, sR[i]) * sFade[i] : sFade[i];
            var a = sAlpha[i] * (0.8 + 0.2 * Math.sin(T * sTw[i] + sPh[i])) * fadeEdge;
            if (mouse.on && mouse.mouse) {
                var dm = Math.hypot(sX[i] - mouse.x, sY[i] - mouse.y);
                if (dm < 110) a *= 1 + 0.6 * (1 - dm / 110);
            }
            var lvl = clamp(Math.round(a * ALEVELS) - 1, -1, ALEVELS - 1);
            sBucket[i] = lvl < 0 ? 255 : sCol[i] * ALEVELS + lvl;
        }
        // one path per colour bucket: sub-pixel stars as rects (a dot either way), the larger
        // ones, which read as squares once the 1x canvas is upscaled, as anti-aliased discs
        ctx.globalAlpha = gal;
        for (var bk = 0; bk < BUCKET_STYLE.length; bk++) {
            var any = false;
            for (i = 0; i < nDraw; i++) {
                if (sBucket[i] !== bk) continue;
                if (!any) { ctx.fillStyle = BUCKET_STYLE[bk]; ctx.beginPath(); any = true; }
                var z = sSize[i];
                if (z <= 1.3) ctx.rect(sX[i] - z / 2, sY[i] - z / 2, z, z);
                else { var rr = z > 2 ? 0.95 : 0.8; ctx.moveTo(sX[i] + rr, sY[i]); ctx.arc(sX[i], sY[i], rr, 0, TAU); }
            }
            if (any) ctx.fill();
        }
        for (i = 0; i < nDraw && glows < CFG.GLOW_MAX; i++) {
            if (sSize[i] <= 2 || sBucket[i] === 255) continue;
            var lv = ((sBucket[i] % ALEVELS) + 1) / ALEVELS;
            ctx.globalAlpha = 0.6 * gal * lv;
            ctx.drawImage(GLOW, sX[i] - 5, sY[i] - 5, 10, 10);
            if (glows < 8) { ctx.globalAlpha = 0.35 * gal * lv; ctx.drawImage(GLINT, sX[i] - 7, sY[i] - 7, 14, 14); }
            glows++;
        }
        ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
    }
    function render() {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
        drawDeep(reduced);
        if (!reduced) drawShooters();
        drawField();
        drawGalaxy();
        drawGroups();
    }

    // ---- scheduler ---------------------------------------------------------------
    var mq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
    var reduced = !!(mq && mq.matches), raf = 0, last = 0, acc = 0, FRAME = 1000 / CFG.FPS;
    var gasClock = 0, gasHz = CFG.GAS_HZ, govLevel = 0, govEma = 0, govHigh = 0, govLow = 0, ready = false;
    function governor(ms, dt) {
        govEma = govEma ? govEma * 0.9 + ms * 0.1 : ms;
        if (govEma > 3) { govHigh += dt; govLow = 0; } else if (govEma < 1.2) { govLow += dt; govHigh = 0; } else { govHigh = govLow = 0; }
        if (govHigh > 2 && govLevel < 4) { setGov(govLevel + 1); govHigh = 0; }
        else if (govLow > 10 && govLevel > 0) { setGov(govLevel - 1); govLow = 0; }
    }
    function setGov(l) {
        govLevel = l;
        var cap = Math.min(CFG.DPR_MAX, l >= 2 ? 1 : l >= 1 ? 1.5 : CFG.DPR_MAX);
        if (cap !== dprCap) { dprCap = cap; applySize(W, H); }
        gasHz = l >= 3 ? 10 : CFG.GAS_HZ;
        nDraw = l >= 4 ? Math.round(NS * 0.7) : NS;
    }
    function frame(now) {
        raf = requestAnimationFrame(frame);
        if (!last) { last = now; return; }
        acc += Math.min(now - last, 250); last = now;
        var step = now - lastScrollAt < 1200 || Math.abs(scrollY - smoothY) > 0.5 ? 1000 / 60 : FRAME;
        if (acc < step - 1) return;
        var n = Math.max(1, Math.floor((acc + 1) / step)), dt = Math.min(n * step, 100) / 1000;
        acc = Math.max(0, acc - n * step);
        var t0 = performance.now();
        // critically damped follow of the real scroll: smooth parallax, no 1-step jumps
        var prevY = smoothY, k = 1 - Math.exp(-dt * 9);
        smoothY += (scrollY - smoothY) * k;
        if (Math.abs(scrollY - smoothY) < 0.05) smoothY = scrollY;
        var dScroll = smoothY - prevY; lastScrollY = scrollY;
        scrollVel += ((dt > 0 ? dScroll / dt : 0) - scrollVel) * Math.min(1, dt * 6);
        T += dt;
        measureNav();
        if (gridDirty || Math.abs(scrollY - gridScroll) >= 12) rebuildGrid();
        if (textReady && !G.placed) placeGalaxy();
        if (G.placed) stepGalaxy(dt, dScroll);
        stepDeep(dt, dScroll);
        stepShooters(dt);
        stepField(dt, dScroll);
        if (G.placed) stepGroups(dt);
        gasClock += dt;
        if (gasClock >= 1 / (now - lastScrollAt < 300 ? 2 : gasHz)) { gasClock = 0; updateGas(T); }
        render();
        governor(performance.now() - t0, dt);
    }
    function start() { if (!raf && !reduced && !document.hidden) { last = 0; acc = 0; raf = requestAnimationFrame(frame); } }
    function stop() { if (raf) { cancelAnimationFrame(raf); raf = 0; } }
    function drawStill() {
        if (!reduced) return;
        if (!(gasReady && textReady)) return;          // never a half-made still frame
        measureNav();
        rebuildGrid();
        if (!G.placed) placeGalaxy();
        lastScrollY = scrollY; smoothY = scrollY; scrollVel = 0;
        G.alpha = 1;
        stepGalaxy(0, 0); stepField(0, 0);
        for (var i = 0; i < NF; i++) { fX[i] = fHx[i]; fY[i] = fHy[i]; }
        if (!groupsStillGood()) instantGroups();
        gasFade = 1; updateGas(T);
        render();
    }
    function onScrollEnd() { if (reduced) drawStill(); }
    function setReduced(v) {
        reduced = v;
        if (reduced) { stop(); drawStill(); } else { start(); }
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
            var m = measure(), dprNow = Math.min(dprCap, window.devicePixelRatio || 1);
            if (m.w === W && m.h === H && dprNow === DPR) return;
            var heightOnly = m.w === W && Math.abs(m.h - H) / H < 0.2 && dprNow === DPR;
            var ow = W, oh = H, wasSmall = small;
            applySize(m.w, m.h);
            gridDirty = true; measureDoc();
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
        if (gasReady && textReady) drawStill(); else setTimeout(waitGas, 120);
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
            if (calm.matches || !wide()) { sc.c.style.transform = ''; sc.c.style.opacity = ''; continue; }
            if (sc.bot < -50 || sc.top > s.vh + 50) continue;
            var e = clamp((s.vh - sc.top) / (s.vh * 0.32), 0, 1);           // entering
            var l = clamp((s.vh * 0.32 - sc.bot) / (s.vh * 0.32), 0, 1);    // leaving
            var ee = 1 - Math.pow(1 - e, 3);
            var op = (0.35 + 0.65 * ee) * (1 - 0.5 * l), sc2 = (0.965 + 0.035 * ee) * (1 - 0.02 * l), ty = 40 * (1 - ee);
            sc.c.style.opacity = op > 0.995 ? '' : op.toFixed(3);
            sc.c.style.transform = (sc2 > 0.9995 && ty < 0.2) ? '' : 'translateY(' + ty.toFixed(1) + 'px) scale(' + sc2.toFixed(4) + ')';
        }
    });

    // ---- pinned "Closed Loop" story ---------------------------------------------------------
    var loop = document.getElementById('loop');
    var track = loop && loop.querySelector('.ce-loop') ? loop.querySelector('.ce-loop').parentElement : null;
    var steps = track ? track.querySelectorAll('.ce-loop-step') : [], lp = { top: 0, h: 1 }, lastStep = -2;
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
        loop.style.setProperty('--lp', p.toFixed(4));
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
        diff.style.setProperty('--wa', clamp(p / 0.3, 0, 1).toFixed(3));
        diff.style.setProperty('--wq', clamp((p - 0.28) / 0.42, 0, 1).toFixed(4));
        diff.style.setProperty('--wb', clamp((p - 0.62) / 0.3, 0, 1).toFixed(3));
    });

    // ---- inertial wheel scrolling (touch, keys, scrollbar stay native) ------------------------
    var target = window.scrollY, cur = window.scrollY, set = window.scrollY, running = false, last = 0;
    function maxY() { return Math.max(0, root.scrollHeight - window.innerHeight); }
    function nestedCanScroll(el, dy) {
        for (; el && el !== body && el !== root; el = el.parentElement) {
            if (el.scrollHeight <= el.clientHeight + 1) continue;
            var oy = getComputedStyle(el).overflowY;
            if (oy !== 'auto' && oy !== 'scroll') continue;
            if (dy > 0 ? el.scrollTop + el.clientHeight < el.scrollHeight - 1 : el.scrollTop > 0) return true;
        }
        return false;
    }
    function tick(now) {
        var dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now;
        if (Math.abs(window.scrollY - set) > 2) { running = false; root.style.scrollBehavior = ''; return; }   // keys / scrollbar took over
        cur += (target - cur) * (1 - Math.exp(-dt * 6.5));
        if (Math.abs(target - cur) < 0.4) cur = target;
        window.scrollTo(0, cur);
        set = window.scrollY;
        if (cur !== target) requestAnimationFrame(tick);
        else { running = false; root.style.scrollBehavior = ''; }
    }
    function glide(to) {
        target = clamp(to, 0, maxY());
        if (!running) { cur = set = window.scrollY; running = true; last = performance.now(); root.style.scrollBehavior = 'auto'; requestAnimationFrame(tick); }
    }
    window.addEventListener('wheel', function (e) {
        if (calm.matches || e.ctrlKey || e.defaultPrevented) return;
        if (body.style.overflow === 'hidden' || root.style.overflow === 'hidden' || (e.target.closest && e.target.closest('[aria-modal="true"]'))) return;
        var dy = e.deltaY;
        if (e.deltaMode === 1) dy *= 40; else if (e.deltaMode === 2) dy *= window.innerHeight;
        if (Math.abs(e.deltaX) > Math.abs(dy) || !dy) return;
        if (nestedCanScroll(e.target, dy)) return;
        e.preventDefault();
        glide((running ? target : window.scrollY) + dy);
    }, { passive: false });
    // same-page anchors glide too, landing below the fixed nav
    document.addEventListener('click', function (e) {
        var a = e.target.closest && e.target.closest('a[href*="#"]');
        if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
        var url = new URL(a.href, location.href);
        if (url.pathname !== location.pathname || !url.hash || url.hash === '#') return;
        var el = document.getElementById(decodeURIComponent(url.hash.slice(1)));
        if (!el) return;
        e.preventDefault();
        var off = nav ? nav.getBoundingClientRect().bottom + 16 : 80;
        var to = el.getBoundingClientRect().top + window.scrollY - off;
        if (calm.matches) window.scrollTo(0, to); else glide(to);
        if (history.pushState) history.pushState(null, '', url.hash);
    });

    // ---- Sentinel: hero wordmark zooms out into the headline ---------------------------------
    function easeIO(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
    function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
    var zHero = body.classList.contains('sentinel') ? document.querySelector('.sentinel-hero') : null;
    var zStage = zHero && zHero.querySelector(':scope > .container'), zMark = zHero && zHero.querySelector('.s-zoom-mark'),
        zRest = zHero && zHero.querySelector('.s-zoom-rest'), zHint = zHero && zHero.querySelector('.s-hint-wrap');
    var zs = { on: null, p: 0, top: 0, h: 1, w0: 1, h0: 1, cy: 0 };
    function zClear() {
        [zMark, zRest, zHint].forEach(function (el) { if (el) { el.style.transform = ''; el.style.opacity = ''; el.style.pointerEvents = ''; } });
    }
    on(function (s) {
        if (!zMark || !zStage) return;
        var want = wide() && !calm.matches;
        if (want !== zs.on) { zs.on = want; zHero.classList.toggle('pin', want); if (!want) zClear(); }
        if (!want) return;
        var r = zHero.getBoundingClientRect(); zs.top = r.top; zs.h = r.height;
        zs.w0 = zMark.offsetWidth || 1; zs.h0 = zMark.offsetHeight || 1;
        var y = 0, el = zMark;                                   // offsets ignore transforms
        while (el && el !== zStage) { y += el.offsetTop; el = el.offsetParent; }
        zs.cy = el === zStage ? y + zs.h0 / 2 : s.vh / 2;
    }, function (s) {
        if (!zs.on) return;
        var p = clamp(-zs.top / Math.max(1, zs.h - s.vh), 0, 1);
        var S0 = Math.max(1, Math.min(0.9 * window.innerWidth / zs.w0, 0.78 * s.vh / zs.h0, 3.4));
        var e = easeIO(clamp(p / 0.55, 0, 1)), sc = S0 + (1 - S0) * e, dy = (s.vh / 2 - zs.cy) * (1 - e);
        zMark.style.transform = e >= 1 ? '' : 'translate3d(0,' + dy.toFixed(1) + 'px,0) scale(' + sc.toFixed(4) + ')';
        var o = clamp((p - 0.42) / 0.33, 0, 1);
        if (zRest) {
            zRest.style.opacity = o >= 1 ? '' : o.toFixed(3);
            zRest.style.transform = o >= 1 ? '' : 'translate3d(0,' + (30 * (1 - o)).toFixed(1) + 'px,0)';
            zRest.style.pointerEvents = o < 0.6 ? 'none' : '';
        }
        if (zHint) zHint.style.opacity = (1 - clamp(p / 0.25, 0, 1)).toFixed(3);
    });

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
