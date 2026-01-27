/**
 * Strategy Performance WebSocket Hook
 * 
 * PHASE 7 — MULTI-STRATEGY VIEW: WebSocket Connection
 * 
 * REGRESSION LOCK — mobile charts are read-only
 * REGRESSION LOCK — no persistence
 * 
 * Connects to /ws/strategy-performance WebSocket endpoint for real-time
 * strategy performance data including time-series PnL.
 * 
 * PHASE 8: Handles disconnections gracefully, shows last known data
 */

import { useState, useEffect, useRef, useCallback } from 'react';

interface StrategyPerformanceData {
  allocation_weight: number;
  trades: number;
  pnl_total: number;
  timeseries: [number, number][]; // [[timestamp, pnl_total], ...]
}

interface StrategyPerformancePayload {
  timestamp: number;
  strategies: Record<string, StrategyPerformanceData>;
}

interface UseStrategyPerformanceReturn {
  /**
   * Current strategy performance data
   * Keys are strategy names, values are performance data
   */
  data: Record<string, StrategyPerformanceData>;
  
  /**
   * Whether WebSocket is connected
   */
  isConnected: boolean;
  
  /**
   * Error message if connection failed (null if no error)
   */
  error: string | null;
  
  /**
   * Last update timestamp
   */
  lastUpdated: Date | null;
  
  /**
   * Manually reconnect WebSocket
   */
  reconnect: () => void;
}

// WebSocket URL configuration
// Default matches apiClient default: http://127.0.0.1:8000 -> ws://127.0.0.1:8000
const HTTP_BASE_URL = process.env.API_BASE_URL || 'http://127.0.0.1:8000';
const WS_BASE_URL = HTTP_BASE_URL.replace(/^http/, 'ws'); // Convert http -> ws, https -> wss
const WS_ENDPOINT = '/ws/strategy-performance';
const WS_FULL_URL = `${WS_BASE_URL}${WS_ENDPOINT}`;

/**
 * Hook for real-time strategy performance data via WebSocket
 */
export function useStrategyPerformance(): UseStrategyPerformanceReturn {
  const [data, setData] = useState<Record<string, StrategyPerformanceData>>({});
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const lastDataRef = useRef<Record<string, StrategyPerformanceData>>({});
  
  const MAX_RECONNECT_ATTEMPTS = 5;
  const RECONNECT_DELAY = 2000; // 2 seconds
  
  /**
   * Connect to WebSocket endpoint
   */
  const connect = useCallback(() => {
    try {
      // Clean up existing connection
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      
      // Clear reconnect timeout
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      
      console.log('[StrategyPerformance] Connecting to WebSocket:', WS_FULL_URL);
      
      const ws = new WebSocket(WS_FULL_URL);
      
      ws.onopen = () => {
        console.log('[StrategyPerformance] WebSocket connected');
        setIsConnected(true);
        setError(null);
        reconnectAttemptsRef.current = 0; // Reset reconnect attempts on success
      };
      
      ws.onmessage = (event) => {
        try {
          const payload: StrategyPerformancePayload = JSON.parse(event.data);
          
          // PHASE 8: Validate payload structure
          if (!payload || typeof payload !== 'object') {
            console.warn('[StrategyPerformance] Invalid payload format');
            return;
          }
          
          // PHASE 8: Extract strategies data (may be empty)
          const strategies = payload.strategies || {};
          
          // PHASE 8: Validate each strategy data structure
          const validatedStrategies: Record<string, StrategyPerformanceData> = {};
          for (const [name, strategyData] of Object.entries(strategies)) {
            if (
              strategyData &&
              typeof strategyData === 'object' &&
              typeof strategyData.allocation_weight === 'number' &&
              typeof strategyData.trades === 'number' &&
              typeof strategyData.pnl_total === 'number' &&
              Array.isArray(strategyData.timeseries)
            ) {
              validatedStrategies[name] = {
                allocation_weight: strategyData.allocation_weight,
                trades: strategyData.trades,
                pnl_total: strategyData.pnl_total,
                timeseries: strategyData.timeseries, // May be empty array
              };
            } else {
              console.warn(`[StrategyPerformance] Invalid strategy data for ${name}`);
            }
          }
          
          // PHASE 8: Update state only if data changed (prevent unnecessary re-renders)
          if (JSON.stringify(validatedStrategies) !== JSON.stringify(lastDataRef.current)) {
            setData(validatedStrategies);
            lastDataRef.current = validatedStrategies;
            setLastUpdated(new Date());
            console.log('[StrategyPerformance] Data updated:', Object.keys(validatedStrategies).length, 'strategies');
          }
        } catch (err) {
          console.error('[StrategyPerformance] Error parsing WebSocket message:', err);
          // PHASE 8: Don't update error state on parse error - keep last known data
        }
      };
      
      ws.onerror = (event) => {
        console.error('[StrategyPerformance] WebSocket error:', event);
        setError('WebSocket connection error');
        setIsConnected(false);
      };
      
      ws.onclose = (event) => {
        console.log('[StrategyPerformance] WebSocket closed:', event.code, event.reason);
        setIsConnected(false);
        wsRef.current = null;
        
        // PHASE 8: Attempt reconnection if not manually closed
        if (event.code !== 1000 && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current += 1;
          console.log(`[StrategyPerformance] Attempting reconnect (${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})...`);
          
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, RECONNECT_DELAY);
        } else if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
          setError('Failed to reconnect after multiple attempts');
          console.error('[StrategyPerformance] Max reconnect attempts reached');
        }
      };
      
      wsRef.current = ws;
    } catch (err) {
      console.error('[StrategyPerformance] Error creating WebSocket:', err);
      setError('Failed to create WebSocket connection');
      setIsConnected(false);
    }
  }, []);
  
  /**
   * Manual reconnect
   */
  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0; // Reset attempts
    connect();
  }, [connect]);
  
  /**
   * Setup WebSocket connection on mount
   */
  useEffect(() => {
    connect();
    
    // Cleanup on unmount
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };
  }, [connect]);
  
  return {
    data,
    isConnected,
    error,
    lastUpdated,
    reconnect,
  };
}
