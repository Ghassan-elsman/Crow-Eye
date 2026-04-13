import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useMemo } from 'react';

/**
 * Task 10: Fix HeatmapView Date Calculation Edge Cases
 * 
 * Tests for UTC-only date arithmetic, DST boundary handling,
 * leap year handling, and month boundary validation.
 */

// Helper function to extract the days calculation logic from HeatmapView
// This allows us to test the date iteration logic in isolation
function calculateDays(globalBounds, dailyTotals) {
  if (!globalBounds?.start || !globalBounds?.end) return [];

  const start = new Date(globalBounds.start);
  const end = new Date(globalBounds.end);

  if (isNaN(start.getTime()) || isNaN(end.getTime())) return [];

  start.setUTCHours(0, 0, 0, 0);
  end.setUTCHours(23, 59, 59, 999);

  const maxSpan = 5 * 365 * 24 * 60 * 60 * 1000;
  const actualStart = (end.getTime() - start.getTime() > maxSpan)
    ? new Date(end.getTime() - maxSpan)
    : start;

  const result = [];
  let currentYear = actualStart.getUTCFullYear();
  let currentMonth = actualStart.getUTCMonth();
  let currentDay = actualStart.getUTCDate();
  
  const endTime = end.getTime();
  let iterationCount = 0;
  const MAX_ITERATIONS = 2000;

  while (iterationCount < MAX_ITERATIONS) {
    const current = new Date(Date.UTC(currentYear, currentMonth, currentDay, 0, 0, 0, 0));
    
    if (current.getTime() > endTime) break;
    
    const iso = current.toISOString().split('T')[0];
    result.push({
      date: new Date(current),
      iso,
      count: dailyTotals[iso]?.total || 0,
      sources: dailyTotals[iso]?.sources || {}
    });

    currentDay++;
    
    const daysInMonth = new Date(Date.UTC(currentYear, currentMonth + 1, 0)).getUTCDate();
    if (currentDay > daysInMonth) {
      currentDay = 1;
      currentMonth++;
      
      if (currentMonth > 11) {
        currentMonth = 0;
        currentYear++;
      }
    }
    
    const nextDate = new Date(Date.UTC(currentYear, currentMonth, currentDay, 0, 0, 0, 0));
    if (isNaN(nextDate.getTime())) {
      console.error('Invalid date generated during iteration', {
        currentYear, currentMonth, currentDay
      });
      break;
    }
    
    iterationCount++;
  }
  
  return result;
}

