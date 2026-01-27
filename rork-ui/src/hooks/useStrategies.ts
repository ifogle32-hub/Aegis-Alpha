/**
 * Strategies Hook - PHASE 3-4
 * 
 * Fetches strategy list from GET /strategies endpoint.
 * PHASE 4: Never crashes on missing fields - uses placeholders.
 */

import { useState, useEffect, useCallback } from 'react';
import { apiClient, APIError } from '../services/apiClient';
import { StrategyView } from '../types/api';

interface UseStrategiesReturn {
  strategies: StrategyView[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Hook for fetching strategies list
 */
export function useStrategies(): UseStrategiesReturn {
  const [strategies, setStrategies] = useState<StrategyView[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * PHASE 3-6: Fetch strategies from /strategies endpoint
   * PHASE 6: Never crash on missing fields - treat missing as defaults
   */
  const fetchStrategies = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await apiClient.getStrategies();
      
      // PHASE 6: Handle both array and wrapped responses gracefully
      let strategiesList: StrategyView[] = [];
      if (Array.isArray(response)) {
        strategiesList = response;
      } else if (response && typeof response === 'object' && 'strategies' in response) {
        strategiesList = (response as any).strategies || [];
      }
      
      // PHASE 6: Normalize strategies (handle missing fields)
      const normalized: StrategyView[] = strategiesList.map((s: any) => ({
        id: s.id || s.name || 'unknown',
        status: (s.status || 'INACTIVE').toUpperCase() as 'ACTIVE' | 'INACTIVE' | 'DISABLED',
        pnl: typeof s.pnl === 'number' ? s.pnl : null,
        win_rate: typeof s.win_rate === 'number' ? s.win_rate : null,
        last_tick: typeof s.last_tick === 'number' ? s.last_tick : 0,
      }));
      
      setStrategies(normalized);
      setError(null);
    } catch (err) {
      const apiError = err as APIError;
      console.error('[Strategies] Error:', apiError.message);
      
      // PHASE 6: Never crash - keep empty list on error
      setError(apiError.message);
      // Don't reset strategies - keep last known list
    } finally {
      setIsLoading(false);
    }
  }, []);

  /**
   * Manual refresh
   */
  const refresh = useCallback(async () => {
    await fetchStrategies();
  }, [fetchStrategies]);

  /**
   * Setup polling (slower than metrics - strategies don't change often)
   */
  useEffect(() => {
    // Initial fetch
    fetchStrategies();
    
    // Poll every 10 seconds (strategies don't change frequently)
    const pollInterval = setInterval(fetchStrategies, 10000);
    
    return () => clearInterval(pollInterval);
  }, [fetchStrategies]);

  return {
    strategies,
    isLoading,
    error,
    refresh,
  };
}
