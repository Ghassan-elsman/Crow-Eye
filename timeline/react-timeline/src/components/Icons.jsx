/**
 * Icons — shared inline-SVG icon components for the Timeline.
 * No emojis. Monochrome stroke icons (feather style); pass `color` to tint
 * (lane icons use their lane color). Mirrors eye/ui/react/src/Icons.tsx.
 */

const Svg = ({ size = 16, color = 'currentColor', strokeWidth = 2, className, children }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    style={{ flex: '0 0 auto' }}
  >
    {children}
  </svg>
);

// ── Lane icons ─────────────────────────────────────────────
export const IconPower = (p) => (   // sessions / power
  <Svg {...p}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></Svg>
);
export const IconBarChart = (p) => (  // srum_app usage / weekly distribution
  <Svg {...p}><line x1="6" y1="20" x2="6" y2="12" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="18" y1="20" x2="18" y2="9" /></Svg>
);
export const IconGlobe = (p) => (   // srum_net / UTC
  <Svg {...p}><circle cx="12" cy="12" r="9" /><line x1="3" y1="12" x2="21" y2="12" /><path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18z" /></Svg>
);
export const IconFiles = (p) => (   // mft / usn — filesystem
  <Svg {...p}><path d="M15 2H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V6z" /><polyline points="15 2 15 6 19 6" /><path d="M6 6H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-1" /></Svg>
);
export const IconRefresh = (p) => (   // prefetch / execution
  <Svg {...p}><polyline points="21 3 21 9 15 9" /><path d="M20 13a8 8 0 1 1-2.3-5.7L21 9" /></Svg>
);
export const IconLink = (p) => (   // lnk / jump lists
  <Svg {...p}><path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" /></Svg>
);
export const IconGear = (p) => (   // bam
  <Svg {...p}><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></Svg>
);
export const IconKey = (p) => (   // registry
  <Svg {...p}><circle cx="7.5" cy="15.5" r="4.5" /><line x1="10.7" y1="12.3" x2="20" y2="3" /><line x1="17" y1="6" x2="20" y2="9" /><line x1="14" y1="9" x2="16.5" y2="11.5" /></Svg>
);
export const IconClipboard = (p) => (   // amcache
  <Svg {...p}><rect x="8" y="3" width="8" height="4" rx="1" /><path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2" /></Svg>
);
export const IconArchive = (p) => (   // shimcache
  <Svg {...p}><rect x="3" y="4" width="18" height="4" rx="1" /><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8" /><line x1="10" y1="12" x2="14" y2="12" /></Svg>
);
export const IconTrash = (p) => (   // recyclebin
  <Svg {...p}><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /><path d="M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" /></Svg>
);
export const IconInbox = (p) => (   // imported evidence
  <Svg {...p}><polyline points="22 12 16 12 14 15 10 15 8 12 2 12" /><path d="M5.5 5.5L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.5A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.5z" /></Svg>
);

// ── Header / toolbar icons ─────────────────────────────────
export const IconSearch = (p) => (
  <Svg {...p}><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></Svg>
);
export const IconTag = (p) => (   // event record
  <Svg {...p}><path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0l-7-7A2 2 0 0 1 3 12.2V5a2 2 0 0 1 2-2h7.2a2 2 0 0 1 1.4.6l7 7a2 2 0 0 1 0 2.8z" /><circle cx="7.5" cy="7.5" r="1.3" fill={p.color || 'currentColor'} stroke="none" /></Svg>
);
export const IconGrid = (p) => (   // heatmap / global case overview
  <Svg {...p}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></Svg>
);

// name → component map for ARTIFACT_CONFIG.icon keys + header uses.
const ICONS = {
  power: IconPower,
  barChart: IconBarChart,
  globe: IconGlobe,
  files: IconFiles,
  refresh: IconRefresh,
  link: IconLink,
  gear: IconGear,
  key: IconKey,
  clipboard: IconClipboard,
  archive: IconArchive,
  trash: IconTrash,
  inbox: IconInbox,
  search: IconSearch,
  tag: IconTag,
  grid: IconGrid,
};

/** Render an icon by name (used by PillBar for ARTIFACT_CONFIG.icon). */
export function LaneIcon({ name, size = 14, color = 'currentColor', className }) {
  const Cmp = ICONS[name];
  if (!Cmp) return null;
  return <Cmp size={size} color={color} className={className} />;
}
