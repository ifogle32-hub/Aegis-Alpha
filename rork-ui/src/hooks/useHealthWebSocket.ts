/**
 * Health WebSocket Hook - Real-Time Health Streaming
 * 
 * PHASE 6 — RORK REAL-TIME CONSUMPTION
 * 
 * Connects to WS /ws/health for real-time health updates
 * Replaces polling for /health endpoint
 * 
 * Behavior:
 * - On app load: Connect to WS /ws/health
 * - On message: Update engine badge, heartbeat age, loop tick display
 * - On disconnect: Show "Reconnecting..." and fall back to last known state
 * 
 * DO NOT:
 * - Send messages upstream
 * - Attempt control commands
 * - Assume LIVE trading
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { HealthSnapshot } from '../types/api';
import { apiClient } from '../services/apiClient';

interface UseHealthWebSocketReturn {
  health: HealthSnapshot | null;
  isConnected: boolean;
  isReconnecting: boolean;
  error: string | null;
  reconnect: () => void;
}

/**
 * Hook for WebSocket health streaming
 */
export function useHealthWebSocket(baseUrl: string = 'http://127.0.0.1:8000'): UseHealthWebSocketReturn {
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [isReconnecting, setIsReconnecting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastHealthRef = useRef<HealthSnapshot | null>(null);
  
  // Convert HTTP URL to WebSocket URL
  const getWebSocketUrl = useCallback((httpUrl: string): string => {
    const url = new URL(httpUrl);
    const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProtocol}//${url.host}/ws/health`;
  }, []);
  
  /**
   * Connect to WebSocket health endpoint
   */
  const connect = useCallback(() => {
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
    
    try {
      const wsUrl = getWebSocketUrl(baseUrl);
      console.log('[HealthWS] Connecting to:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      
      ws.onopen = () => {
        console.log('[HealthWS] Connected');
        setIsConnected(true);
        setIsReconnecting(false);
        setError(null);
      };
      
      ws.onmessage = (event) => {
        try {
          // SAFETY: Ignore ping messages
          if (event.data === '{"type":"ping"}') {
            return;
          }
          
          const data = JSON.parse(event.data);
          
          // Validate health snapshot shape
          if (data.status && data.mode && typeof data.loop_tick === 'number') {
            const healthSnapshot: HealthSnapshot = {
              status: data.status,
              mode: data.mode,
              loop_phase: data.loop_phase || 'UNKNOWN',
              loop_tick: data.loop_tick || 0,
              loop_tick_age: data.loop_tick_age || 999.9,
              heartbeat_age: data.heartbeat_age || 999.9,
              broker: data.broker || 'NONE',
              watchdog: data.watchdog || 'FROZEN',
              timestamp: data.timestamp || Date.now(),
            };
            
            setHealth(healthSnapshot);
            lastHealthRef.current = healthSnapshot;
            console.log('[HealthWS] Received health update:', healthSnapshot);
          }
        } catch (err) {
          console.error('[HealthWS] Error parsing message:', err);
          setError('Failed to parse health data');
        }
      };
      
      ws.onerror = (event) => {
        console.error('[HealthWS] WebSocket error:', event);
        setError('WebSocket connection error');
        setIsConnected(false);
      };
      
      ws.onclose = (event) => {
        console.log('[HealthWS] Disconnected:', event.code, event.reason);
        setIsConnected(false);
        wsRef.current = null;
        
        // Auto-reconnect after 2 seconds
        // SAFETY: Do not show "Reconnecting..." immediately - wait for first reconnect attempt
        if (event.code !== 1000) { // Not a normal closure
          setIsReconnecting(true);
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, 2000);
        }
      };
      
    } catch (err) {
      console.error('[HealthWS] Connection error:', err);
      setError('Failed to connect to WebSocket');
      setIsConnected(false);
      
      // Try to reconnect after delay
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, 2000);
    }
  }, [baseUrl, getWebSocketUrl]);
  
  /**
   * Manual reconnect
   */
  const reconnect = useCallback(() => {
    setIsReconnecting(true);
    connect();
  }, [connect]);
  
  /**
   * Connect on mount, cleanup on unmount
   */
  useEffect(() => {
    connect();
    
    return () => {
      // Cleanup on unmount
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
  
  // Return last known health if disconnected (fallback)
  return {
    health: health || lastHealthRef.current,
    isConnected,
    isReconnecting,
    error,
    reconnect,
  };
}
