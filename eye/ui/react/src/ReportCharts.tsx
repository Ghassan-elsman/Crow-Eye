/**
 * Report visualisations for the Eye: chart, timeline and heatmap blocks.
 *
 * One look for every chart the Eye adds to a report: the block's own title and
 * a readout (total, peak, largest share) above the chart, Crow-Eye's chart
 * palette (no red - red is kept for urgent findings), the site's dark ink for
 * axes and legends, values written on the bars and slices, and the numbers
 * behind the chart one click away. Every chart kind the backend can produce
 * draws: horizontalBar, radar and scatter were registered nowhere and left an
 * empty frame, and a fixed aspect ratio inside a fixed-height box clipped the
 * bottom of every bar, line and pie chart.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Chart as ChartJS, registerables, type Plugin } from 'chart.js';
import { Chart } from 'react-chartjs-2';
import type { ChartBlock, TimelineBlock, HeatmapBlock } from './types';
import './ReportCharts.css';

ChartJS.register(...registerables);

/** Crow-Eye's chart palette (ui/app_theme.py CHART_PALETTE). */
export const CHART_PALETTE = [
  '#6366F1', '#22D3EE', '#A78BFA', '#2DD4BF', '#FBBF24', '#F472B6',
  '#38BDF8', '#A3E635', '#FB923C', '#94A3B8', '#818CF8', '#34D399',
];

const INK = {
  text: '#E2E8F0',
  muted: '#94A3B8',
  faint: '#64748B',
  grid: 'rgba(148, 163, 184, 0.12)',
  panel: '#0B1220',
  tooltip: '#0F172A',
  line: '#334155',
};

const FONT = "'Inter', 'Segoe UI', system-ui, sans-serif";

/** Forensic categories, coloured without red. */
export const CATEGORY_COLOURS: Record<string, string> = {
  security: '#F472B6',
  execution: '#2DD4BF',
  persistence: '#A78BFA',
  identity: '#22D3EE',
  hardware: '#FB923C',
  filesystem: '#38BDF8',
  intent: '#FBBF24',
  evidence: '#818CF8',
  network: '#A3E635',
};

const categoryColour = (category: string | undefined, index: number) =>
  CATEGORY_COLOURS[(category || '').toLowerCase()] || CHART_PALETTE[index % CHART_PALETTE.length];

const alpha = (hex: string, a: number) => {
  const h = hex.replace('#', '');
  if (h.length !== 6) return hex;
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
};

const fmt = (v: number) =>
  Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });

const num = (v: unknown): number | null => {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
  return null;
};

type Kind = 'bar' | 'line' | 'pie' | 'doughnut' | 'radar' | 'scatter';

const KIND_NAMES: Record<string, string> = {
  bar: 'Bar chart', hbar: 'Bar chart', line: 'Line chart', pie: 'Pie chart',
  doughnut: 'Doughnut chart', radar: 'Radar chart', scatter: 'Scatter plot',
};

/** Writes each bar's value at its end, and each slice's share inside it. */
const valueLabels: Plugin = {
  id: 'eyeValueLabels',
  afterDatasetsDraw(chart) {
    const type = (chart.config as any).type as string;
    const ctx = chart.ctx;
    ctx.save();
    ctx.font = `600 11px ${FONT}`;
    if (type === 'bar') {
      const horizontal = chart.options.indexAxis === 'y';
      const bars = chart.data.datasets.reduce((n, ds) => n + (ds.data?.length || 0), 0);
      if (bars > 40) { ctx.restore(); return; }
      chart.data.datasets.forEach((ds, di) => {
        const meta = chart.getDatasetMeta(di);
        if (meta.hidden) return;
        meta.data.forEach((el: any, i) => {
          const v = num((ds.data as unknown[])[i]);
          if (v === null || v === 0) return;
          ctx.fillStyle = INK.text;
          if (horizontal) {
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(fmt(v), el.x + 6, el.y);
          } else {
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText(fmt(v), el.x, el.y - 4);
          }
        });
      });
    } else if (type === 'pie' || type === 'doughnut') {
      const ds = chart.data.datasets[0];
      const meta = chart.getDatasetMeta(0);
      const values = ((ds?.data as unknown[]) || []).map((v) => num(v) || 0);
      const total = values.reduce((a, b) => a + b, 0);
      if (total > 0) {
        meta.data.forEach((arc: any, i) => {
          const share = values[i] / total;
          if (share < 0.05 || !arc || (chart as any).getDataVisibility?.(i) === false) return;
          const p = arc.tooltipPosition();
          ctx.fillStyle = '#0B1220';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(`${Math.round(share * 100)}%`, p.x, p.y);
        });
        if (type === 'doughnut') {
          const arc: any = meta.data[0];
          if (arc) {
            ctx.fillStyle = INK.text;
            ctx.font = `700 20px ${FONT}`;
            ctx.fillText(fmt(total), arc.x, arc.y - 6);
            ctx.fillStyle = INK.muted;
            ctx.font = `500 11px ${FONT}`;
            ctx.fillText('total', arc.x, arc.y + 14);
          }
        }
      }
    }
    ctx.restore();
  },
};

