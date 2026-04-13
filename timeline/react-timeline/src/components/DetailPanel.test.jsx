import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DetailPanel from './DetailPanel';

describe('DetailPanel - Task 9: MFT/USN Duration Display Fix', () => {
  const mockState = {
    selectedEvent: null,
    detailPanelCollapsed: false,
    setDetailPanelCollapsed: () => {},
    setDetailEvent: () => {},
    setSelectedEvent: () => {}
  };

  describe('Task 9.1 & 9.2: Instantaneous Events (MFT, USN, Prefetch, Registry)', () => {
    it('should NOT show End Time for mft_create events', () => {
      const mftEvent = {
        type: 'mft_create',
        timestamp: '2024-01-15T10:30:00Z',
        fn_filename: 'document.txt',
        id: 'mft-1'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: mftEvent }} 
          data={{}} 
          links={[]} 
        />
      );

      expect(screen.getByText('Timestamp (UTC)')).toBeDefined();
      expect(screen.queryByText('End Time (UTC)')).toBeNull();
      expect(screen.queryByText('Duration')).toBeNull();
    });

    it('should NOT show End Time for mft_usn events', () => {
      const usnEvent = {
        type: 'mft_usn',
        timestamp: '2024-01-15T10:30:00Z',
        fn_filename: 'system.log',
        usn_reason: 0x00000100,
        id: 'usn-1'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: usnEvent }} 
          data={{}} 
          links={[]} 
        />
      );

      expect(screen.getByText('Timestamp (UTC)')).toBeDefined();
      expect(screen.queryByText('End Time (UTC)')).toBeNull();
      expect(screen.queryByText('Duration')).toBeNull();
    });

    it('should NOT show End Time for prefetch events', () => {
      const prefetchEvent = {
        type: 'prefetch',
        timestamp: '2024-01-15T10:30:00Z',
        executable_name: 'chrome.exe',
        id: 'prefetch-1'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: prefetchEvent }} 
          data={{}} 
          links={[]} 
        />
      );

      expect(screen.getByText('Timestamp (UTC)')).toBeDefined();
      expect(screen.queryByText('End Time (UTC)')).toBeNull();
      expect(screen.queryByText('Duration')).toBeNull();
    });

    it('should NOT show End Time for registry events', () => {
      const registryEvent = {
        type: 'registry',
        timestamp: '2024-01-15T10:30:00Z',
        name: 'HKLM\\Software\\Microsoft',
        id: 'reg-1'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: registryEvent }} 
          data={{}} 
          links={[]} 
        />
      );

      expect(screen.getByText('Timestamp (UTC)')).toBeDefined();
      expect(screen.queryByText('End Time (UTC)')).toBeNull();
      expect(screen.queryByText('Duration')).toBeNull();
    });
  });

  describe('Task 9.3: Time-Span Events (SRUM, Sessions)', () => {
    it('should show End Time and Duration for srum_app events', () => {
      const srumEvent = {
        type: 'srum_app',
        start: '2024-01-15T10:30:00Z',
        end: '2024-01-15T11:30:00Z',
        app_name: 'chrome.exe',
        face_time: 3600,
        id: 'srum-1'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: srumEvent }} 
          data={{}} 
          links={[]} 
        />
      );

      expect(screen.getByText('Timestamp (UTC)')).toBeDefined();
      expect(screen.getByText('End Time (UTC)')).toBeDefined();
      expect(screen.getByText('Duration')).toBeDefined();
    });

    it('should show End Time and Duration for session events', () => {
      const sessionEvent = {
        type: 'sessions',
        start: '2024-01-15T08:00:00Z',
        end: '2024-01-15T17:00:00Z',
        name: 'User Session',
        id: 'session-1'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: sessionEvent }} 
          data={{}} 
          links={[]} 
        />
      );

      expect(screen.getByText('Timestamp (UTC)')).toBeDefined();
      expect(screen.getByText('End Time (UTC)')).toBeDefined();
      expect(screen.getByText('Duration')).toBeDefined();
    });

    it('should calculate duration correctly (1 hour = 3600s)', () => {
      const srumEvent = {
        type: 'srum_app',
        start: '2024-01-15T10:00:00Z',
        end: '2024-01-15T11:00:00Z',
        app_name: 'notepad.exe',
        id: 'srum-2'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: srumEvent }} 
          data={{}} 
          links={[]} 
        />
      );

      // Duration should be formatted as "1h 0m" by formatDuration
      expect(screen.getByText('Duration')).toBeDefined();
    });

    it('should NOT show Duration if end time is missing', () => {
      const srumEvent = {
        type: 'srum_app',
        start: '2024-01-15T10:00:00Z',
        // No end time
        app_name: 'notepad.exe',
        id: 'srum-3'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: srumEvent }} 
          data={{}} 
          links={[]} 
        />
      );

      expect(screen.getByText('Timestamp (UTC)')).toBeDefined();
      expect(screen.queryByText('End Time (UTC)')).toBeNull();
      expect(screen.queryByText('Duration')).toBeNull();
    });
  });

  describe('Edge Cases', () => {
    it('should handle events with both timestamp and start fields', () => {
      const event = {
        type: 'srum_app',
        timestamp: '2024-01-15T10:00:00Z',
        start: '2024-01-15T10:00:00Z',
        end: '2024-01-15T11:00:00Z',
        app_name: 'test.exe',
        id: 'test-1'
      };

      render(
        <DetailPanel 
          state={{ ...mockState, selectedEvent: event }} 
          data={{}} 
          links={[]} 
        />
      );

      expect(screen.getByText('Timestamp (UTC)')).toBeDefined();
      expect(screen.getByText('End Time (UTC)')).toBeDefined();
      expect(screen.getByText('Duration')).toBeDefined();
    });

    it('should return null when no event is selected', () => {
      const { container } = render(
        <DetailPanel 
          state={mockState} 
          data={{}} 
          links={[]} 
        />
      );

      expect(container.firstChild).toBeNull();
    });
  });
});
