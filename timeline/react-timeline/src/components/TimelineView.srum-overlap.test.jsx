/**
 * Unit tests for SRUM Background Time Extrapolation Overlap Fix (Task 8)
 * Tests the actual background_cycle_time usage and overlap detection
 */

import { describe, it, expect } from 'vitest';

/**
 * Simulates the SRUM app processing logic from TimelineView.jsx
 * This is the FIXED version with overlap detection
 */
function processSRUMApps(srumData) {
  return srumData.map((a, idx, arr) => {
    const ts = new Date(a.timestamp).getTime();
    const faceMs = a.face_time ? Number(a.face_time) * 1000 : 0;
    
    // Use actual background_cycle_time instead of fixed 1-hour
    const bgCycleMs = a.background_cycle_time ? Number(a.background_cycle_time) * 1000 : 0;
    let bgStart = ts - Math.max(20000, bgCycleMs);
    
    // Add overlap detection with previous events for the same app
    if (idx > 0) {
      for (let i = idx - 1; i >= 0; i--) {
        const prev = arr[i];
        if (prev.app_name === a.app_name) {
          const prevEnd = new Date(prev.timestamp).getTime();
          // Adjust bgStart if overlap detected
          if (bgStart < prevEnd) {
            bgStart = prevEnd;
          }
          break; // Only check the most recent previous event for same app
        }
      }
    }
    
    return { 
      ...a, 
      start: ts - Math.max(20000, faceMs), 
      end: ts, 
      bgStart, 
      type: 'srum_app' 
    };
  });
}

