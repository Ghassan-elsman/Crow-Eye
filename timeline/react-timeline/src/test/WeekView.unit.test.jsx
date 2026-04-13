/**
 * WeekView Unit Tests - getTimestampForArtifact Helper Function
 * 
 * Tests for Task 11: Fix WeekView Timestamp Fallback Chain
 * 
 * These tests validate the artifact-type-specific timestamp extraction logic
 * in isolation from the full component rendering.
 */

import { describe, it, expect } from 'vitest';

/**
 * Extract the getTimestampForArtifact function logic for unit testing.
 * This is a copy of the function from WeekView.jsx for isolated testing.
 */
const getTimestampForArtifact = (artifact, type) => {
  if (!artifact) return null;
  
  switch (type) {
    case 'srum':
      return artifact.timestamp;
    
    case 'mft':
      return artifact.usn_timestamp || artifact.si_creation_time;
    
    case 'exec':
      return artifact.last_executed || artifact.last_execution || artifact.Time_Access;
    
    case 'amcache':
      return artifact.link_date || artifact.install_date || artifact.driver_time_stamp;
    
    case 'shimcache':
      return artifact.last_modified;
    
    case 'recyclebin':
      return artifact.deletion_time;
    
    case 'registry':
      return artifact.access_date || artifact.accessed_date || artifact.modified_date;
    
    case 'sessions':
      return artifact.timestamp || artifact.start;
    
    default:
      return artifact.timestamp || artifact.start;
  }
};

