/**
 * Risk and Funding Hooks - PHASE 3-4
 * 
 * Fetches risk and funding data from GET /risk and GET /funding endpoints.
 * PHASE 4: Never crashes on missing fields - uses placeholders.
 * PHASE 7: Read-only display - no trading controls exposed.
 */

import { useState, useEffect, useCallback } from 'react';
import { apiClient, APIError } from '../services/apiClient';
import { RiskResponse, FundingResponse } from '../types/api';

interface UseRiskReturn {
  risk: RiskResponse | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

interface UseFundingReturn {
  funding: FundingResponse | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Hook for fetching risk data
 * PHASE 7: Read-only - no trading controls
 */
export function useRisk(): UseRiskReturn {
  const [risk, setRisk] = useState<RiskResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRisk = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await apiClient.getRisk();
      
      // PHASE 6: Handle missing fields gracefully
      const normalized: RiskResponse = {
        max_drawdown: response.max_drawdown ?? 'server_managed',
        max_daily_loss: response.max_daily_loss ?? 'server_managed',
        risk_state: response.risk_state ?? 'NORMAL',
        timestamp: response.timestamp,
      };
      
      setRisk(normalized);
      setError(null);
    } catch (err) {
      const apiError = err as APIError;
      console.error('[Risk] Error:', apiError.message);
      
      // PHASE 6: Never crash - use defaults
      setError(apiError.message);
      setRisk({
        max_drawdown: 'server_managed',
        max_daily_loss: 'server_managed',
        risk_state: 'NORMAL',
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await fetchRisk();
  }, [fetchRisk]);

  useEffect(() => {
    fetchRisk();
    // Poll every 30 seconds (risk limits don't change often)
    const pollInterval = setInterval(fetchRisk, 30000);
    return () => clearInterval(pollInterval);
  }, [fetchRisk]);

  return {
    risk,
    isLoading,
    error,
    refresh,
  };
}

/**
 * Hook for fetching funding data
 * PHASE 2: Funding-only actions (read-only display + requests)
 */
export function useFunding(): UseFundingReturn {
  const [funding, setFunding] = useState<FundingResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchFunding = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await apiClient.getFunding();
      
      // PHASE 6: Handle missing fields gracefully
      const normalized: FundingResponse = {
        current_equity: response.current_equity ?? null,
        can_add_funds: response.can_add_funds ?? false,
        can_withdraw: response.can_withdraw ?? false,
        cooldown_active: response.cooldown_active ?? false,
        timestamp: response.timestamp,
      };
      
      setFunding(normalized);
      setError(null);
    } catch (err) {
      const apiError = err as APIError;
      console.error('[Funding] Error:', apiError.message);
      
      // PHASE 6: Never crash - use defaults
      setError(apiError.message);
      setFunding({
        current_equity: null,
        can_add_funds: false,
        can_withdraw: false,
        cooldown_active: false,
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await fetchFunding();
  }, [fetchFunding]);

  useEffect(() => {
    fetchFunding();
    // Poll every 10 seconds (funding status may change)
    const pollInterval = setInterval(fetchFunding, 10000);
    return () => clearInterval(pollInterval);
  }, [fetchFunding]);

  return {
    funding,
    isLoading,
    error,
    refresh,
  };
}
