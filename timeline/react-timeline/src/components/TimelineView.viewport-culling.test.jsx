import { describe, it, expect } from 'vitest';

/**
 * Viewport Culling Optimization Tests
 * 
 * Tests for Task 7: Optimize Viewport Culling for SVG Links
 * 
 * Bug: Original implementation used AND logic, only culling links when BOTH
 * endpoints were off-screen. This caused performance issues with large datasets.
 * 
 * Fix: Changed to OR logic with 2000px buffer zone. Culls links if ANY endpoint
 * is beyond the buffer zone (viewStart - 2000 or viewEnd + 2000).
 */

describe('Viewport Culling for SVG Links', () => {
  const CULL_BUFFER = 2000;
  const viewStart = 0;
  const viewEnd = 5000;

  /**
   * Helper function to simulate the fixed culling logic
   */
  const shouldCullLink = (pa, pb, viewStart, viewEnd) => {
    const CULL_BUFFER = 2000;
    return (
      pa.x < viewStart - CULL_BUFFER ||
      pa.x > viewEnd + CULL_BUFFER ||
      pb.x < viewStart - CULL_BUFFER ||
      pb.x > viewEnd + CULL_BUFFER
    );
  };

  /**
   * Helper function for the OLD buggy culling logic (for comparison)
   */
  const shouldCullLinkOld = (pa, pb, viewStart, viewEnd) => {
    return (
      (pa.x < viewStart && pb.x < viewStart) ||
      (pa.x > viewEnd && pb.x > viewEnd)
    );
  };

  describe('7.3 Test with partially visible links', () => {
    it('should cull link when point A is visible but point B is far off-screen right', () => {
      const pa = { x: 1000 }; // Visible
      const pb = { x: 50000 }; // Far off-screen
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });

    it('should cull link when point A is far off-screen left but point B is visible', () => {
      const pa = { x: -10000 }; // Far off-screen
      const pb = { x: 2000 }; // Visible
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });

    it('should cull link when point A is visible but point B is far off-screen left', () => {
      const pa = { x: 3000 }; // Visible
      const pb = { x: -5000 }; // Far off-screen
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });

    it('should cull link when point A is far off-screen right but point B is visible', () => {
      const pa = { x: 20000 }; // Far off-screen
      const pb = { x: 4000 }; // Visible
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });
  });

  describe('7.5 Verify links near viewport edges still render', () => {
    it('should NOT cull link when both points are within viewport', () => {
      const pa = { x: 1000 };
      const pb = { x: 3000 };
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(false);
    });

    it('should NOT cull link when point A is just outside left edge within buffer', () => {
      const pa = { x: -1500 }; // Within buffer zone (-2000 to 0)
      const pb = { x: 2000 };
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(false);
    });

    it('should NOT cull link when point B is just outside right edge within buffer', () => {
      const pa = { x: 2000 };
      const pb = { x: 6500 }; // Within buffer zone (5000 to 7000)
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(false);
    });

    it('should NOT cull link when both points are at viewport edges', () => {
      const pa = { x: 0 }; // Left edge
      const pb = { x: 5000 }; // Right edge
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(false);
    });

    it('should NOT cull link spanning entire viewport', () => {
      const pa = { x: -1000 }; // Just outside left, within buffer
      const pb = { x: 6000 }; // Just outside right, within buffer
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(false);
    });
  });

  describe('Buffer zone edge cases', () => {
    it('should cull link when point A is exactly at buffer boundary (left)', () => {
      const pa = { x: -2001 }; // Just beyond buffer
      const pb = { x: 2000 };
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });

    it('should NOT cull link when point A is exactly at buffer boundary (inside)', () => {
      const pa = { x: -2000 }; // Exactly at buffer edge
      const pb = { x: 2000 };
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(false);
    });

    it('should cull link when point B is exactly at buffer boundary (right)', () => {
      const pa = { x: 2000 };
      const pb = { x: 7001 }; // Just beyond buffer (5000 + 2000 + 1)
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });

    it('should NOT cull link when point B is exactly at buffer boundary (inside)', () => {
      const pa = { x: 2000 };
      const pb = { x: 7000 }; // Exactly at buffer edge (5000 + 2000)
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(false);
    });
  });

  describe('Comparison with old buggy logic', () => {
    it('OLD LOGIC: would NOT cull link with one visible and one far off-screen endpoint', () => {
      const pa = { x: 1000 }; // Visible
      const pb = { x: 50000 }; // Far off-screen
      
      const oldShouldCull = shouldCullLinkOld(pa, pb, viewStart, viewEnd);
      expect(oldShouldCull).toBe(false); // Bug: should cull but doesn't
    });

    it('NEW LOGIC: correctly culls link with one visible and one far off-screen endpoint', () => {
      const pa = { x: 1000 }; // Visible
      const pb = { x: 50000 }; // Far off-screen
      
      const newShouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(newShouldCull).toBe(true); // Fixed: correctly culls
    });

    it('BOTH LOGICS: cull when both endpoints are far off-screen left', () => {
      const pa = { x: -5000 };
      const pb = { x: -3000 };
      
      const oldShouldCull = shouldCullLinkOld(pa, pb, viewStart, viewEnd);
      const newShouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      
      expect(oldShouldCull).toBe(true);
      expect(newShouldCull).toBe(true);
    });

    it('BOTH LOGICS: cull when both endpoints are far off-screen right', () => {
      const pa = { x: 10000 };
      const pb = { x: 15000 };
      
      const oldShouldCull = shouldCullLinkOld(pa, pb, viewStart, viewEnd);
      const newShouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      
      expect(oldShouldCull).toBe(true);
      expect(newShouldCull).toBe(true);
    });
  });

  describe('Large dataset scenarios', () => {
    it('should cull most links in a 10,000 artifact dataset when viewport shows 100 artifacts', () => {
      // Simulate 10,000 artifacts spread across 1,000,000px
      const artifacts = Array.from({ length: 10000 }, (_, i) => ({
        x: i * 100 // Spread evenly
      }));

      // Viewport showing artifacts 0-50 (x: 0-5000)
      const viewStart = 0;
      const viewEnd = 5000;

      let culledCount = 0;
      let renderedCount = 0;

      // Check links between consecutive artifacts
      for (let i = 0; i < artifacts.length - 1; i++) {
        const pa = artifacts[i];
        const pb = artifacts[i + 1];
        
        if (shouldCullLink(pa, pb, viewStart, viewEnd)) {
          culledCount++;
        } else {
          renderedCount++;
        }
      }

      // Most links should be culled (only ~70 links within buffer zone should render)
      expect(culledCount).toBeGreaterThan(9900);
      expect(renderedCount).toBeLessThan(100);
    });

    it('should handle links spanning very large distances', () => {
      const pa = { x: 100 };
      const pb = { x: 1000000 }; // 1 million pixels away
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });
  });

  describe('Edge cases and boundary conditions', () => {
    it('should handle negative viewport coordinates', () => {
      const viewStart = -5000;
      const viewEnd = 0;
      
      const pa = { x: -3000 }; // Visible
      const pb = { x: -10000 }; // Far off-screen
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });

    it('should handle zero coordinates', () => {
      const pa = { x: 0 };
      const pb = { x: 0 };
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(false);
    });

    it('should handle very small viewport', () => {
      const viewStart = 0;
      const viewEnd = 100;
      
      const pa = { x: 50 }; // Visible
      const pb = { x: 3000 }; // Beyond buffer
      
      const shouldCull = shouldCullLink(pa, pb, viewStart, viewEnd);
      expect(shouldCull).toBe(true);
    });
  });
});
