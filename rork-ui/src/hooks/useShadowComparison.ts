/**
 * Shadow vs Live Comparison Hook
 * 
 * OBSERVATIONAL ONLY - Read-only access to shadow comparison data.
 * UI must NEVER influence execution.
 * 
 * Connects to WebSocket /ws/shadow-vs-live for real-time streaming.
 * Falls back to REST /shadow/comparison on WebSocket failure.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Platform } from 'react-native';
import { apiClient, APIError } from '../services/apiClient';

interface ShadowComparisonData {
  strategy_deltas: Record<string, {
    shadow_pnl: number;
    execution_pnl: number;
    pnl_delta: number;
  }>;
  aggregate_shadow_pnl: number;
  aggregate_execution_pnl: number;
  aggregate_pnl_delta: number;
  slippage: {
    avg: number;
    max: number;
    count: number;
  };
  execution_latency: {
    avg_ms: number;
    max_ms: number;
    count: number;
  };
  divergence_alerts_count: number;
  timestamp: string;
}

interface UseShadowComparisonReturn {
  data: ShadowComparisonData | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const POLL_INTERVAL = Platform.OS === 'web' ? 1000 : 2000; // 1s desktop, 2s mobile

/**
 * Hook for shadow vs live comparison with WebSocket streaming.
 * 
 * Falls back to polling if WebSocket unavailable.
 */
export function useShadowComparison(): UseShadowComparisonReturn {
  const [data, setData] = useState<ShadowComparisonData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  
  const websocketRef = useRef<WebSocket | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  /**
   * Fetch comparison data via REST API (fallback)
   */
  const fetchComparison = useCallback(async () => {
    try {
      const response = await apiClient.getShadowComparison();
      setData(response);
      setError(null);
    } catch (err) {
      const apiError = err as APIError;
      console.error('[ShadowComparison] Error:', apiError.message);
      setError(apiError.message);
      // Keep last known data on error
    }
  }, []);

  /**
   * Setup WebSocket connection for real-time streaming
   */
  const connectWebSocket = useCallback(() => {
    try {
      // Determine WebSocket URL
      const wsProtocol = Platform.OS === 'web' 
        ? (window.location.protocol === 'https:' ? 'wss:' : 'ws:')
        : 'ws:';
      const wsHost = Platform.OS === 'web'
        ? window.location.host
        : '127.0.0.1:8000';
      const wsUrl = `${wsProtocol}//${wsHost}/ws/shadow-vs-live`;

      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[ShadowComparison] WebSocket connected');
        setError(null);
        // Clear polling if WebSocket successful
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
      };

      ws.onmessage = (event) => {
        try {
          const comparisonData = JSON.parse(event.data) as ShadowComparisonData;
          setData(comparisonData);
          setError(null);
        } catch (err) {
          console.error('[ShadowComparison] Error parsing WebSocket message:', err);
        }
      };

      ws.onerror = (err) => {
        console.error('[ShadowComparison] WebSocket error:', err);
        // Fallback to polling on WebSocket error
        if (!pollIntervalRef.current) {
          pollIntervalRef.current = setInterval(fetchComparison, POLL_INTERVAL);
        }
      };

      ws.onclose = () => {
        console.log('[ShadowComparison] WebSocket disconnected');
        websocketRef.current = null;
        
        // Attempt reconnection after delay
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        reconnectTimeoutRef.current = setTimeout(() => {
          connectWebSocket();
        }, 5000); // Reconnect after 5s
        
        // Fallback to polling
        if (!pollIntervalRef.current) {
          pollIntervalRef.current = setInterval(fetchComparison, POLL_INTERVAL);
        }
      };

      websocketRef.current = ws;
    } catch (err) {
      console.error('[ShadowComparison] Error setting up WebSocket:', err);
      // Fallback to polling
      if (!pollIntervalRef.current) {
        pollIntervalRef.current = setInterval(fetchComparison, POLL_INTERVAL);
      }
    }
  }, [fetchComparison]);

  /**
   * Manual refresh (forces REST fetch)
   */
  const refresh = useCallback(async () => {
    setIsLoading(true);
    await fetchComparison();
    setIsLoading(false);
  }, [fetchComparison]);

  /**
   * Setup connection on mount
   */
  useEffect(() => {
    // Try WebSocket first (desktop/web)
    if (Platform.OS === 'web') {
      connectWebSocket();
    } else {
      // Mobile: fallback to polling (WebSocket can be unreliable)
      pollIntervalRef.current = setInterval(fetchComparison, POLL_INTERVAL);
      fetchComparison(); // Initial fetch
    }

    // Cleanup
    return () => {
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };
  }, [connectWebSocket, fetchComparison]);

  return {
    data,
    isLoading,
    error,
    refresh,
  };
}
