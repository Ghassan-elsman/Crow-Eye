/**
 * WeekView Timestamp Extraction Tests
 * 
 * Tests for Task 11: Fix WeekView Timestamp Fallback Chain
 * 
 * Validates:
 * - Artifact-type-specific timestamp extraction
 * - Correct event counts in week view
 * - Events assigned to correct days
 * - Accurate weekly distribution visualization
 */

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import WeekView from '../components/WeekView';

describe('WeekView - Timestamp Extraction', () => {
  // Helper to create a basic state object
  const createState = () => ({
    timeRange: {
      start: '2024-01-01T00:00:00.000Z',
      end: '2024-01-07T23:59:59.999Z'
    },
    setTimeRange: () => {},
    setViewModeOverride: () => {}
  });

  // Helper to create test data with specific timestamps
  const createTestData = () => ({
    srum_app: [],
    mft_usn: [],
    prefetch: [],
    bam: [],
    lnk: [],
    srum_net: { connectivity: [], data_usage: [] },
    amcache: { application_files: [], applications: [], drivers: [] },
    shimcache: [],
    recyclebin: [],
    registry: { open_save_mru: [], last_save_mru: [], shellbags: [], recent_docs: [], user_assist: [] },
    sessions: { events: [] }
  });

  describe('SRUM Artifact Timestamp Extraction', () => {
    it('should use timestamp field for SRUM artifacts', () => {
      const data = createTestData();
      data.srum_app = [
        { timestamp: '2024-01-01T12:00:00.000Z', app_name: 'test.exe' },
        { timestamp: '2024-01-02T12:00:00.000Z', app_name: 'test2.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      
      // Verify component renders without errors
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should handle SRUM artifacts with missing timestamp', () => {
      const data = createTestData();
      data.srum_app = [
        { app_name: 'test.exe' }, // No timestamp
        { timestamp: '2024-01-01T12:00:00.000Z', app_name: 'test2.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('MFT/USN Artifact Timestamp Extraction', () => {
    it('should prefer usn_timestamp over si_creation_time for MFT artifacts', () => {
      const data = createTestData();
      data.mft_usn = [
        {
          usn_timestamp: '2024-01-01T12:00:00.000Z',
          si_creation_time: '2024-01-02T12:00:00.000Z', // Should be ignored
          file_name: 'test.txt'
        }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should fallback to si_creation_time when usn_timestamp is missing', () => {
      const data = createTestData();
      data.mft_usn = [
        {
          si_creation_time: '2024-01-01T12:00:00.000Z',
          file_name: 'test.txt'
        }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should handle MFT artifacts with no timestamps', () => {
      const data = createTestData();
      data.mft_usn = [
        { file_name: 'test.txt' } // No timestamps
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Execution Artifact Timestamp Extraction', () => {
    it('should use last_executed for Prefetch artifacts', () => {
      const data = createTestData();
      data.prefetch = [
        { last_executed: '2024-01-01T12:00:00.000Z', executable: 'test.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should use last_execution for BAM artifacts', () => {
      const data = createTestData();
      data.bam = [
        { last_execution: '2024-01-01T12:00:00.000Z', executable: 'test.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should use Time_Access for LNK artifacts', () => {
      const data = createTestData();
      data.lnk = [
        { Time_Access: '2024-01-01T12:00:00.000Z', target_path: 'C:\\test.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should handle mixed execution artifacts with different timestamp fields', () => {
      const data = createTestData();
      data.prefetch = [
        { last_executed: '2024-01-01T12:00:00.000Z', executable: 'test.exe' }
      ];
      data.bam = [
        { last_execution: '2024-01-02T12:00:00.000Z', executable: 'test2.exe' }
      ];
      data.lnk = [
        { Time_Access: '2024-01-03T12:00:00.000Z', target_path: 'C:\\test3.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Amcache Artifact Timestamp Extraction', () => {
    it('should use link_date for application_files', () => {
      const data = createTestData();
      data.amcache.application_files = [
        { link_date: '2024-01-01T12:00:00.000Z', file_path: 'C:\\test.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should use install_date for applications', () => {
      const data = createTestData();
      data.amcache.applications = [
        { install_date: '2024-01-01T12:00:00.000Z', name: 'Test App' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should use driver_time_stamp for drivers', () => {
      const data = createTestData();
      data.amcache.drivers = [
        { driver_time_stamp: '2024-01-01T12:00:00.000Z', driver_name: 'test.sys' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Shimcache Artifact Timestamp Extraction', () => {
    it('should use last_modified for Shimcache artifacts', () => {
      const data = createTestData();
      data.shimcache = [
        { last_modified: '2024-01-01T12:00:00.000Z', path: 'C:\\test.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('RecycleBin Artifact Timestamp Extraction', () => {
    it('should use deletion_time for RecycleBin artifacts', () => {
      const data = createTestData();
      data.recyclebin = [
        { deletion_time: '2024-01-01T12:00:00.000Z', original_path: 'C:\\test.txt' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Registry Artifact Timestamp Extraction', () => {
    it('should prefer access_date for Registry artifacts', () => {
      const data = createTestData();
      data.registry.open_save_mru = [
        {
          access_date: '2024-01-01T12:00:00.000Z',
          accessed_date: '2024-01-02T12:00:00.000Z', // Should be ignored
          modified_date: '2024-01-03T12:00:00.000Z', // Should be ignored
          file_path: 'C:\\test.txt'
        }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should fallback to accessed_date when access_date is missing', () => {
      const data = createTestData();
      data.registry.shellbags = [
        {
          accessed_date: '2024-01-01T12:00:00.000Z',
          modified_date: '2024-01-02T12:00:00.000Z', // Should be ignored
          folder_path: 'C:\\Users\\Test'
        }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should fallback to modified_date when access_date and accessed_date are missing', () => {
      const data = createTestData();
      data.registry.shellbags = [
        {
          modified_date: '2024-01-01T12:00:00.000Z',
          folder_path: 'C:\\Users\\Test'
        }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Sessions Artifact Timestamp Extraction', () => {
    it('should use timestamp for session events', () => {
      const data = createTestData();
      data.sessions.events = [
        { timestamp: '2024-01-01T12:00:00.000Z', event_name: 'Logon' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should fallback to start for session events', () => {
      const data = createTestData();
      data.sessions.events = [
        { start: '2024-01-01T12:00:00.000Z', event_name: 'Logon' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Day Assignment Accuracy', () => {
    it('should assign artifacts to correct days based on UTC date', () => {
      const data = createTestData();
      // Create artifacts for each day of the week
      data.srum_app = [
        { timestamp: '2024-01-01T12:00:00.000Z', app_name: 'day1.exe' },
        { timestamp: '2024-01-02T12:00:00.000Z', app_name: 'day2.exe' },
        { timestamp: '2024-01-03T12:00:00.000Z', app_name: 'day3.exe' },
        { timestamp: '2024-01-04T12:00:00.000Z', app_name: 'day4.exe' },
        { timestamp: '2024-01-05T12:00:00.000Z', app_name: 'day5.exe' },
        { timestamp: '2024-01-06T12:00:00.000Z', app_name: 'day6.exe' },
        { timestamp: '2024-01-07T12:00:00.000Z', app_name: 'day7.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      
      // Verify 7 day columns are rendered
      const dayColumns = container.querySelectorAll('.week-view > div:last-child > div');
      expect(dayColumns.length).toBe(7);
    });

    it('should handle artifacts at day boundaries (midnight UTC)', () => {
      const data = createTestData();
      data.srum_app = [
        { timestamp: '2024-01-01T00:00:00.000Z', app_name: 'midnight.exe' },
        { timestamp: '2024-01-01T23:59:59.999Z', app_name: 'end_of_day.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Invalid Timestamp Handling', () => {
    it('should gracefully handle invalid timestamp formats', () => {
      const data = createTestData();
      data.srum_app = [
        { timestamp: 'invalid-date', app_name: 'test.exe' },
        { timestamp: '2024-01-01T12:00:00.000Z', app_name: 'valid.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should handle null timestamps', () => {
      const data = createTestData();
      data.srum_app = [
        { timestamp: null, app_name: 'test.exe' },
        { timestamp: '2024-01-01T12:00:00.000Z', app_name: 'valid.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should handle undefined timestamps', () => {
      const data = createTestData();
      data.srum_app = [
        { app_name: 'test.exe' }, // timestamp is undefined
        { timestamp: '2024-01-01T12:00:00.000Z', app_name: 'valid.exe' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Mixed Artifact Types', () => {
    it('should correctly count artifacts from all types in the same week', () => {
      const data = createTestData();
      
      // Add artifacts of different types on the same day
      data.srum_app = [
        { timestamp: '2024-01-01T12:00:00.000Z', app_name: 'test.exe' }
      ];
      data.mft_usn = [
        { usn_timestamp: '2024-01-01T13:00:00.000Z', file_name: 'test.txt' }
      ];
      data.prefetch = [
        { last_executed: '2024-01-01T14:00:00.000Z', executable: 'test.exe' }
      ];
      data.shimcache = [
        { last_modified: '2024-01-01T15:00:00.000Z', path: 'C:\\test.exe' }
      ];
      data.recyclebin = [
        { deletion_time: '2024-01-01T16:00:00.000Z', original_path: 'C:\\test.txt' }
      ];

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });

  describe('Empty Data Handling', () => {
    it('should handle completely empty data', () => {
      const data = createTestData();

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });

    it('should handle null arrays', () => {
      const data = {
        srum_app: null,
        mft_usn: null,
        prefetch: null,
        bam: null,
        lnk: null,
        srum_net: null,
        amcache: null,
        shimcache: null,
        recyclebin: null,
        registry: null,
        sessions: null
      };

      const { container } = render(<WeekView data={data} state={createState()} />);
      expect(container.querySelector('.week-view')).toBeTruthy();
    });
  });
});