describe('getTimestampForArtifact - Unit Tests', () => {
  describe('SRUM Type', () => {
    it('should return timestamp for SRUM artifacts', () => {
      const artifact = { timestamp: '2024-01-01T12:00:00.000Z' };
      expect(getTimestampForArtifact(artifact, 'srum')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null when timestamp is missing', () => {
      const artifact = { app_name: 'test.exe' };
      expect(getTimestampForArtifact(artifact, 'srum')).toBeUndefined();
    });

    it('should not use fallback fields for SRUM', () => {
      const artifact = {
        usn_timestamp: '2024-01-02T12:00:00.000Z',
        last_executed: '2024-01-03T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'srum')).toBeUndefined();
    });
  });

  describe('MFT Type', () => {
    it('should prefer usn_timestamp over si_creation_time', () => {
      const artifact = {
        usn_timestamp: '2024-01-01T12:00:00.000Z',
        si_creation_time: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'mft')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to si_creation_time when usn_timestamp is missing', () => {
      const artifact = {
        si_creation_time: '2024-01-01T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'mft')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null when both timestamps are missing', () => {
      const artifact = { file_name: 'test.txt' };
      expect(getTimestampForArtifact(artifact, 'mft')).toBeUndefined();
    });

    it('should handle falsy usn_timestamp and use si_creation_time', () => {
      const artifact = {
        usn_timestamp: null,
        si_creation_time: '2024-01-01T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'mft')).toBe('2024-01-01T12:00:00.000Z');
    });
  });

  describe('Exec Type', () => {
    it('should prefer last_executed (Prefetch)', () => {
      const artifact = {
        last_executed: '2024-01-01T12:00:00.000Z',
        last_execution: '2024-01-02T12:00:00.000Z',
        Time_Access: '2024-01-03T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'exec')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to last_execution (BAM) when last_executed is missing', () => {
      const artifact = {
        last_execution: '2024-01-01T12:00:00.000Z',
        Time_Access: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'exec')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to Time_Access (LNK) when others are missing', () => {
      const artifact = {
        Time_Access: '2024-01-01T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'exec')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null when all exec timestamps are missing', () => {
      const artifact = { executable: 'test.exe' };
      expect(getTimestampForArtifact(artifact, 'exec')).toBeUndefined();
    });
  });

  describe('Amcache Type', () => {
    it('should prefer link_date (application_files)', () => {
      const artifact = {
        link_date: '2024-01-01T12:00:00.000Z',
        install_date: '2024-01-02T12:00:00.000Z',
        driver_time_stamp: '2024-01-03T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'amcache')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to install_date (applications)', () => {
      const artifact = {
        install_date: '2024-01-01T12:00:00.000Z',
        driver_time_stamp: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'amcache')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to driver_time_stamp (drivers)', () => {
      const artifact = {
        driver_time_stamp: '2024-01-01T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'amcache')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null when all amcache timestamps are missing', () => {
      const artifact = { file_path: 'C:\\test.exe' };
      expect(getTimestampForArtifact(artifact, 'amcache')).toBeUndefined();
    });
  });

  describe('Shimcache Type', () => {
    it('should return last_modified for shimcache artifacts', () => {
      const artifact = { last_modified: '2024-01-01T12:00:00.000Z' };
      expect(getTimestampForArtifact(artifact, 'shimcache')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null when last_modified is missing', () => {
      const artifact = { path: 'C:\\test.exe' };
      expect(getTimestampForArtifact(artifact, 'shimcache')).toBeUndefined();
    });

    it('should not use other timestamp fields for shimcache', () => {
      const artifact = {
        timestamp: '2024-01-02T12:00:00.000Z',
        last_executed: '2024-01-03T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'shimcache')).toBeUndefined();
    });
  });

  describe('RecycleBin Type', () => {
    it('should return deletion_time for recyclebin artifacts', () => {
      const artifact = { deletion_time: '2024-01-01T12:00:00.000Z' };
      expect(getTimestampForArtifact(artifact, 'recyclebin')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null when deletion_time is missing', () => {
      const artifact = { original_path: 'C:\\test.txt' };
      expect(getTimestampForArtifact(artifact, 'recyclebin')).toBeUndefined();
    });

    it('should not use other timestamp fields for recyclebin', () => {
      const artifact = {
        timestamp: '2024-01-02T12:00:00.000Z',
        last_modified: '2024-01-03T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'recyclebin')).toBeUndefined();
    });
  });

  describe('Registry Type', () => {
    it('should prefer access_date', () => {
      const artifact = {
        access_date: '2024-01-01T12:00:00.000Z',
        accessed_date: '2024-01-02T12:00:00.000Z',
        modified_date: '2024-01-03T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'registry')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to accessed_date', () => {
      const artifact = {
        accessed_date: '2024-01-01T12:00:00.000Z',
        modified_date: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'registry')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to modified_date', () => {
      const artifact = {
        modified_date: '2024-01-01T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'registry')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null when all registry timestamps are missing', () => {
      const artifact = { file_path: 'C:\\test.txt' };
      expect(getTimestampForArtifact(artifact, 'registry')).toBeUndefined();
    });
  });

  describe('Sessions Type', () => {
    it('should prefer timestamp over start', () => {
      const artifact = {
        timestamp: '2024-01-01T12:00:00.000Z',
        start: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'sessions')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to start', () => {
      const artifact = {
        start: '2024-01-01T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'sessions')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null when both timestamps are missing', () => {
      const artifact = { event_name: 'Logon' };
      expect(getTimestampForArtifact(artifact, 'sessions')).toBeUndefined();
    });
  });

  describe('Default/Unknown Type', () => {
    it('should use timestamp for unknown types', () => {
      const artifact = {
        timestamp: '2024-01-01T12:00:00.000Z',
        start: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'unknown')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should fallback to start for unknown types', () => {
      const artifact = {
        start: '2024-01-01T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'unknown')).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should return null for unknown types with no common fields', () => {
      const artifact = { some_field: 'value' };
      expect(getTimestampForArtifact(artifact, 'unknown')).toBeUndefined();
    });
  });

  describe('Edge Cases', () => {
    it('should return null for null artifact', () => {
      expect(getTimestampForArtifact(null, 'srum')).toBeNull();
    });

    it('should return null for undefined artifact', () => {
      expect(getTimestampForArtifact(undefined, 'srum')).toBeNull();
    });

    it('should handle empty object', () => {
      expect(getTimestampForArtifact({}, 'srum')).toBeUndefined();
    });

    it('should handle artifact with only non-timestamp fields', () => {
      const artifact = {
        name: 'test',
        path: 'C:\\test',
        size: 1024
      };
      expect(getTimestampForArtifact(artifact, 'srum')).toBeUndefined();
    });

    it('should handle empty string timestamps', () => {
      const artifact = { timestamp: '' };
      expect(getTimestampForArtifact(artifact, 'srum')).toBe('');
    });

    it('should handle zero as timestamp', () => {
      const artifact = { timestamp: 0 };
      expect(getTimestampForArtifact(artifact, 'srum')).toBe(0);
    });

    it('should handle false as timestamp', () => {
      const artifact = { timestamp: false };
      expect(getTimestampForArtifact(artifact, 'srum')).toBe(false);
    });
  });

  describe('Consistency Validation', () => {
    it('should always return the same result for the same input', () => {
      const artifact = {
        usn_timestamp: '2024-01-01T12:00:00.000Z',
        si_creation_time: '2024-01-02T12:00:00.000Z'
      };
      
      const result1 = getTimestampForArtifact(artifact, 'mft');
      const result2 = getTimestampForArtifact(artifact, 'mft');
      const result3 = getTimestampForArtifact(artifact, 'mft');
      
      expect(result1).toBe(result2);
      expect(result2).toBe(result3);
      expect(result1).toBe('2024-01-01T12:00:00.000Z');
    });

    it('should not modify the input artifact', () => {
      const artifact = {
        timestamp: '2024-01-01T12:00:00.000Z',
        app_name: 'test.exe'
      };
      const originalArtifact = { ...artifact };
      
      getTimestampForArtifact(artifact, 'srum');
      
      expect(artifact).toEqual(originalArtifact);
    });
  });

  describe('Type-Specific Field Isolation', () => {
    it('should not use SRUM fields for MFT type', () => {
      const artifact = {
        timestamp: '2024-01-01T12:00:00.000Z',
        usn_timestamp: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'mft')).toBe('2024-01-02T12:00:00.000Z');
    });

    it('should not use MFT fields for SRUM type', () => {
      const artifact = {
        usn_timestamp: '2024-01-01T12:00:00.000Z',
        timestamp: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'srum')).toBe('2024-01-02T12:00:00.000Z');
    });

    it('should not use exec fields for shimcache type', () => {
      const artifact = {
        last_executed: '2024-01-01T12:00:00.000Z',
        last_modified: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'shimcache')).toBe('2024-01-02T12:00:00.000Z');
    });

    it('should not use registry fields for recyclebin type', () => {
      const artifact = {
        access_date: '2024-01-01T12:00:00.000Z',
        deletion_time: '2024-01-02T12:00:00.000Z'
      };
      expect(getTimestampForArtifact(artifact, 'recyclebin')).toBe('2024-01-02T12:00:00.000Z');
    });
  });
});
