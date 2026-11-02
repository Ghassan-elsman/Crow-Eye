/**
 * Icons — Shared SVG icon components.
 * No emojis. All icons are inline SVG for crisp rendering at any size, but
 * the Wing and the Feather, which are the brand's art (below).
 */

import React from 'react';
/*
 * The Wing and the Feather exactly as the User Guide draws them (Ghassan,
 * 2026-10-30): the indigo layered wing and the cyan quill, Crow-Eye's
 * correlation_engine/gui/icons/wing.png / feather.png (128 px) and their @2x
 * (256 px), byte for byte (redrawn 2026-10-30; the SVG masters are in
 * correlation_engine/gui/icons/brand/). Vite inlines them into the
 * single-file bundle as data: URIs, as it does eye_icon.png.
 */
import wingArt from './assets/wing.png';
import wingArt2x from './assets/wing@2x.png';
import featherArt from './assets/feather.png';
import featherArt2x from './assets/feather@2x.png';

interface IconProps {
  size?: number;
  className?: string;
  color?: string;
}

const defaultProps: Required<Pick<IconProps, 'size'>> = { size: 16 };

export const IconSend: React.FC<IconProps> = ({ size = 18, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);

export const IconCheck: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

export const IconX: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

export const IconLoader: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}
    style={{ animation: 'spin 1s linear infinite' }}>
    <path d="M21 12a9 9 0 1 1-6.219-8.56" />
  </svg>
);

export const IconDatabase: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <ellipse cx="12" cy="5" rx="9" ry="3" />
    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
  </svg>
);

export const IconBrain: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.46 2.5 2.5 0 0 1-1.73-3.01A3 3 0 0 1 2 13.5a3 3 0 0 1 3-3 2.5 2.5 0 0 1 1.5-4.49A2.5 2.5 0 0 1 9.5 2Z"/>
    <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.46 2.5 2.5 0 0 0 1.73-3.01A3 3 0 0 0 22 13.5a3 3 0 0 0-3-3 2.5 2.5 0 0 0-1.5-4.49A2.5 2.5 0 0 0 14.5 2Z"/>
  </svg>
);

export const IconSearch: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

export const IconLayers: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <polygon points="12 2 2 7 12 12 22 7 12 2" />
    <polyline points="2 17 12 22 22 17" />
    <polyline points="2 12 12 17 22 12" />
  </svg>
);

export const IconZap: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
  </svg>
);

export const IconTrash: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6l-1 14H6L5 6" />
    <path d="M10 11v6M14 11v6" />
    <path d="M9 6V4h6v2" />
  </svg>
);

export const IconFileText: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="16" y1="13" x2="8" y2="13" />
    <line x1="16" y1="17" x2="8" y2="17" />
    <polyline points="10 9 9 9 8 9" />
  </svg>
);

export const IconClipboardList: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
    <rect x="9" y="3" width="6" height="4" rx="2" />
    <path d="M9 12h6" /><path d="M9 16h6" />
  </svg>
);

export const IconChartBar: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M3 20h18" /><path d="M6 16h2" /><path d="M6 12h2" /><path d="M11 16h2" /><path d="M11 8h2" /><path d="M16 16h2" /><path d="M16 10h2" />
  </svg>
);

export const IconChevronRight: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

export const IconArrowLeft: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <line x1="19" y1="12" x2="5" y2="12" />
    <polyline points="12 19 5 12 12 5" />
  </svg>
);

export const IconCpu: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <rect x="4" y="4" width="16" height="16" rx="2" ry="2" />
    <rect x="9" y="9" width="6" height="6" />
    <line x1="9" y1="1" x2="9" y2="4" /><line x1="15" y1="1" x2="15" y2="4" />
    <line x1="9" y1="20" x2="9" y2="23" /><line x1="15" y1="20" x2="15" y2="23" />
    <line x1="20" y1="9" x2="23" y2="9" /><line x1="20" y1="14" x2="23" y2="14" />
    <line x1="1" y1="9" x2="4" y2="9" /><line x1="1" y1="14" x2="4" y2="14" />
  </svg>
);

export const IconSettings: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