describe('TimelineView SRUM Overlap Fix (Task 8)', () => {
  
  // Task 8.1.1: Use actual background_cycle_time instead of fixed 1-hour
  it('should use actual background_cycle_time instead of fixed 1-hour', () => {
    const srumData = [
      {
        timestamp: '2024-01-15T12:00:00.000Z',
        app_name: 'chrome.exe',
        face_time: 60, // 60 seconds
        background_cycle_time: 300 // 5 minutes (300 seconds)
      }
    ];
    
    const processed = processSRUMApps(srumData);
    const ts = new Date(srumData[0].timestamp).getTime();
    const expectedBgStart = ts - (300 * 1000); // 5 minutes back, not 1 hour
    
    expect(processed[0].bgStart).toBe(expectedBgStart);
    expect(processed[0].bgStart).not.toBe(ts - 3600000); // NOT 1 hour back
  });
  
  // Task 8.1.2: Add overlap detection with previous events
  it('should detect overlap with previous event for same app', () => {
    const srumData = [
      {
        timestamp: '2024-01-15T12:00:00.000Z',
        app_name: 'chrome.exe',
        face_time: 60,
        background_cycle_time: 300
      },
      {
        timestamp: '2024-01-15T12:03:00.000Z', // 3 minutes later
        app_name: 'chrome.exe',
        face_time: 45,
        background_cycle_time: 300 // Would overlap if extrapolated 5 minutes back
      }
    ];
    
    const processed = processSRUMApps(srumData);
    const firstEnd = new Date(srumData[0].timestamp).getTime();
    const secondTs = new Date(srumData[1].timestamp).getTime();
    const naiveBgStart = secondTs - (300 * 1000); // Would be 5 minutes back
    
    // Verify overlap would occur without fix
    expect(naiveBgStart).toBeLessThan(firstEnd);
    
    // Verify fix adjusts bgStart to prevent overlap
    expect(processed[1].bgStart).toBeGreaterThanOrEqual(firstEnd);
    expect(processed[1].bgStart).toBe(firstEnd); // Should be adjusted to firstEnd
  });
  
  // Task 8.1.3: Adjust bgStart if overlap detected
  it('should adjust bgStart to previous event end when overlap detected', () => {
    const srumData = [
      {
        timestamp: '2024-01-15T12:00:00.000Z',
        app_name: 'cmd.exe',
        face_time: 30,
        background_cycle_time: 600 // 10 minutes
      },
      {
        timestamp: '2024-01-15T12:05:00.000Z', // 5 minutes later
        app_name: 'cmd.exe',
        face_time: 20,
        background_cycle_time: 600 // 10 minutes - would overlap
      }
    ];
    
    const processed = processSRUMApps(srumData);
    const firstEnd = new Date(srumData[0].timestamp).getTime();
    
    // Second event's bgStart should be adjusted to first event's end
    expect(processed[1].bgStart).toBe(firstEnd);
  });
  
  // Task 8.3: Test with periodic SRUM logs (1-hour intervals)
  it('should handle periodic SRUM logs without chaotic overlap', () => {
    const baseTime = new Date('2024-01-15T12:00:00.000Z').getTime();
    const srumData = [
      {
        timestamp: new Date(baseTime).toISOString(),
        app_name: 'chrome.exe',
        face_time: 120,
        background_cycle_time: 3600 // 1 hour
      },
      {
        timestamp: new Date(baseTime + 3600000).toISOString(), // +1 hour
        app_name: 'chrome.exe',
        face_time: 150,
        background_cycle_time: 3600 // 1 hour
      },
      {
        timestamp: new Date(baseTime + 7200000).toISOString(), // +2 hours
        app_name: 'chrome.exe',
        face_time: 180,
        background_cycle_time: 3600 // 1 hour
      }
    ];
    
    const processed = processSRUMApps(srumData);
    
    // Verify no overlaps
    for (let i = 1; i < processed.length; i++) {
      const prevEnd = processed[i - 1].end;
      const currentBgStart = processed[i].bgStart;
      expect(currentBgStart).toBeGreaterThanOrEqual(prevEnd);
    }
  });
  
  // Task 8.4: Test with dense SRUM data
  it('should handle dense SRUM data without excessive overlaps', () => {
    const baseTime = new Date('2024-01-15T12:00:00.000Z').getTime();
    const srumData = [];
    
    // Create 10 events for same app, 2 minutes apart
    for (let i = 0; i < 10; i++) {
      srumData.push({
        timestamp: new Date(baseTime + i * 120000).toISOString(), // +2 minutes each
        app_name: 'notepad.exe',
        face_time: 30,
        background_cycle_time: 300 // 5 minutes - would cause overlaps
      });
    }
    
    const processed = processSRUMApps(srumData);
    
    // Verify no overlaps in dense data
    for (let i = 1; i < processed.length; i++) {
      const prevEnd = processed[i - 1].end;
      const currentBgStart = processed[i].bgStart;
      expect(currentBgStart).toBeGreaterThanOrEqual(prevEnd);
    }
  });
  
  // Test that different apps don't interfere with each other
  it('should only check overlap for same app_name', () => {
    const srumData = [
      {
        timestamp: '2024-01-15T12:00:00.000Z',
        app_name: 'chrome.exe',
        face_time: 60,
        background_cycle_time: 300
      },
      {
        timestamp: '2024-01-15T12:02:00.000Z', // 2 minutes later
        app_name: 'firefox.exe', // Different app
        face_time: 45,
        background_cycle_time: 300
      }
    ];
    
    const processed = processSRUMApps(srumData);
    const secondTs = new Date(srumData[1].timestamp).getTime();
    const expectedBgStart = secondTs - (300 * 1000);
    
    // Firefox should NOT be adjusted based on Chrome's end time
    expect(processed[1].bgStart).toBe(expectedBgStart);
  });
  
  // Test minimum 20-second background time
  it('should use minimum 20-second background time when bgCycleMs is small', () => {
    const srumData = [
      {
        timestamp: '2024-01-15T12:00:00.000Z',
        app_name: 'test.exe',
        face_time: 5,
        background_cycle_time: 0.5 // 0.5 seconds - very small
      }
    ];
    
    const processed = processSRUMApps(srumData);
    const ts = new Date(srumData[0].timestamp).getTime();
    const expectedBgStart = ts - 20000; // Should use 20-second minimum
    
    expect(processed[0].bgStart).toBe(expectedBgStart);
  });
  
  // Test with missing background_cycle_time field
  it('should handle missing background_cycle_time gracefully', () => {
    const srumData = [
      {
        timestamp: '2024-01-15T12:00:00.000Z',
        app_name: 'test.exe',
        face_time: 60
        // No background_cycle_time field
      }
    ];
    
    const processed = processSRUMApps(srumData);
    const ts = new Date(srumData[0].timestamp).getTime();
    const expectedBgStart = ts - 20000; // Should use 20-second minimum
    
    expect(processed[0].bgStart).toBe(expectedBgStart);
  });
});