describe('HeatmapView Date Calculation', () => {
  describe('Task 10.1: UTC-only arithmetic', () => {
    it('10.1.1: should use UTC methods for all date operations', () => {
      const globalBounds = {
        start: '2024-01-01T00:00:00.000Z',
        end: '2024-01-05T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Verify all dates are in UTC
      days.forEach(day => {
        expect(day.date.getUTCHours()).toBe(0);
        expect(day.date.getUTCMinutes()).toBe(0);
        expect(day.date.getUTCSeconds()).toBe(0);
        expect(day.date.getUTCMilliseconds()).toBe(0);
      });

      // Verify ISO strings are UTC
      days.forEach(day => {
        expect(day.iso).toMatch(/^\d{4}-\d{2}-\d{2}$/);
        expect(day.date.toISOString().startsWith(day.iso)).toBe(true);
      });
    });

    it('10.1.2: should validate day continuity', () => {
      const globalBounds = {
        start: '2024-01-01T00:00:00.000Z',
        end: '2024-01-31T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Verify no missing days
      expect(days.length).toBe(31);

      // Verify each day is exactly 1 day after the previous
      for (let i = 1; i < days.length; i++) {
        const prevDate = days[i - 1].date;
        const currDate = days[i].date;
        const diffMs = currDate.getTime() - prevDate.getTime();
        const diffDays = diffMs / (24 * 60 * 60 * 1000);
        
        expect(diffDays).toBe(1);
      }
    });
  });

  describe('Task 10.2: DST boundary handling', () => {
    it('10.2.1: should handle spring DST transition (March 2024)', () => {
      // Spring DST in US: March 10, 2024 at 2:00 AM
      const globalBounds = {
        start: '2024-03-08T00:00:00.000Z',
        end: '2024-03-12T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Should have exactly 5 days
      expect(days.length).toBe(5);

      // Verify no missing days
      const expectedDates = [
        '2024-03-08',
        '2024-03-09',
        '2024-03-10', // DST transition day
        '2024-03-11',
        '2024-03-12'
      ];

      days.forEach((day, i) => {
        expect(day.iso).toBe(expectedDates[i]);
      });

      // Verify day continuity across DST boundary
      for (let i = 1; i < days.length; i++) {
        const prevDate = days[i - 1].date;
        const currDate = days[i].date;
        const diffMs = currDate.getTime() - prevDate.getTime();
        const diffDays = diffMs / (24 * 60 * 60 * 1000);
        
        expect(diffDays).toBe(1);
      }
    });

    it('10.2.2: should handle fall DST transition (November 2024)', () => {
      // Fall DST in US: November 3, 2024 at 2:00 AM
      const globalBounds = {
        start: '2024-11-01T00:00:00.000Z',
        end: '2024-11-05T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Should have exactly 5 days
      expect(days.length).toBe(5);

      // Verify no missing days
      const expectedDates = [
        '2024-11-01',
        '2024-11-02',
        '2024-11-03', // DST transition day
        '2024-11-04',
        '2024-11-05'
      ];

      days.forEach((day, i) => {
        expect(day.iso).toBe(expectedDates[i]);
      });
    });

    it('10.2.3: should verify no missing/duplicate days across DST', () => {
      // Test across both DST transitions in 2024
      const globalBounds = {
        start: '2024-03-08T00:00:00.000Z',
        end: '2024-11-05T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Verify no duplicate ISO dates
      const isoSet = new Set(days.map(d => d.iso));
      expect(isoSet.size).toBe(days.length);

      // Verify continuous sequence
      for (let i = 1; i < days.length; i++) {
        const prevDate = days[i - 1].date;
        const currDate = days[i].date;
        const diffMs = currDate.getTime() - prevDate.getTime();
        const diffDays = diffMs / (24 * 60 * 60 * 1000);
        
        expect(diffDays).toBe(1);
      }
    });
  });

  describe('Task 10.3: Leap year handling', () => {
    it('10.3.1: should handle February 29 in leap years', () => {
      // 2024 is a leap year
      const globalBounds = {
        start: '2024-02-27T00:00:00.000Z',
        end: '2024-03-02T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Should have exactly 5 days including Feb 29
      expect(days.length).toBe(5);

      const expectedDates = [
        '2024-02-27',
        '2024-02-28',
        '2024-02-29', // Leap day
        '2024-03-01',
        '2024-03-02'
      ];

      days.forEach((day, i) => {
        expect(day.iso).toBe(expectedDates[i]);
      });

      // Verify Feb 29 exists
      const feb29 = days.find(d => d.iso === '2024-02-29');
      expect(feb29).toBeDefined();
      expect(feb29.date.getUTCDate()).toBe(29);
      expect(feb29.date.getUTCMonth()).toBe(1); // February (0-indexed)
    });

    it('10.3.2: should handle February 28 in non-leap years', () => {
      // 2023 is not a leap year
      const globalBounds = {
        start: '2023-02-27T00:00:00.000Z',
        end: '2023-03-02T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Should have exactly 4 days (no Feb 29)
      expect(days.length).toBe(4);

      const expectedDates = [
        '2023-02-27',
        '2023-02-28',
        '2023-03-01',
        '2023-03-02'
      ];

      days.forEach((day, i) => {
        expect(day.iso).toBe(expectedDates[i]);
      });

      // Verify Feb 29 does NOT exist
      const feb29 = days.find(d => d.iso === '2023-02-29');
      expect(feb29).toBeUndefined();

      // Verify transition from Feb 28 to Mar 1
      const feb28 = days.find(d => d.iso === '2023-02-28');
      const mar1 = days.find(d => d.iso === '2023-03-01');
      expect(feb28).toBeDefined();
      expect(mar1).toBeDefined();

      const diffMs = mar1.date.getTime() - feb28.date.getTime();
      const diffDays = diffMs / (24 * 60 * 60 * 1000);
      expect(diffDays).toBe(1);
    });
  });

  describe('Task 10.4: Month boundary validation', () => {
    it('10.4.1: should handle 30-day months correctly', () => {
      // April has 30 days
      const globalBounds = {
        start: '2024-04-28T00:00:00.000Z',
        end: '2024-05-02T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      expect(days.length).toBe(5);

      const expectedDates = [
        '2024-04-28',
        '2024-04-29',
        '2024-04-30', // Last day of April
        '2024-05-01', // First day of May
        '2024-05-02'
      ];

      days.forEach((day, i) => {
        expect(day.iso).toBe(expectedDates[i]);
      });

      // Verify no April 31
      const apr31 = days.find(d => d.iso === '2024-04-31');
      expect(apr31).toBeUndefined();
    });

    it('10.4.2: should handle 31-day months correctly', () => {
      // January has 31 days
      const globalBounds = {
        start: '2024-01-29T00:00:00.000Z',
        end: '2024-02-02T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      expect(days.length).toBe(5);

      const expectedDates = [
        '2024-01-29',
        '2024-01-30',
        '2024-01-31', // Last day of January
        '2024-02-01', // First day of February
        '2024-02-02'
      ];

      days.forEach((day, i) => {
        expect(day.iso).toBe(expectedDates[i]);
      });
    });

    it('10.4.3: should verify correct day count across multiple months', () => {
      // Test across 3 months with different day counts
      const globalBounds = {
        start: '2024-01-15T00:00:00.000Z',
        end: '2024-03-15T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // January: 17 days (15-31)
      // February: 29 days (leap year)
      // March: 15 days (1-15)
      // Total: 61 days
      expect(days.length).toBe(61);

      // Verify month transitions
      const jan31 = days.find(d => d.iso === '2024-01-31');
      const feb1 = days.find(d => d.iso === '2024-02-01');
      const feb29 = days.find(d => d.iso === '2024-02-29');
      const mar1 = days.find(d => d.iso === '2024-03-01');

      expect(jan31).toBeDefined();
      expect(feb1).toBeDefined();
      expect(feb29).toBeDefined();
      expect(mar1).toBeDefined();

      // Verify continuity at boundaries
      const jan31ToFeb1 = feb1.date.getTime() - jan31.date.getTime();
      expect(jan31ToFeb1).toBe(24 * 60 * 60 * 1000);

      const feb29ToMar1 = mar1.date.getTime() - feb29.date.getTime();
      expect(feb29ToMar1).toBe(24 * 60 * 60 * 1000);
    });

    it('should handle year boundary correctly', () => {
      const globalBounds = {
        start: '2023-12-30T00:00:00.000Z',
        end: '2024-01-02T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      expect(days.length).toBe(4);

      const expectedDates = [
        '2023-12-30',
        '2023-12-31',
        '2024-01-01',
        '2024-01-02'
      ];

      days.forEach((day, i) => {
        expect(day.iso).toBe(expectedDates[i]);
      });
    });
  });

  describe('Edge cases and error handling', () => {
    it('should handle empty global bounds', () => {
      const days = calculateDays({}, {});
      expect(days).toEqual([]);
    });

    it('should handle invalid date strings', () => {
      const globalBounds = {
        start: 'invalid',
        end: 'invalid'
      };
      const days = calculateDays(globalBounds, {});
      expect(days).toEqual([]);
    });

    it('should handle very large date ranges (capped at 5 years)', () => {
      const globalBounds = {
        start: '2020-01-01T00:00:00.000Z',
        end: '2030-12-31T23:59:59.999Z' // 10+ years
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Should be capped at 5 years max
      expect(days.length).toBeLessThanOrEqual(5 * 365 + 2); // +2 for leap years
    });

    it('should handle iteration limit (2000 days)', () => {
      const globalBounds = {
        start: '2020-01-01T00:00:00.000Z',
        end: '2026-12-31T23:59:59.999Z' // ~7 years
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // Should be capped at 2000 iterations
      expect(days.length).toBeLessThanOrEqual(2000);
    });
  });

  describe('Acceptance Criteria Validation', () => {
    it('should have no missing days in heatmap calendar', () => {
      const globalBounds = {
        start: '2024-01-01T00:00:00.000Z',
        end: '2024-12-31T23:59:59.999Z'
      };
      const dailyTotals = {};

      const days = calculateDays(globalBounds, dailyTotals);

      // 2024 is a leap year: 366 days
      expect(days.length).toBe(366);

      // Verify no gaps
      for (let i = 1; i < days.length; i++) {
        const prevDate = days[i - 1].date;
        const currDate = days[i].date;
        const diffMs = currDate.getTime() - prevDate.getTime();
        const diffDays = diffMs / (24 * 60 * 60 * 1000);
        
        expect(diffDays).toBe(1);
      }
    });

    it('should have correct day alignment with data', () => {
      const dailyTotals = {
        '2024-03-10': { total: 100, sources: {} }, // DST transition day
        '2024-02-29': { total: 50, sources: {} }   // Leap day
      };

      const globalBounds = {
        start: '2024-02-28T00:00:00.000Z',
        end: '2024-03-11T23:59:59.999Z'
      };

      const days = calculateDays(globalBounds, dailyTotals);

      const dstDay = days.find(d => d.iso === '2024-03-10');
      const leapDay = days.find(d => d.iso === '2024-02-29');

      expect(dstDay.count).toBe(100);
      expect(leapDay.count).toBe(50);
    });

    it('should have no off-by-one errors near DST transitions', () => {
      // Test multiple DST transitions
      const dstTransitions = [
        { start: '2024-03-09T00:00:00.000Z', end: '2024-03-11T23:59:59.999Z' },
        { start: '2024-11-02T00:00:00.000Z', end: '2024-11-04T23:59:59.999Z' }
      ];

      dstTransitions.forEach(bounds => {
        const days = calculateDays(bounds, {});
        
        expect(days.length).toBe(3);
        
        // Verify exact dates
        const startDate = new Date(bounds.start);
        days.forEach((day, i) => {
          const expectedDate = new Date(Date.UTC(
            startDate.getUTCFullYear(),
            startDate.getUTCMonth(),
            startDate.getUTCDate() + i
          ));
          
          expect(day.date.getTime()).toBe(expectedDate.getTime());
        });
      });
    });

    it('should handle leap years correctly', () => {
      // Test leap year (2024) vs non-leap year (2023)
      const leapYearBounds = {
        start: '2024-02-01T00:00:00.000Z',
        end: '2024-02-29T23:59:59.999Z'
      };
      const nonLeapYearBounds = {
        start: '2023-02-01T00:00:00.000Z',
        end: '2023-02-28T23:59:59.999Z'
      };

      const leapYearDays = calculateDays(leapYearBounds, {});
      const nonLeapYearDays = calculateDays(nonLeapYearBounds, {});

      expect(leapYearDays.length).toBe(29);
      expect(nonLeapYearDays.length).toBe(28);

      // Verify Feb 29 exists in leap year
      const feb29 = leapYearDays.find(d => d.iso === '2024-02-29');
      expect(feb29).toBeDefined();
    });
  });
});
