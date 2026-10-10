/* bytemap.js - the live byte map shared by the registry anatomy pages.
 *
 * One record, drawn one byte at a time. Click a cell or a row of the reference
 * table and the panel beside it explains that field: what the bytes are, what
 * they decode to, and which parser reads them.
 *
 * The component is a port of the one inside prefetch_anatomy.html, with three
 * deliberate differences:
 *
 *   - It is a module, because four pages need it and four copies of a thing
 *     is four places for it to drift.
 *
 *   - The bytes are real. Prefetch fills most of its map with gen(), which
 *     synthesises filler from Math.sin. Every array these pages pass in was
 *     measured off a real hive, which is the whole claim the pages make.
 *
 *   - Cells are reachable from the keyboard. The original is onclick only,
 *     which leaves the main interactive element of the page unusable without
 *     a mouse.
 *
 * The data contract, unchanged from prefetch so the two stay legible together:
 *
 *   variants = { key: { label, hex: ["4D", ...], fields: [ {
 *      section, name, offset, size, type, val?, forensic, struct?
 *   } ] } }
 *
 * A byte covered by no field renders as reserved and says so when clicked -
 * padding and undocumented space are findings too, not gaps in the page.
 */
(function (global) {
  'use strict';

  /* Seven solid steps per family, rotated across consecutive fields so two
   * neighbouring fields never share a colour. Solid hex rather than alpha:
   * the anatomy pages sit on several different backgrounds and a translucent
   * fill reads as a different colour on each one.
   */
  var PALETTES = {
    header: [
      { bg: '#0e7490', fg: '#ffffff' }, { bg: '#0891b2', fg: '#ffffff' },
      { bg: '#06b6d4', fg: '#062024' }, { bg: '#22d3ee', fg: '#062024' },
      { bg: '#67e8f9', fg: '#062024' }, { bg: '#155e75', fg: '#ffffff' },
      { bg: '#164e63', fg: '#ffffff' }
    ],
    time: [
      { bg: '#9f1239', fg: '#ffffff' }, { bg: '#be123c', fg: '#ffffff' },
      { bg: '#e11d48', fg: '#ffffff' }, { bg: '#f43f5e', fg: '#2b0611' },
      { bg: '#fb7185', fg: '#2b0611' }, { bg: '#881337', fg: '#ffffff' },
      { bg: '#4c0519', fg: '#ffffff' }
    ],
    count: [
      { bg: '#065f46', fg: '#ffffff' }, { bg: '#047857', fg: '#ffffff' },
      { bg: '#059669', fg: '#ffffff' }, { bg: '#10b981', fg: '#03251a' },
      { bg: '#34d399', fg: '#03251a' }, { bg: '#6ee7b7', fg: '#03251a' },
      { bg: '#064e3b', fg: '#ffffff' }
    ],
    name: [
      { bg: '#6d28d9', fg: '#ffffff' }, { bg: '#7c3aed', fg: '#ffffff' },
      { bg: '#8b5cf6', fg: '#ffffff' }, { bg: '#a78bfa', fg: '#1e1035' },
      { bg: '#c4b5fd', fg: '#1e1035' }, { bg: '#5b21b6', fg: '#ffffff' },
      { bg: '#4c1d95', fg: '#ffffff' }
    ],
    size: [
      { bg: '#b45309', fg: '#ffffff' }, { bg: '#d97706', fg: '#2b1503' },
      { bg: '#f59e0b', fg: '#2b1503' }, { bg: '#fbbf24', fg: '#2b1503' },
      { bg: '#fcd34d', fg: '#2b1503' }, { bg: '#92400e', fg: '#ffffff' },
      { bg: '#78350f', fg: '#ffffff' }
    ],
    flags: [
      { bg: '#1d4ed8', fg: '#ffffff' }, { bg: '#2563eb', fg: '#ffffff' },
      { bg: '#3b82f6', fg: '#ffffff' }, { bg: '#60a5fa', fg: '#08183a' },
      { bg: '#93c5fd', fg: '#08183a' }, { bg: '#1e40af', fg: '#ffffff' },
      { bg: '#1e3a8a', fg: '#ffffff' }
    ]
  };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined) { n.textContent = text; }
    return n;
  }

  function hex(n) { return '0x' + n.toString(16).toUpperCase(); }

  /* Bytes 32-126 render as characters. That is the point of an ASCII column
   * and also the reason every array handed to this component is redacted at
   * the source: whatever is in the bytes is on the screen.
   */
  function ascii(bytes) {
    return bytes.map(function (b) {
      var c = parseInt(b, 16);
      return (c >= 32 && c <= 126) ? String.fromCharCode(c) : '.';
    }).join('');
  }

  function fieldAt(fields, i) {
    for (var k = 0; k < fields.length; k++) {
      var f = fields[k];
      if (i >= f.offset && i < f.offset + f.size) { return f; }
    }
    return null;
  }

  function ByteMap(cfg) {
    this.cfg = cfg;
    this.variants = cfg.variants;
    this.keys = Object.keys(cfg.variants);
    this.current = cfg.initial || this.keys[0];
    this.cells = [];
    this.buildTabs();
    this.render();
  }

  ByteMap.prototype.buildTabs = function () {
    var self = this;
    var host = this.cfg.tabsEl;
    if (!host || this.keys.length < 2) { return; }
    host.innerHTML = '';
    this.keys.forEach(function (key) {
      var tab = el('div', 'v-tab', self.variants[key].label || key);
      tab.setAttribute('role', 'tab');
      tab.setAttribute('tabindex', '0');
      if (key === self.current) { tab.classList.add('active'); }
      function pick() { self.setVariant(key); }
      tab.addEventListener('click', pick);
      tab.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      });
      host.appendChild(tab);
    });
  };

  ByteMap.prototype.setVariant = function (key) {
    if (!this.variants[key]) { return; }
    this.current = key;
    var host = this.cfg.tabsEl;
    if (host) {
      var tabs = host.querySelectorAll('.v-tab');
      for (var i = 0; i < tabs.length; i++) {
        tabs[i].classList.toggle('active', this.keys[i] === key);
      }
    }
    this.render();
    /* Let the page know. Optional and additive: three of the four pages that
     * share this file pass nothing and behave exactly as before. The amcache
     * page uses it so its two diagrams light the record the tabs just chose -
     * before this the map could be driven but could not report. */
    if (this.cfg.onVariant) { this.cfg.onVariant(key); }
  };

  ByteMap.prototype.render = function () {
    var self = this;
    var v = this.variants[this.current];
    var map = this.cfg.mapEl;
    var table = this.cfg.tableEl;
    map.innerHTML = '';
    if (table) { table.innerHTML = ''; }
    this.cells = [];

    var section = null, fieldIdx = 0, lastField = null;

    v.hex.forEach(function (b, i) {
      var f = fieldAt(v.fields, i);
      if (f && f.section !== section) {
        map.appendChild(el('div', 'divider-row', f.section));
        section = f.section;
        fieldIdx = 0;
      }
      if (f && f !== lastField) { lastField = f; fieldIdx++; }

      var cell = el('div', 'byte-cell', b);
      if (f && f.type !== 'reserved') {
        var pal = PALETTES[f.type] || PALETTES.header;
        var colour = pal[fieldIdx % pal.length];
        /* backgroundColor, never background: the shorthand resets
         * background-image and the cards behind these maps use one. */
        cell.style.backgroundColor = colour.bg;
        cell.style.color = colour.fg;
      } else {
        cell.classList.add('reserved');
      }
      cell.setAttribute('tabindex', '0');
      cell.setAttribute('role', 'button');
      cell.setAttribute('aria-label',
        'byte at offset ' + hex(i) + (f ? ', ' + f.name : ', not documented'));
      cell.addEventListener('click', function () { self.select(f, i); });
      cell.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          self.select(f, i);
        }
      });
      self.cells.push(cell);
      map.appendChild(cell);
    });

    if (table) {
      v.fields.forEach(function (f) {
        var row = el('tr');
        row.appendChild(el('td', null, hex(f.offset)));
        row.appendChild(el('td', null, f.size + 'B'));
        var name = el('td', null, f.name);
        name.style.fontWeight = '700';
        row.appendChild(name);
        var why = el('td');
        why.innerHTML = f.forensic || '';
        row.appendChild(why);
        row.setAttribute('tabindex', '0');
        row.addEventListener('click', function () { self.select(f, f.offset); });
        row.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') { e.preventDefault(); self.select(f, f.offset); }
        });
        table.appendChild(row);
      });
    }

    if (v.fields.length) { this.select(v.fields[0], v.fields[0].offset); }
  };

  /* Open a variant and highlight the field containing `offset`.
   *
   * Additive: this file is shared by the amcache, registry, shellbags and
   * shimcache pages, and nothing existing changes behaviour. It exists so a
   * diagram outside the map can drive it - the amcache page hovers an arrow
   * and lands on the exact four bytes that arrow was read from.
   *
   * Returns the field it selected, or null when there is none there. A byte
   * belonging to no field is not an error: select() renders it as reserved
   * and explains itself, which is the same thing clicking that byte does.
   */
  ByteMap.prototype.focusField = function (key, offset) {
    if (!this.variants[key]) { return null; }
    if (key !== this.current) { this.setVariant(key); }
    var f = fieldAt(this.variants[key].fields, offset);
    this.select(f, offset);
    return f;
  };

  ByteMap.prototype.select = function (f, idx) {
    var v = this.variants[this.current];
    var panel = this.cfg.panelEl;

    if (!f) {
      this.cells.forEach(function (c) { c.classList.remove('active'); });
      if (this.cells[idx]) { this.cells[idx].classList.add('active'); }
      panel.innerHTML =
        '<div class="field-name">Undocumented byte</div>' +
        '<div class="meta-box"><span class="meta-lbl">Offset</span>' +
        '<div class="field-val">' + hex(idx) + '</div></div>' +
        '<div class="forensic-text">This byte sits between the documented ' +
        'structures. It is almost always alignment padding or space reserved ' +
        'for a field Microsoft never shipped. It is shown rather than hidden ' +
        'because a parser has to account for every byte it walks past, and ' +
        'because a non-zero value here on a record that should be padded is ' +
        'worth a second look.</div>';
      return;
    }

    var start = f.offset, end = f.offset + f.size - 1;
    this.cells.forEach(function (c, i) {
      c.classList.toggle('active', i >= start && i <= end);
    });

    var bytes = v.hex.slice(start, end + 1);
    var out =
      '<div class="field-name">' + f.name + '</div>' +
      '<div class="meta-box">' +
      '<span class="meta-lbl">Offset</span>' +
      '<div class="field-val">' + hex(start) +
      (f.size > 1 ? ' to ' + hex(end) : '') + '  (' + f.size + ' bytes)</div>' +
      '<span class="meta-lbl">Raw bytes</span>' +
      '<div class="field-val mono">' + bytes.join(' ') + '</div>' +
      '<span class="meta-lbl">ASCII</span>' +
      '<div class="field-val mono">' + ascii(bytes) + '</div>';

    if (f.val !== undefined) {
      out += '<span class="meta-lbl">Decodes to</span>' +
             '<div class="field-val">' + f.val + '</div>';
    }
    out += '</div>';

    out += '<div class="forensic-text">' + (f.forensic || '') + '</div>';

    if (f.struct && f.struct.length) {
      out += '<table class="ref-table" style="margin-top:14px"><thead><tr>' +
             '<th>Offset</th><th>Size</th><th>Field</th></tr></thead><tbody>';
      f.struct.forEach(function (s) {
        out += '<tr><td>' + s.off + '</td><td>' + s.size + '</td><td>' +
               s.name + '</td></tr>';
      });
      out += '</tbody></table>';
    }

    panel.innerHTML = out;
  };

  global.ByteMap = {
    mount: function (cfg) {
      if (!cfg || !cfg.mapEl || !cfg.panelEl || !cfg.variants) { return null; }
      return new ByteMap(cfg);
    },
    palettes: PALETTES,
    /* Exported so the tests can exercise them without a DOM: jsdom reports
     * every rect as 0x0, so anything geometric has to be checked as a pure
     * function or not at all. */
    _fieldAt: fieldAt,
    _ascii: ascii
  };
})(window);
