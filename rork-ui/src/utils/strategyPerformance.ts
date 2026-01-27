/**
 * Strategy Performance Normalization Utilities
 * 
 * PHASE 5 — MOBILE CHART NORMALIZATION
 * 
 * REGRESSION LOCK — mobile charts are read-only
 * REGRESSION LOCK — no persistence
 */

/**
 * Normalize timeseries data from backend format to chart-ready format.
 * 
 * Backend format: [[timestamp, pnl_total], ...]  (Unix timestamp in seconds)
 * Chart format: [{ x: Date, y: number }, ...]
 * 
 * SAFETY:
 * - Handles empty/missing series gracefully (returns empty array)
 * - Handles invalid data gracefully (skips invalid points)
 * - Never raises errors
 * 
 * @param series - Timeseries array from backend: [[timestamp, pnl_total], ...]
 * @returns Normalized array: [{ x: Date, y: number }, ...]
 */
export function normalizeTimeseries(
  series?: [number, number][]
): Array<{ x: Date; y: number }> {
  // PHASE 8: Handle missing/empty series gracefully
  if (!Array.isArray(series)) {
    return [];
  }
  
  // PHASE 8: Filter and normalize valid data points
  return series
    .filter((point) => {
      // Validate point structure
      if (!Array.isArray(point) || point.length < 2) {
        return false;
      }
      
      const [ts, pnl] = point;
      
      // Validate timestamp (must be a number and reasonable Unix timestamp)
      if (typeof ts !== 'number' || ts <= 0 || ts > Date.now() / 1000 + 86400) {
        return false;
      }
      
      // Validate PnL (must be a number, NaN/infinity filtered)
      if (typeof pnl !== 'number' || !isFinite(pnl)) {
        return false;
      }
      
      return true;
    })
    .map(([ts, pnl]) => ({
      x: new Date(ts * 1000), // Convert Unix timestamp (seconds) to Date
      y: pnl,
    }));
}

/**
 * Get latest PnL value from normalized timeseries.
 * 
 * @param normalizedSeries - Normalized timeseries array
 * @returns Latest PnL value or 0 if empty
 */
export function getLatestPnl(
  normalizedSeries: Array<{ x: Date; y: number }>
): number {
  if (!normalizedSeries || normalizedSeries.length === 0) {
    return 0;
  }
  
  return normalizedSeries[normalizedSeries.length - 1].y;
}

/**
 * Calculate min/max values from normalized timeseries for chart scaling.
 * 
 * @param normalizedSeries - Normalized timeseries array
 * @returns Object with min and max values, or null if empty
 */
export function getChartBounds(
  normalizedSeries: Array<{ x: Date; y: number }>
): { min: number; max: number } | null {
  if (!normalizedSeries || normalizedSeries.length === 0) {
    return null;
  }
  
  const values = normalizedSeries.map((point) => point.y);
  const min = Math.min(...values);
  const max = Math.max(...values);
  
  // Add padding for better visualization
  const padding = Math.max(Math.abs(max - min) * 0.1, 1);
  
  return {
    min: min - padding,
    max: max + padding,
  };
}
