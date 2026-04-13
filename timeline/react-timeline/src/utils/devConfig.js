/**
 * Configuration for Development / Testing.
 * Useful for automating data testing without manual clicks.
 */
export const DEV_CONFIG = {
    /** 
     * Auto-jump to a specific date 1.5 seconds after loading finishes. 
     * Set to null to disable.
     */
    AUTO_TEST_TARGET_DATE: '2026-02-28',
    
    /** Range in days to fetch around the target date */
    AUTO_TEST_RADIUS_DAYS: 1,
    
    /** Print extra debug logs in the console */
    DEBUG_LOGGING: true,
  };
  
