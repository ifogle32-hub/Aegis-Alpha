/**
 * Live Metrics Hook - PHASE 4
 * 
 * Polls multiple endpoints to aggregate live metrics:
 * - Equity (from /account)
 * - PnL (from /positions)
 * - Open positions count (from /positions)
 * - Active strategies count (from /strategies)
 * - Engine uptime (from /status)
 * - Current mode (from /status)
 * 
 * Polling intervals:
 * - Desktop: 1s
 * - Mobile: 2-3s adaptive
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Platform } from 'react-native';
import { apiClient, APIError } from '../services/apiClient';
import { LiveMetrics } from '../types/api';

// Polling configuration
const POLL_INTERVAL_DESKTOP = 1000; // 1 second
const POLL_INTERVAL_MOBILE_MIN = 2000; // 2 seconds
const POLL_INTERVAL_MOBILE_MAX = 3000; // 3 seconds (adaptive)
const POLL_INTERVAL = Platform.OS === 'web' ? POLL_INTERVAL_DESKTOP : POLL_INTERVAL_MOBILE_MIN;

interface UseLiveMetricsReturn {
  metrics: LiveMetrics;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Hook for live metrics with adaptive polling
 */
export function useLiveMetrics(): UseLiveMetricsReturn {
  const [metrics, setMetrics] = useState<LiveMetrics>({
    equity: null,
    totalPnL: 0,
    openPositionsCount: 0,
    activeStrategiesCount: 0,
    engineUptime: 0,
    currentMode: 'UNKNOWN',
    lastUpdated: null,
  });
  
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastMetricsRef = useRef<LiveMetrics | null>(null);

  /**
   * PHASE 3-6: Fetch metrics from canonical /metrics endpoint
   * PHASE 6: Never crash on missing fields - use placeholders
   */
  const fetchMetrics = useCallback(async () => {
    try {
      // PHASE 3: Fetch from canonical /metrics endpoint
      const metricsResponse = await apiClient.getMetrics().catch(() => null);
      
      // PHASE 3: Also fetch strategies for active count
      const strategiesResponse = await apiClient.getStrategies().catch(() => null);
      
      // PHASE 3: Also fetch positions for open positions count
      const positionsResponse = await apiClient.getPositions().catch(() => null);
      
      // PHASE 3: Fetch status for uptime and mode (fallback)
      const statusResponse = await apiClient.getStatus().catch(() => null);

      // PHASE 6: Aggregate metrics with safe defaults (never crash on missing fields)
      const newMetrics: LiveMetrics = {
        equity: metricsResponse?.equity ?? null,
        totalPnL: metricsResponse?.daily_pnl ?? positionsResponse?.total_pnl ?? 0,
        openPositionsCount: positionsResponse?.count ?? 0,
        activeStrategiesCount: Array.isArray(strategiesResponse) 
          ? strategiesResponse.filter((s: any) => s.status === 'ACTIVE').length 
          : (strategiesResponse?.count ?? 0),
        engineUptime: metricsResponse?.uptime_seconds ?? statusResponse?.uptime ?? 0,
        currentMode: statusResponse?.mode ?? 'UNKNOWN',
        lastUpdated: new Date(),
      };

      // Only update if data changed (prevents unnecessary re-renders)
      if (
        !lastMetricsRef.current ||
        JSON.stringify(newMetrics) !== JSON.stringify(lastMetricsRef.current)
      ) {
        setMetrics(newMetrics);
        lastMetricsRef.current = newMetrics;
      }

      setError(null);
      
      console.log('[Metrics] Updated:', {
        equity: newMetrics.equity,
        totalPnL: newMetrics.totalPnL,
        positions: newMetrics.openPositionsCount,
        strategies: newMetrics.activeStrategiesCount,
        uptime: newMetrics.engineUptime,
        mode: newMetrics.currentMode,
      });
    } catch (err) {
      const apiError = err as APIError;
      console.error('[Metrics] Error:', apiError.message);
      
      // PHASE 6: Keep last known metrics on error (never crash UI)
      setError(apiError.message);
      
      // On network error, keep last snapshot (don't reset)
      if (apiError.isNetworkError && lastMetricsRef.current) {
        // Metrics remain from last successful poll
        return;
      }
    }
  }, []);

  /**
   * Manual refresh
   */
  const refresh = useCallback(async () => {
    setIsLoading(true);
    await fetchMetrics();
    setIsLoading(false);
  }, [fetchMetrics]);

  /**
   * Setup polling with adaptive intervals
   */
  useEffect(() => {
    // Initial fetch
    fetchMetrics();

    // Adaptive polling for mobile: increase interval if network is slow
    let currentInterval = POLL_INTERVAL;
    let consecutiveErrors = 0;

    const poll = async () => {
      try {
        await fetchMetrics();
        consecutiveErrors = 0;
        // Reset to base interval on success
        currentInterval = POLL_INTERVAL;
      } catch (err) {
        consecutiveErrors++;
        // Adaptive backoff: increase interval on consecutive errors (mobile only)
        if (Platform.OS !== 'web' && consecutiveErrors > 3) {
          currentInterval = Math.min(
            currentInterval * 1.5,
            POLL_INTERVAL_MOBILE_MAX
          );
        }
      }
    };

    // Setup polling interval
    pollIntervalRef.current = setInterval(poll, POLL_INTERVAL);

    // Cleanup
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [fetchMetrics]);

  return {
    metrics,
    isLoading,
    error,
    refresh,
  };
}