interface Prepared {
  kind: Kind;
  horizontal: boolean;
  labels: string[];
  datasets: any[];
  height: number;
  readout: { label: string; value: string }[];
  kindName: string;
}

function prepare(block: ChartBlock): Prepared {
  const config = (block.metadata && (block.metadata as any).chart_config) || null;
  const rawType = String(config?.type || block.chart_type || 'bar');
  const horizontal = rawType === 'horizontalBar' || config?.options?.indexAxis === 'y';
  const kind = (rawType === 'horizontalBar' ? 'bar' : rawType) as Kind;
  const labels: string[] = ((config?.data?.labels || block.labels || []) as unknown[]).map((l) => String(l));
  const source: any[] = config?.data?.datasets || block.datasets || [];
  // Colours the investigator chose (custom_colors) are kept; the default
  // palette gives way to Crow-Eye's.
  const custom: string[] | null = Array.isArray((block as any).custom_colors) && (block as any).custom_colors.length
    ? (block as any).custom_colors : null;
  const colourAt = (i: number) => (custom ? custom[i % custom.length] : CHART_PALETTE[i % CHART_PALETTE.length]);
  const circular = kind === 'pie' || kind === 'doughnut';

  const datasets = source.map((ds, i) => {
    const c = colourAt(i);
    const base = { label: ds.label ?? `Series ${i + 1}`, data: ds.data || [] };
    if (circular) {
      return {
        ...base,
        backgroundColor: (ds.data || []).map((_: unknown, j: number) => colourAt(j)),
        borderColor: INK.panel,
        borderWidth: 2,
        hoverOffset: 6,
      };
    }
    if (kind === 'line') {
      return {
        ...base, borderColor: c, backgroundColor: alpha(c, 0.14), fill: source.length === 1,
        tension: 0.3, borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: c,
      };
    }
    if (kind === 'radar') {
      return {
        ...base, borderColor: c, backgroundColor: alpha(c, 0.18), borderWidth: 2,
        pointRadius: 3, pointBackgroundColor: c,
      };
    }
    if (kind === 'scatter') {
      return { ...base, backgroundColor: alpha(c, 0.8), borderColor: c, pointRadius: 4 };
    }
    return {
      ...base, backgroundColor: alpha(c, 0.85), hoverBackgroundColor: c, borderColor: c,
      borderWidth: 0, borderRadius: 4, borderSkipped: false, maxBarThickness: 44,
    };
  });

  // The readout: what an analyst reads first.
  const readout: { label: string; value: string }[] = [];
  const all = datasets.flatMap((ds) => (ds.data as unknown[]).map(num).filter((v): v is number => v !== null));
  if (all.length && kind !== 'scatter') {
    readout.push({ label: 'Total', value: fmt(all.reduce((a, b) => a + b, 0)) });
  }
  if (datasets.length >= 1 && labels.length && kind !== 'scatter') {
    const sums = labels.map((_, li) =>
      datasets.reduce((s, ds) => s + (num((ds.data as unknown[])[li]) || 0), 0));
    const peak = sums.reduce((best, v, li) => (v > sums[best] ? li : best), 0);
    const total = sums.reduce((a, b) => a + b, 0);
    if (circular && total > 0) {
      readout.push({ label: 'Largest', value: `${labels[peak]} · ${Math.round((sums[peak] / total) * 100)}%` });
    } else if (sums[peak] > 0) {
      readout.push({ label: 'Peak', value: `${labels[peak]} · ${fmt(sums[peak])}` });
    }
  }
  if (labels.length) readout.push({ label: circular ? 'Slices' : 'Labels', value: String(labels.length) });
  if (datasets.length > 1) readout.push({ label: 'Series', value: String(datasets.length) });

  const height = horizontal
    ? Math.min(640, Math.max(220, labels.length * datasets.length * 26 + 70))
    : circular ? 300 : kind === 'radar' ? 340 : 320;

  return {
    kind, horizontal, labels, datasets, height, readout,
    kindName: KIND_NAMES[horizontal ? 'hbar' : kind] || 'Chart',
  };
}

