/* Anatomy: the animation engine behind the Eye-Describe explainers.
 *
 * Written because the registry guide had grown four separate hand-rolled
 * animation lifecycles, each with its own timers array, its own clear() and its
 * own button wiring, and because none of them honoured a reader's reduced-motion
 * preference or announced anything to a screen reader.
 *
 * The one design decision everything follows from: STEPS ARE DATA, AND SEEKING
 * REPLAYS FROM THE START. A step declares what it does to the page, never how to
 * undo it, and the engine reaches step n by resetting and applying 0..n. That is
 * what makes step-back, scrubbing and deterministic testing work for every
 * animation at once instead of each one having to write an inverse of itself.
 *
 * No dependencies, and no fetch: these pages are opened straight off file://
 * during development and must keep working that way.
 */
(function (global) {
  'use strict';

  var registry = {};

  // Motion preference goes through this one function so tests can force either
  // branch. Reading matchMedia directly at a dozen call sites is how a setting
  // ends up half-honoured, which is exactly the state this replaces.
  var motionOverride = null;
  function prefersReducedMotion() {
    if (motionOverride !== null) return motionOverride;
    return !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function el(sel) {
    return typeof sel === 'string' ? document.querySelector(sel) : sel;
  }

  function button(label, aria, icon) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn-proto';
    b.setAttribute('aria-label', aria);
    b.innerHTML = (icon ? '<i class="fas fa-' + icon + '"></i> ' : '') + label;
    return b;
  }

  /* timeline({ id, mount, status, speed, reset, steps, tracks, subtree })
   *
   *   id      registration key, also the key in window.__anim
   *   mount   where the transport bar is rendered
   *   status  element the engine writes each step's status text into
   *   speed   ms per step during playback; ignored under reduced motion
   *   reset   fn(ctx) returning the animation to frame zero
   *   steps   [{ label, status, apply(ctx) }]  or omitted when using tracks
   *   tracks  { name: [steps] } for animations with more than one path,
   *           e.g. a clean write and an interrupted one over the same reset
   *   subtree selector for the DOM the test hook snapshots
   */
  function timeline(spec) {
    var mount = el(spec.mount);
    var status = el(spec.status);
    if (!mount) return null;

    var tracks = spec.tracks || { main: spec.steps || [] };
    var trackNames = Object.keys(tracks);
    var track = spec.startTrack || trackNames[0];
    var at = -1;                 // -1 is the reset frame, before step 0
    var playing = false;
    var timer = null;
    var autoplayed = false;
    var touched = false;         // the reader has taken control

    var ctx = spec.context || {};

    function steps() { return tracks[track] || []; }

    // ---- the live region -------------------------------------------------
    if (status && !status.getAttribute('aria-live')) {
      status.setAttribute('aria-live', 'polite');
      status.setAttribute('aria-atomic', 'true');
    }

    function say(html) {
      if (!status) return;
      if (html === undefined || html === null) return;
      status.innerHTML = html;
    }

    // ---- transport -------------------------------------------------------
    var bar = document.createElement('div');
    bar.className = 'proto-btns anim-bar';
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', (spec.name || spec.id) + ' playback controls');

    var bPlay = button('Play', 'Play ' + (spec.name || spec.id), 'play');
    var bPrev = button('', 'Previous step', 'backward-step');
    var bNext = button('', 'Next step', 'forward-step');
    var bReset = button('Reset', 'Reset to the start', 'rotate-left');
    var readout = document.createElement('span');
    readout.className = 'anim-count';
    readout.setAttribute('aria-live', 'polite');

    [bPlay, bPrev, bNext, bReset].forEach(function (b) { bar.appendChild(b); });
    bar.appendChild(readout);
    mount.appendChild(bar);

    // Extra buttons the animation supplies, e.g. one per track.
    (spec.buttons || []).forEach(function (def) {
      var b = button(def.label, def.aria || def.label, def.icon);
      if (def.className) b.className += ' ' + def.className;
      b.onclick = function () {
        touched = true;
        track = def.track;
        reset();
        play();
      };
      bar.insertBefore(b, bPlay);
    });

    // ---- the state machine ----------------------------------------------
    function applyReset() {
      at = -1;
      if (spec.reset) spec.reset(ctx);
      say(spec.idleStatus);
    }

    // Seek by replaying. A step never has to know how to undo itself.
    function goTo(n) {
      var target = Math.max(-1, Math.min(n, steps().length - 1));
      applyReset();
      for (var i = 0; i <= target; i++) {
        var st = steps()[i];
        if (st.apply) st.apply(ctx, i);
      }
      at = target;
      if (target >= 0) say(steps()[target].status);
      paintControls();
      return at;
    }

    function next() {
      if (at >= steps().length - 1) { stop(); return false; }
      // Forward is the one case that does not need a replay.
      at += 1;
      var st = steps()[at];
      if (st.apply) st.apply(ctx, at);
      say(st.status);
      paintControls();
      return true;
    }

    function prev() {
      if (at <= -1) return false;
      goTo(at - 1);
      return true;
    }

    function tick() {
      if (!next()) return;
      if (at >= steps().length - 1) { stop(); return; }
      timer = global.setTimeout(tick, spec.speed || 500);
    }

    function play() {
      stop();
      if (at >= steps().length - 1) applyReset();
      if (prefersReducedMotion()) {
        // Not "play faster": no timed motion at all. The reader still gets the
        // whole sequence, they just get it as a destination rather than a trip,
        // and the transport is right there to step through it.
        goTo(steps().length - 1);
        return;
      }
      playing = true;
      paintControls();
      tick();
    }

    function stop() {
      playing = false;
      if (timer) { global.clearTimeout(timer); timer = null; }
      paintControls();
    }

    function reset() {
      stop();
      applyReset();
      paintControls();
    }

    function paintControls() {
      bPlay.innerHTML = '<i class="fas fa-' + (playing ? 'pause' : 'play') + '"></i> ' +
        (playing ? 'Pause' : 'Play');
      bPlay.setAttribute('aria-label', (playing ? 'Pause ' : 'Play ') + (spec.name || spec.id));
      bPrev.disabled = at <= -1;
      bNext.disabled = at >= steps().length - 1;
      [bPrev, bNext].forEach(function (b) { b.style.opacity = b.disabled ? '0.4' : '1'; });
      readout.textContent = at < 0
        ? 'start  ' + String.fromCharCode(183) + '  ' + steps().length + ' steps'
        : 'step ' + (at + 1) + ' of ' + steps().length;
    }

    bPlay.onclick = function () { touched = true; playing ? stop() : play(); };
    bNext.onclick = function () { touched = true; stop(); next(); };
    bPrev.onclick = function () { touched = true; stop(); prev(); };
    bReset.onclick = function () { touched = true; reset(); };

    // ---- autoplay on first view -----------------------------------------
    // Once, when it is actually on screen, and never when the reader has asked
    // for less motion or has already taken control of this animation.
    if (global.IntersectionObserver && !prefersReducedMotion()) {
      var io = new global.IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting || autoplayed || touched) return;
          autoplayed = true;
          io.disconnect();
          play();
        });
      }, { threshold: 0.35 });
      io.observe(mount.closest('.anat') || mount);
    }

    applyReset();
    paintControls();

    var api = {
      id: spec.id,
      kind: 'timeline',
      get steps() { return steps().length; },
      get at() { return at; },
      get playing() { return playing; },
      get tracks() { return trackNames; },
      setTrack: function (name) { if (tracks[name]) { track = name; reset(); } },
      goTo: goTo,
      next: next,
      prev: prev,
      play: play,
      pause: stop,
      reset: reset,
      snapshot: function () {
        var root = el(spec.subtree) || mount.closest('.anat') || mount;
        // Class names plus text: enough to notice a step that changed nothing,
        // without being so precise that a repaint of identical state trips it.
        return Array.prototype.map.call(root.querySelectorAll('*'), function (e) {
          return (e.className && e.className.baseVal === undefined ? e.className : '') +
                 '|' + (e.textContent || '').slice(0, 60);
        }).join('~');
      },
    };
    registry[spec.id] = api;
    return api;
  }

  /* register(id, obj) - for the explorers that are not timelines.
   * The byte maps and the nested walk are driven by clicking their own content,
   * not by a transport, and pretending otherwise would make them worse. They are
   * registered anyway so a driver can enumerate everything on a page.
   */
  function register(id, obj) {
    obj.id = id;
    obj.kind = obj.kind || 'explorer';
    registry[id] = obj;
    return obj;
  }

  global.Anatomy = {
    timeline: timeline,
    register: register,
    all: registry,
    reducedMotion: prefersReducedMotion,
    // Tests force the branch instead of hoping the harness emulates the media
    // query. null hands control back to the real preference.
    forceReducedMotion: function (v) { motionOverride = v; },
  };
  global.__anim = registry;
})(window);
