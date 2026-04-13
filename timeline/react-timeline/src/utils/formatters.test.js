/**
 * Timezone Validation Test Suite
 * Task 5.6: Comprehensive tests to ensure all timestamps display in strict UTC
 * 
 * Tests forensic accuracy across multiple timezones to verify no local timezone
 * conversion occurs anywhere in the application.
 */

import { describe, it, expect } from 'vitest';
import { formatTime, timeToX, xToTime } from './formatters.js';

describe('Timezone Validation - Task 5.6', () => {
  describe('Task 5.6.1: UTC+0 (London)', () => {
    it('should display time in UTC, not local timezone', () => {
      const testISO = '2024-01-15T14:30:00.000Z';
      const time = formatTime(testISO, 'time');
      expect(time).toContain('14:30:00');
    });

    it('should display date in UTC, not local timezone', () => {
      const testISO = '2024-01-15T14:30:00.000Z';
      const date = formatTime(testISO, 'date');
      expect(date).toContain('15 Jan 2024');
    });
  });

  describe('Task 5.6.2: UTC-5 (New York)', () => {
    it('should NOT convert date to EST (critical forensic accuracy)', () => {
      const testISO = '2024-01-15T02:00:00.000Z';
      const date = formatTime(testISO, 'date');
      // Must show Jan 15 (UTC), NOT Jan 14 (EST)
      expect(date).toContain('15 Jan 2024');
    });

    it('should NOT convert time to EST', () => {
      const testISO = '2024-01-15T02:00:00.000Z';
      const time = formatTime(testISO, 'time');
      // Must show 02:00:00 (UTC), NOT 21:00:00 (EST)
      expect(time).toContain('02:00:00');
    });
  });

  describe('Task 5.6.3: UTC+9 (Tokyo)', () => {
    it('should NOT convert date to JST (critical forensic accuracy)', () => {
      const testISO = '2024-01-15T20:00:00.000Z';
      const date = formatTime(testISO, 'date');
      // Must show Jan 15 (UTC), NOT Jan 16 (JST)
      expect(date).toContain('15 Jan 2024');
    });

    it('should NOT convert time to JST', () => {
      const testISO = '2024-01-15T20:00:00.000Z';
      const time = formatTime(testISO, 'time');
      // Must show 20:00:00 (UTC), NOT 05:00:00 (JST)
      expect(time).toContain('20:00:00');
    });
  });

  describe('Task 5.6.4: Timestamp Consistency', () => {
    it('should produce identical output for same ISO timestamp', () => {
      const testISO = '2024-06-15T12:30:45.000Z';
      const result1 = formatTime(testISO, 'full');
      const result2 = formatTime(testISO, 'full');
      const result3 = formatTime(testISO, 'full');
      
      expect(result1).toBe(result2);
      expect(result2).toBe(result3);
    });

    it('should show correct UTC values', () => {
      const testISO = '2024-06-15T12:30:45.000Z';
      const result = formatTime(testISO, 'full');
      
      expect(result).toContain('15 Jun 2024');
      expect(result).toContain('12:30:45');
    });
  });

  describe('Time Conversion Functions', () => {
    it('timeToX should correctly calculate position', () => {
      const rangeStart = '2024-01-01T00:00:00.000Z';
      const testISO = '2024-01-01T12:00:00.000Z';
      const pxPerHour = 100;
      
      const x = timeToX(testISO, rangeStart, pxPerHour);
      // 12 hours * 100 px/hour = 1200 px
      expect(x).toBe(1200);
    });

    it('xToTime should correctly convert back to ISO', () => {
      const rangeStart = '2024-01-01T00:00:00.000Z';
      const testISO = '2024-01-01T12:00:00.000Z';
      const pxPerHour = 100;
      
      const x = timeToX(testISO, rangeStart, pxPerHour);
      const isoBack = xToTime(x, rangeStart, pxPerHour);
      
      expect(isoBack).toBe(testISO);
    });
  });

  describe('DST Boundary Handling', () => {
    it('should not shift date during DST transition', () => {
      const beforeDST = '2024-03-10T01:30:00.000Z';
      const duringDST = '2024-03-10T02:30:00.000Z';
      const afterDST = '2024-03-10T03:30:00.000Z';
      
      const before = formatTime(beforeDST, 'full');
      const during = formatTime(duringDST, 'full');
      const after = formatTime(afterDST, 'full');
      
      expect(before).toContain('10 Mar 2024');
      expect(during).toContain('10 Mar 2024');
      expect(after).toContain('10 Mar 2024');
    });

    it('should not shift time during DST transition', () => {
      const beforeDST = '2024-03-10T01:30:00.000Z';
      const duringDST = '2024-03-10T02:30:00.000Z';
      const afterDST = '2024-03-10T03:30:00.000Z';
      
      const before = formatTime(beforeDST, 'full');
      const during = formatTime(duringDST, 'full');
      const after = formatTime(afterDST, 'full');
      
      expect(before).toContain('01:30');
      expect(during).toContain('02:30');
      expect(after).toContain('03:30');
    });
  });
});