function chartOptions(p: Prepared): any {
  const circular = p.kind === 'pie' || p.kind === 'doughnut';
  const showLegend = circular || p.datasets.length > 1;
  const ticks = { color: INK.muted, font: { family: FONT, size: 11 } };
  const options: any = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 350 },
    layout: { padding: { top: p.kind === 'bar' && !p.horizontal ? 18 : 6, right: p.horizontal ? 36 : 8 } },
    plugins: {
      title: { display: false },
      legend: {
        display: showLegend,
        position: circular ? 'right' : 'top',
        align: circular ? 'center' : 'end',
        labels: {
          color: INK.muted, usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 10, boxHeight: 10,
          padding: 14, font: { family: FONT, size: 12 },
        },
      },
      tooltip: {
        backgroundColor: INK.tooltip, borderColor: INK.line, borderWidth: 1, padding: 10, cornerRadius: 6,
        titleColor: INK.text, bodyColor: INK.text, titleFont: { family: FONT, weight: '600' },
        bodyFont: { family: FONT }, displayColors: true, boxPadding: 4,
        callbacks: circular ? {
          label: (ctx: any) => {
            const values = (ctx.dataset.data as unknown[]).map((v) => num(v) || 0);
            const total = values.reduce((a: number, b: number) => a + b, 0);
            const v = num(ctx.raw) || 0;
            return ` ${ctx.label}: ${fmt(v)} (${total ? Math.round((v / total) * 1000) / 10 : 0}%)`;
          },
        } : undefined,
      },
    },
  };
  if (p.kind === 'doughnut') options.cutout = '62%';
  if (p.kind === 'radar') {
    options.scales = {
      r: {
        beginAtZero: true,
        grid: { color: INK.grid }, angleLines: { color: INK.grid },
        pointLabels: { color: INK.text, font: { family: FONT, size: 12 } },
        // The rings carry the scale; numbers on them sat on the spokes.
        ticks: { display: false },
      },
    };
  } else if (!circular) {
    const valueAxis = { beginAtZero: true, ticks, grid: { color: INK.grid }, border: { display: false } };
    const categoryAxis = { ticks: { ...ticks, autoSkip: true, maxRotation: 0 }, grid: { display: false }, border: { color: INK.line } };
    if (p.horizontal) {
      options.indexAxis = 'y';
      options.scales = { x: valueAxis, y: categoryAxis };
    } else {
      options.scales = { x: p.kind === 'scatter' ? valueAxis : categoryAxis, y: valueAxis };
    }
  }
  return options;
}

/** Recompute the canvas size whenever the panel changes size or is shown. */
function useChartReflow(chartRef: React.MutableRefObject<any>, boxRef: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const resize = () => {
      if (chartRef.current) {
        chartRef.current.resize();
        chartRef.current.update('none');
      }
    };
    const timer = setTimeout(resize, 200);
    let observer: ResizeObserver | null = null;
    if (boxRef.current && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => resize());
      observer.observe(boxRef.current);
    }
    window.addEventListener('reflow-forensic-charts', resize);
    return () => {
      clearTimeout(timer);
      if (observer) observer.disconnect();
      window.removeEventListener('reflow-forensic-charts', resize);
    };
  }, [chartRef, boxRef]);
}