export const IconRefresh: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <polyline points="23 4 23 10 17 10" />
    <polyline points="1 20 1 14 7 14" />
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10" />
    <path d="M20.49 15a9 9 0 0 1-14.85 3.36L1 14" />
  </svg>
);

export const IconDownload: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

// ── Narrative Map icons ──────────────────────────────────────────────
export const IconCircleCheck: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="m8.5 12 2.5 2.5 4.5-5" />
  </svg>
);

export const IconCircleMinus: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="12" cy="12" r="9" />
    <line x1="8" y1="12" x2="16" y2="12" />
  </svg>
);

export const IconAlertTriangle: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
    <line x1="12" y1="9" x2="12" y2="13" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

export const IconLockCheck: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 0 1 9.9-1" />
    <path d="m9 16 2 2 4-4" />
  </svg>
);

export const IconLock: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
);

export const IconFlag: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
    <line x1="4" y1="22" x2="4" y2="15" />
  </svg>
);

export const IconPlus: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

export const IconMinus: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

export const IconMaximize: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M8 3H5a2 2 0 0 0-2 2v3" />
    <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
    <path d="M3 16v3a2 2 0 0 0 2 2h3" />
    <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
  </svg>
);

export const IconShieldCheck: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

export const IconNote: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M14 3v4a1 1 0 0 0 1 1h4" />
    <path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z" />
    <line x1="9" y1="13" x2="15" y2="13" />
    <line x1="9" y1="17" x2="13" y2="17" />
  </svg>
);

export const IconLink: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
  </svg>
);

export const IconUser: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);

export const IconBucket: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M4 7h16l-1.6 12.2a2 2 0 0 1-2 1.8H7.6a2 2 0 0 1-2-1.8z" />
    <path d="M3 7a9 3 0 0 0 18 0a9 3 0 0 0-18 0z" />
  </svg>
);

export const IconPin: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <line x1="12" y1="17" x2="12" y2="22" />
    <path d="M9 4h6l-1 6 3 3H7l3-3-1-6z" />
  </svg>
);

