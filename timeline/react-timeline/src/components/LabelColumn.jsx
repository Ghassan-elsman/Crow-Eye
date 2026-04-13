/**
 * LabelColumn — Left-side lane labels with drag-to-resize handles.
 */
import { memo, useCallback, useRef } from 'react';

const LANES = [
  { key: 'sessions',  label: 'Sessions / Power',   sub: 'Login, Logout, Power, Sleep', color: 'var(--lane-sessions)' },
  { key: 'srum_app',  label: 'SRUM App Usage',      sub: 'FG/BG Cycles, Face Time',    color: 'var(--lane-srum-app)' },
  { key: 'srum_net',  label: 'SRUM Network',         sub: 'Connectivity, Data Usage',   color: 'var(--lane-srum-net)' },
  { key: 'mft_usn',   label: 'MFT / USN',            sub: 'File Create, Modify, Delete', color: 'var(--lane-mft-usn)' },
  { key: 'execution', label: 'Execution Artifacts',  sub: 'Prefetch, LNK, BAM, Registry', color: 'var(--lane-execution)' },
  { key: 'cache',     label: 'Cache & RecycleBin',   sub: 'AmCache, ShimCache, Bin',    color: 'var(--lane-cache)' },
];

function LabelColumn({ state }) {
  const { laneHeights, setLaneHeight, activeArtifacts } = state;
  const dragRef = useRef(null);

  const onMouseDown = useCallback((e, laneKey) => {
    e.preventDefault();
    const startY = e.clientY;
    const startHeight = laneHeights[laneKey] || 100;

    const onMove = (moveEvt) => {
      const delta = moveEvt.clientY - startY;
      setLaneHeight(laneKey, startHeight + delta);
    };

    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [laneHeights, setLaneHeight]);

  // Determine which lanes are visible
  const isLaneVisible = (lane) => {
    if (lane.key === 'execution') {
      return activeArtifacts.prefetch || activeArtifacts.lnk || activeArtifacts.bam || activeArtifacts.registry;
    }
    if (lane.key === 'cache') {
      return activeArtifacts.amcache || activeArtifacts.shimcache || activeArtifacts.recyclebin;
    }
    return activeArtifacts[lane.key] !== false;
  };

  return (
    <div className="label-column">
      <div style={{ height: 30, borderBottom: '1px solid var(--border-subtle)', flexShrink: 0, backgroundColor: 'var(--bg-primary)' }} />
      {LANES.filter(isLaneVisible).map((lane) => (
        <div
          key={lane.key}
          className="label-column__item"
          style={{ height: laneHeights[lane.key] || 100, marginBottom: 2, flexShrink: 0 }}
        >
          <div className="label-column__indicator" style={{ background: lane.color }} />
          <div>
            <div className="label-column__text">{lane.label}</div>
            <div className="label-column__subtext">{lane.sub}</div>
          </div>
          
          {/* Dedicated Resize Handle */}
          <div 
            className="label-column__resizer"
            onMouseDown={(e) => onMouseDown(e, lane.key)}
          />
        </div>
      ))}
    </div>
  );
}

export default memo(LabelColumn);