const VizHeader: React.FC<{ title: string; meta: string; readout?: { label: string; value: string }[] }> = ({ title, meta, readout }) => (
  <div className="viz-head">
    <div className="viz-title-row">
      <h4 className="viz-title">{title}</h4>
      <span className="viz-meta">{meta}</span>
    </div>
    {readout && readout.length > 0 && (
      <div className="viz-readout">
        {readout.map((r) => (
          <span key={r.label} className="viz-stat">
            <span className="viz-stat-label">{r.label}</span>
            <span className="viz-stat-value">{r.value}</span>
          </span>
        ))}
      </div>
    )}
  </div>
);

export const ChartBlockContent: React.FC<{ block: ChartBlock }> = ({ block }) => {
  const chartRef = useRef<any>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [showData, setShowData] = useState(false);
  const p = useMemo(() => prepare(block), [block]);
  const options = useMemo(() => chartOptions(p), [p]);
  useChartReflow(chartRef, boxRef);

  const title = block.title || (block.metadata as any)?.chart_config?.options?.plugins?.title?.text || 'Chart';
  const hasData = p.labels.length > 0 && p.datasets.some((ds) => (ds.data || []).length > 0);

  return (
    <div className="viz-block">
      <VizHeader title={title} meta={p.kindName} readout={hasData ? p.readout : []} />
      {hasData ? (
        <div className="viz-canvas" ref={boxRef} style={{ height: p.height }}>
          <Chart
            ref={chartRef}
            type={p.kind}
            data={{ labels: p.labels, datasets: p.datasets }}
            options={options}
            plugins={[valueLabels]}
          />
        </div>
      ) : (
        <div className="viz-empty">This chart has no data.</div>
      )}
      {hasData && p.kind !== 'scatter' && (
        <div className="viz-data">
          <button type="button" className="viz-data-toggle" onClick={() => setShowData((s) => !s)}>
            {showData ? 'Hide the numbers' : 'Show the numbers'}
          </button>
          {showData && (
            <div className="viz-data-scroll">
              <table className="viz-data-table">
                <thead>
                  <tr>
                    <th>Label</th>
                    {p.datasets.map((ds, i) => <th key={i}>{ds.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {p.labels.map((l, li) => (
                    <tr key={li}>
                      <td>{l}</td>
                      {p.datasets.map((ds, di) => {
                        const v = num((ds.data as unknown[])[li]);
                        return <td key={di} className="num">{v === null ? '—' : fmt(v)}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/** "2026-02-14T22:10:04.123Z" -> "2026-02-14 22:10:04 UTC" - the time as recorded, not re-zoned. */
const showTime = (ts: string) => {
  if (!ts) return '';
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(:\d{2})?)(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/.exec(ts.trim());
  if (!m) return ts;
  const zone = m[5] === 'Z' || m[5] === '+00:00' ? ' UTC' : m[5] ? ` ${m[5]}` : '';
  return `${m[1]} ${m[2]}${zone}`;
};

const gap = (ms: number) => {
  if (!Number.isFinite(ms) || ms <= 0) return '';
  const s = Math.round(ms / 1000);
  if (s < 60) return `+${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `+${m} min${s % 60 ? ` ${s % 60} s` : ''}`;
  const h = Math.floor(m / 60);
  if (h < 48) return `+${h} h${m % 60 ? ` ${m % 60} min` : ''}`;
  return `+${Math.round(h / 24)} days`;
};

const span = (ms: number) => (ms > 0 ? gap(ms).slice(1) : '');

export const TimelineBlockContent: React.FC<{ block: TimelineBlock }> = ({ block }) => {
  const events = useMemo(() => {
    const list = (block.events || []).map((ev, i) => ({ ...ev, _i: i, _t: Date.parse(ev.timestamp) }));
    return list.sort((a, b) => (Number.isFinite(a._t) && Number.isFinite(b._t) ? a._t - b._t : a._i - b._i));
  }, [block.events]);
  const categories = Array.from(new Set(events.map((e) => (e.category || '').toLowerCase()).filter(Boolean)));
  const times = events.map((e) => e._t).filter(Number.isFinite);
  const readout = [{ label: 'Events', value: String(events.length) }];
  if (times.length > 1) readout.push({ label: 'Span', value: span(Math.max(...times) - Math.min(...times)) });
  if (events.length) {
    readout.push({ label: 'First', value: showTime(events[0].timestamp) });
  }

  return (
    <div className="viz-block">
      <VizHeader title={block.title || 'Timeline'} meta="Timeline" readout={readout} />
      {categories.length > 1 && (
        <div className="tl-legend">
          {categories.map((c, i) => (
            <span key={c} className="tl-chip" style={{ ['--chip' as any]: categoryColour(c, i) }}>{c}</span>
          ))}
        </div>
      )}
      <ol className="tl-list">
        {events.map((ev, i) => {
          const colour = categoryColour(ev.category, categories.indexOf((ev.category || '').toLowerCase()));
          const prev = i > 0 ? events[i - 1]._t : NaN;
          return (
            <li key={i} className="tl-item" style={{ ['--dot' as any]: colour }}>
              <span className="tl-dot" aria-hidden="true" />
              <div className="tl-when">
                <span className="tl-time">{showTime(ev.timestamp)}</span>
                {i > 0 && gap(ev._t - prev) && <span className="tl-gap">{gap(ev._t - prev)}</span>}
              </div>
              <div className="tl-what">
                <span className="tl-label">{ev.label}</span>
                {ev.category && <span className="tl-cat">{ev.category}</span>}
              </div>
              {ev.description && <p className="tl-desc">{ev.description}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
};

/** Sequential indigo scale: panel -> #6366F1 -> #C7D2FE. */
const heat = (t: number) => {
  const stops = [[17, 24, 39], [99, 102, 241], [199, 210, 254]];
  const x = Math.max(0, Math.min(1, t)) * 2;
  const a = stops[Math.floor(Math.min(x, 1.999))];
  const b = stops[Math.floor(Math.min(x, 1.999)) + 1];
  const f = x - Math.floor(Math.min(x, 1.999));
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(', ')})`;
};

export const HeatmapBlockContent: React.FC<{ block: HeatmapBlock }> = ({ block }) => {
  const xs = block.x_labels || [];
  const ys = block.y_labels || [];
  const grid = block.intensity_values || [];
  const values = grid.flat().map((v) => num(v)).filter((v): v is number => v !== null);
  const max = values.length ? Math.max(...values) : 0;
  const min = values.length ? Math.min(...values) : 0;
  let peak = { x: '', y: '', v: -Infinity };
  grid.forEach((row, yi) => row.forEach((v, xi) => {
    const n = num(v);
    if (n !== null && n > peak.v) peak = { x: xs[xi] ?? '', y: ys[yi] ?? '', v: n };
  }));
  const readout = values.length ? [
    { label: 'Total', value: fmt(values.reduce((a, b) => a + b, 0)) },
    { label: 'Peak', value: `${peak.y} ${peak.x} · ${fmt(peak.v)}` },
  ] : [];
  const showNumbers = xs.length <= 16;

  return (
    <div className="viz-block">
      <VizHeader title={block.title || 'Heatmap'} meta="Heatmap" readout={readout} />
      {values.length === 0 ? (
        <div className="viz-empty">This heatmap has no data.</div>
      ) : (
        <div className="hm-scroll">
          <div className="hm-grid" style={{ gridTemplateColumns: `max-content repeat(${xs.length}, minmax(34px, 1fr))` }}>
            <span />
            {xs.map((x, i) => <span key={`x${i}`} className="hm-xlabel">{x}</span>)}
            {ys.map((y, yi) => (
              <React.Fragment key={`r${yi}`}>
                <span className="hm-ylabel">{y}</span>
                {xs.map((x, xi) => {
                  const v = num(grid[yi]?.[xi]);
                  const t = v === null || max === min ? (v ? 1 : 0) : (v - min) / (max - min);
                  return (
                    <span
                      key={`c${yi}-${xi}`}
                      className="hm-cell"
                      style={{ background: v === null ? 'transparent' : heat(t), color: t > 0.6 ? '#0B1220' : INK.text }}
                      title={`${y} ${x}: ${v === null ? 'no data' : fmt(v)}`}
                    >
                      {showNumbers && v !== null && v !== 0 ? fmt(v) : ''}
                    </span>
                  );
                })}
              </React.Fragment>
            ))}
          </div>
          <div className="hm-scale">
            <span>{fmt(min)}</span>
            <span className="hm-ramp" style={{ background: `linear-gradient(90deg, ${heat(0)}, ${heat(0.5)}, ${heat(1)})` }} />
            <span>{fmt(max)}</span>
          </div>
        </div>
      )}
    </div>
  );
};
