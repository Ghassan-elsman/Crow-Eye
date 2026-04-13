/**
 * linkComputer.js — Handles drawing connection curves between related events.
 */

export function computeLinks(data, activeArtifacts) {
  // We'll implement robust link correlation later.
  // For now, return an empty array to satisfy the requirement.
  return [];
}

/** Generate SVG path for a cubic bezier connection */
export function buildLinkPath(x1, y1, x2, y2) {
  const dx = Math.abs(x2 - x1);
  const cpX1 = x1 + dx * 0.4;
  const cpX2 = x2 - dx * 0.4;
  return `M ${x1} ${y1} C ${cpX1} ${y1}, ${cpX2} ${y2}, ${x2} ${y2}`;
}
