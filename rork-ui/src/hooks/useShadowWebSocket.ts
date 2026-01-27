/**
 * Shadow WebSocket Hook - Real-Time Shadow Strategy Monitoring
 * 
 * PHASE 1 — SHADOW BACKTESTING REAL-TIME FEEDS
 * 
 * Connects to WS /shadow/ws/shadow for real-time shadow signals and metrics
 * SAFETY: SHADOW MODE ONLY - read-only, no execution
 * 
 * Behavior:
 * - On app load: Connect to WS /shadow/ws/shadow
 * - On message: Update shadow charts (PnL, signals, metrics)
 * - On disconnect: Show "Reconnecting..." and fall back to cached data
 * - iOS background: Throttle/pause WS updates
 */

import { useState, useEffect, useRef, useCallback } from 'react';

export interface ShadowSignal {
  strategy_id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  confidence: number;
  timestamp: string;
  price?: number;
}

export interface ShadowMetrics {
  strategy_id: string;
  pnl: number;
  sharpe: number;
  max_drawdown: number;
  trade_count: number;
  win_rate?: number;
  total_return?: number;
}

export interface ShadowRealtimeData {
  timestamp: string;
  signals: ShadowSignal[];
  metrics: Record<string, ShadowMetrics>;
}

interface UseShadowWebSocketReturn {
  data: ShadowRealtimeData | null;
  isConnected: boolean;
  isReconnecting: boolean;
  error: string | null;
  reconnect: () => void;
  pause: () => void;
  resume: () => void;
}

/**
 * Hook for WebSocket shadow strategy monitoring
 */
export function useShadowWebSocket(baseUrl: string = 'http://127.0.0.1:8000'): UseShadowWebSocketReturn {
  const [data, setData] = useState<ShadowRealtimeData | null>(null);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [isReconnecting, setIsReconnecting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastDataRef = useRef<ShadowRealtimeData | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const maxReconnectAttempts = 10;
  
  // Convert HTTP URL to WebSocket URL
  const getWebSocketUrl = useCallback((httpUrl: string): string => {
    const url = new URL(httpUrl);
    const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProtocol}//${url.host}/shadow/ws/shadow`;
  }, []);
  
  /**
   * Connect to WebSocket shadow endpoint
   */
  const connect = useCallback(() => {
    // Don't connect if paused
    if (isPaused) {
      return;
    }
    
    // Close existing connection if any
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    
    // Clear reconnect timeout
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    
    // Check reconnect attempts
    if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
      setError('Max reconnection attempts reached');
      setIsReconnecting(false);
      return;
    }
    
    try {
      const wsUrl = getWebSocketUrl(baseUrl);
      console.log('[ShadowWS] Connecting to:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      
      ws.onopen = () => {
        console.log('[ShadowWS] Connected');
        setIsConnected(true);
        setIsReconnecting(false);
        setError(null);
        reconnectAttemptsRef.current = 0; // Reset on successful connection
      };
      
      ws.onmessage = (event) => {
        try {
          // SAFETY: Ignore ping messages
          if (event.data === '{"type":"ping"}') {
            return;
          }
          
          const parsedData = JSON.parse(event.data);
          
          // Validate shadow data shape
          if (parsedData.timestamp && Array.isArray(parsedData.signals) && typeof parsedData.metrics === 'object') {
            const shadowData: ShadowRealtimeData = {
              timestamp: parsedData.timestamp,
              signals: parsedData.signals || [],
              metrics: parsedData.metrics || {}
            };
            
            setData(shadowData);
            lastDataRef.current = shadowData;
            console.log('[ShadowWS] Received shadow update:', shadowData);
          }
        } catch (err) {
          console.error('[ShadowWS] Error parsing message:', err);
          setError('Failed to parse shadow data');
        }
      };
      
      ws.onerror = (event) => {
        console.error('[ShadowWS] WebSocket error:', event);
        setError('WebSocket connection error');
        setIsConnected(false);
        reconnectAttemptsRef.current++;
      };
      
      ws.onclose = (event) => {
        console.log('[ShadowWS] Disconnected:', event.code, event.reason);
        setIsConnected(false);
        wsRef.current = null;
        
        // Auto-reconnect with exponential backoff (not a normal closure)
        if (event.code !== 1000 && !isPaused) {
          setIsReconnecting(true);
          const delay = Math.min(2000 * Math.pow(2, reconnectAttemptsRef.current), 30000); // Max 30s
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        }
      };
      
    } catch (err) {
      console.error('[ShadowWS] Connection error:', err);
      setError('Failed to connect to WebSocket');
      setIsConnected(false);
      reconnectAttemptsRef.current++;
      
      // Try to reconnect after delay
      if (!isPaused) {
        const delay = Math.min(2000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      }
    }
  }, [baseUrl, getWebSocketUrl, isPaused]);
  
  /**
   * Manual reconnect
   */
  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    setIsReconnecting(true);
    connect();
  }, [connect]);
  
  /**
   * Pause WebSocket (for iOS background or user action)
   */
  const pause = useCallback(() => {
    setIsPaused(true);
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);
  
  /**
   * Resume WebSocket
   */
  const resume = useCallback(() => {
    setIsPaused(false);
    reconnectAttemptsRef.current = 0;
    connect();
  }, [connect]);
  
  /**
   * Connect on mount, cleanup on unmount
   */
  useEffect(() => {
    if (!isPaused) {
      connect();
    }
    
    // Handle visibility change (iOS background)
    const handleVisibilityChange = () => {
      if (document.hidden) {
        // Pause WS when tab is hidden (iOS background)
        pause();
      } else {
        // Resume WS when tab is visible
        resume();
      }
    };
    
    document.addEventListener('visibilitychange', handleVisibilityChange);
    
    return () => {
      // Cleanup on unmount
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };
  }, [connect, pause, resume, isPaused]);
  
  // Return last known data if disconnected (fallback)
  return {
    data: data || lastDataRef.current,
    isConnected,
    isReconnecting,
    error,
    reconnect,
    pause,
    resume,
  };
}