export const IconWrench: React.FC<IconProps> = ({ size = defaultProps.size, className, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M14.7 6.3a4 4 0 0 0-5.2 5.2l-6.1 6.1a1.5 1.5 0 0 0 2.1 2.1l6.1-6.1a4 4 0 0 0 5.2-5.2l-2.3 2.3-2.1-2.1 2.3-2.3z" />
  </svg>
);

/*
 * Correlation Engine icons: the three engines, a Wing and a Feather. The
 * engines are the same drawings as Crow-Eye's correlation_engine/gui/icons
 * (engine_*.svg): one 1.8 stroke, round caps and joins, no fill but the record
 * dots, each in its one colour. The Wing and the Feather are the brand's art
 * (wing.png / feather.png), coloured as drawn, so they take no colour.
 */
export const ENGINE_COLORS = {
  time: '#34D399',      // Time-Window engine
  identity: '#2196F3',  // Identity engine
  behaviour: '#A78BFA', // Behavioural engine
} as const;

const EngineSvg: React.FC<{ size: number; className?: string; color: string; label: string; children: React.ReactNode }> =
  ({ size, className, color, label, children }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" className={className} role="img" aria-label={label}>
      {children}
    </svg>
  );

export const IconEngineTime: React.FC<IconProps> = ({ size = defaultProps.size, className, color = ENGINE_COLORS.time }) => (
  <EngineSvg size={size} className={className} color={color} label="Time-Window engine">
    <path d="M6.5 4H5a1.5 1.5 0 0 0 -1.5 1.5V18.5A1.5 1.5 0 0 0 5 20H6.5M17.5 4H19a1.5 1.5 0 0 1 1.5 1.5V18.5A1.5 1.5 0 0 1 19 20H17.5" />
    <circle cx="12" cy="10.5" r="4.2" />
    <path d="M12 8.3V10.5L13.6 11.6" />
    <circle cx="8.6" cy="17.2" r="1.2" fill={color} stroke="none" />
    <circle cx="12" cy="17.2" r="1.2" fill={color} stroke="none" />
    <circle cx="15.4" cy="17.2" r="1.2" fill={color} stroke="none" />
  </EngineSvg>
);

export const IconEngineIdentity: React.FC<IconProps> = ({ size = defaultProps.size, className, color = ENGINE_COLORS.identity }) => (
  <EngineSvg size={size} className={className} color={color} label="Identity engine">
    <circle cx="16" cy="12" r="4.5" />
    <circle cx="16" cy="12" r="1.6" fill={color} stroke="none" />
    <path d="M6.6 6.7L10.8 9.05M7 12H10M6.6 17.3L10.8 14.95" />
    <circle cx="4.4" cy="5.6" r="1.6" fill={color} stroke="none" />
    <rect x="3" y="10.6" width="2.8" height="2.8" rx=".6" fill={color} stroke="none" />
    <path d="M4.4 16.6L5.9 18.4 4.4 20.2 2.9 18.4Z" fill={color} stroke="none" />
  </EngineSvg>
);

export const IconEngineBehaviour: React.FC<IconProps> = ({ size = defaultProps.size, className, color = ENGINE_COLORS.behaviour }) => (
  <EngineSvg size={size} className={className} color={color} label="Behavioural engine">
    <circle cx="12" cy="6" r="2.5" />
    <path d="M7.5 13C7.5 10.5 9.5 9 12 9S16.5 10.5 16.5 13" />
    <circle cx="4.5" cy="18.5" r="1.5" fill={color} stroke="none" />
    <circle cx="12" cy="18.5" r="1.5" fill={color} stroke="none" />
    <circle cx="19.5" cy="18.5" r="1.5" fill={color} stroke="none" />
    <path d="M6.8 18.5H9.4M8.2 17.2L9.5 18.5 8.2 19.8M14.3 18.5H16.9M15.7 17.2L17 18.5 15.7 19.8" />
  </EngineSvg>
);

/* The brand art as an <img>: the 128 px file, and the 256 px one on a
   high-density screen. */
const BrandArt: React.FC<{ size: number; className?: string; src: string; src2x: string; label: string }> =
  ({ size, className, src, src2x, label }) => (
    <img src={src} srcSet={`${src} 1x, ${src2x} 2x`} width={size} height={size} alt={label}
      className={className} draggable={false} style={{ display: 'block', objectFit: 'contain' }} />
  );

export const IconWing: React.FC<IconProps> = ({ size = defaultProps.size, className }) => (
  <BrandArt size={size} className={className} src={wingArt} src2x={wingArt2x} label="Wing" />
);

export const IconFeather: React.FC<IconProps> = ({ size = defaultProps.size, className }) => (
  <BrandArt size={size} className={className} src={featherArt} src2x={featherArt2x} label="Feather" />
);

/**
 * The Correlation Engine icon for an Eye tool call, or null when the tool does
 * not touch a Wing, a Feather or an engine. Writing a Wing shows the Wing;
 * reading correlation results shows the engine that produced them.
 */
export const correlationToolIcon = (tool: string | undefined, params: Record<string, any> | undefined, size: number): React.ReactElement | null => {
  switch (tool) {
    case 'correlation_create_wing':
    case 'correlation_edit_wing':
      return <IconWing size={size} />;
    case 'query_correlation_results': {
      const qtype = String(params?.query_type ?? '').toLowerCase();
      if (qtype === 'time') return <IconEngineTime size={size} />;
      if (qtype === 'identity') return <IconEngineIdentity size={size} />;
      return null;
    }
    default:
      return null;
  }
};

/** Returns the correct icon component for a ThinkingStep type */
export const StepIcon: React.FC<{ type: string; status: string; size?: number; tool?: string; params?: Record<string, any> }> =
  ({ type, status, size = 14, tool, params }) => {
  if (status === 'error') return <IconX size={size} color="var(--color-error)" />;
  if (status === 'active') return <IconLoader size={size} color="var(--color-accent)" />;
  // done states: a Correlation Engine tool shows its Wing / engine icon
  const correlation = correlationToolIcon(tool, params, size);
  if (correlation) return correlation;
  switch (type) {
    case 'rag':       return <IconSearch size={size} color="var(--color-cyan)" />;
    case 'tool_call': return <IconDatabase size={size} color="var(--color-accent)" />;
    case 'synthesis': return <IconLayers size={size} color="var(--color-success)" />;
    default:          return <IconCheck size={size} color="var(--color-success)" />;
  }
};
