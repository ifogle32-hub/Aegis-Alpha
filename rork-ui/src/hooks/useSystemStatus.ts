/**
 * System Status Hook - Mobile Hardened
 * 
 * PHASE 1: Mobile debounce (critical)
 * PHASE 2: Latency smoothing (optimistic UI)
 * PHASE 3: Status stability guards
 * PHASE 4: Auth state integration
 * PHASE 5: Status refresh loop
 * PHASE 6: Network resilience
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { MutableRefObject } from 'react';
import { Platform } from 'react-native';
import { BotState, UIState, SystemState } from '../types/api';
import { apiClient, APIError } from '../services/apiClient';
import { parseStatusResponse, parseHealthResponse } from '../utils/stateNormalizer';
import { debounceManager, ActionType, DEBOUNCE_CONFIG } from '../utils/debounce';
import { AuthUIState, initializeAuthStorage } from '../utils/authStorage';
import { biometricAuth } from '../services/biometricAuth';

// Polling configuration - 1s desktop, 2s mobile
const POLL_INTERVAL_DESKTOP = 1000; // 1 second
const POLL_INTERVAL_MOBILE = 2000; // 2 seconds
// Detect desktop (web) vs mobile (ios/android)
const POLL_INTERVAL = Platform.OS === 'web' ? POLL_INTERVAL_DESKTOP : POLL_INTERVAL_MOBILE;
const ACTION_TIMEOUT = 5000; // 5 seconds max for any action

/**
 * Extended system status with debounce and auth state
 */
interface SystemStatus {
  state: SystemState;
  mode: string; // EngineMode value (RESEARCH, PAPER, LIVE, PAUSED, KILLED)
  uptime: number;
  heartbeat: string | null;
  isLoading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  // PHASE 1: Debounce state
  isActionInFlight: boolean;
  lockedActions: Set<ActionType>;
  // PHASE 4: Auth state
  authState: AuthUIState;
  // PHASE 4: Biometric state
  biometricAvailable: boolean;
  isBiometricLockedOut: boolean;
  // PHASE 5: Health-based status details
  healthStatus?: "RUNNING" | "STALE" | "FROZEN";
  loopTick?: number;
  heartbeatAge?: number;
  broker?: string;
  watchdog?: string;
}

interface UseSystemStatusReturn extends SystemStatus {
  refresh: () => Promise<void>;
  startEngine: () => Promise<void>;
  stopEngine: () => Promise<void>;
  killEngine: () => Promise<void>;
  modeLabel: string; // UI-friendly mode label
  // Utility methods
  canExecuteAction: (action: ActionType) => boolean;
  isButtonDisabled: (action: ActionType) => boolean;
}

/**
 * Hook for managing system status with mobile hardening.
 * 
 * PHASE 1: Mobile debounce - prevents duplicate taps
 * PHASE 2: Optimistic UI - immediate visual feedback
 * PHASE 3: Status stability - never shows UNKNOWN during normal operation
 * PHASE 4: Auth integration - handles 401/403 gracefully
 */
export function useSystemStatus(): UseSystemStatusReturn {
  // Core state
  const [state, setState] = useState<SystemState>(UIState.UNKNOWN);
  const [mode, setMode] = useState<string>('UNKNOWN');
  const [modeLabel, setModeLabel] = useState<string>('Unknown');
  const [uptime, setUptime] = useState<number>(0);
  const [heartbeat, setHeartbeat] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  
  // PHASE 5: Health-based status details
  const [healthStatus, setHealthStatus] = useState<"RUNNING" | "STALE" | "FROZEN" | undefined>(undefined);
  const [loopTick, setLoopTick] = useState<number | undefined>(undefined);
  const [heartbeatAge, setHeartbeatAge] = useState<number | undefined>(undefined);
  const [broker, setBroker] = useState<string | undefined>(undefined);
  const [watchdog, setWatchdog] = useState<string | undefined>(undefined);

  // PHASE 1: Debounce state
  const [isActionInFlight, setIsActionInFlight] = useState<boolean>(false);
  const [lockedActions, setLockedActions] = useState<Set<ActionType>>(new Set());

  // Request abort controllers for canceling in-flight requests
  const startAbortControllerRef = useRef<AbortController | null>(null);
  const stopAbortControllerRef = useRef<AbortController | null>(null);
  const killAbortControllerRef = useRef<AbortController | null>(null);

  // PHASE 4: Auth state (initialized asynchronously)
  const [authState, setAuthState] = useState<AuthUIState>({
    isAuthenticated: false,
    isAuthRequired: false,
    authError: null,
    isHardwareBacked: false,
    hasToken: false,
  });

  // PHASE 4: Biometric availability state
  const [biometricAvailable, setBiometricAvailable] = useState<boolean>(false);
  const [isBiometricLockedOut, setIsBiometricLockedOut] = useState<boolean>(false);

  // Refs for cleanup
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const actionTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  /**
   * Update locked actions state from debounce manager
   */
  const updateLockedActionsState = useCallback(() => {
    const actions: ActionType[] = ['START', 'STOP', 'KILL'];
    const locked = new Set<ActionType>();
    actions.forEach(action => {
      if (debounceManager.isActionLocked(action)) {
        locked.add(action);
      }
    });
    setLockedActions(locked);
    setIsActionInFlight(debounceManager.isAnyActionInFlight());
  }, []);

  /**
   * PHASE 1: Check if action can be executed
   */
  const canExecuteAction = useCallback((action: ActionType): boolean => {
    return debounceManager.canExecuteAction(action);
  }, []);

  /**
   * PHASE 3-4: Fetch health from /health endpoint
   * PHASE 4: If /health responds → system is ONLINE (not OFFLINE)
   * PHASE 4: Replace hard OFFLINE logic with heartbeat-based status
   * UNKNOWN only on network/timeout/JSON errors
   */
  const fetchStatus = useCallback(async () => {
    try {
      // PHASE 3: Use /health endpoint (canonical Sentinel X API)
      const healthResponse = await apiClient.getHealth();
      
      // PHASE 4: If /health responds, system is ONLINE
      // Parse health response (handles missing fields gracefully)
      const parsed = parseHealthResponse(healthResponse);
      
      // Also fetch /status for uptime (fallback if /health doesn't have it)
      let uptime = 0;
      try {
        const statusResponse = await apiClient.getStatus();
        uptime = statusResponse.uptime || 0;
      } catch (statusErr) {
        // Ignore /status errors - use defaults
        console.debug('[Status] Endpoint failed (non-fatal), using defaults');
      }

      // Log health response
      console.log('[Health] Response:', {
        status: parsed.status,
        mode: parsed.mode,
        loop_tick: parsed.loop_tick,
        heartbeat_age: parsed.heartbeat_age,
        broker: parsed.broker,
        watchdog: parsed.watchdog,
      });

      // Update state - mapping happens in parseHealthResponse
      setState(parsed.state);
      setMode(parsed.mode);
      setModeLabel(parsed.modeLabel);
      setUptime(uptime);
      setHeartbeat(`${parsed.heartbeat_age.toFixed(1)}s`); // Display heartbeat age
      
      // PHASE 5: Update health-based status details
      setHealthStatus(parsed.status as "RUNNING" | "STALE" | "FROZEN");
      setLoopTick(parsed.loop_tick);
      setHeartbeatAge(parsed.heartbeat_age);
      setBroker(parsed.broker);
      setWatchdog(parsed.watchdog);
      
      setLastUpdated(new Date());
      setError(null);

      // PHASE 4: Update auth state
      const authState = await apiClient.getAuthState();
      setAuthState(authState);
    } catch (err) {
      const apiError = err as APIError;

      console.error('[Health] Error:', {
        message: apiError.message,
        isNetworkError: apiError.isNetworkError,
        isAuthError: apiError.isAuthError,
        statusCode: apiError.statusCode,
      });

      // PHASE 4: Handle auth errors - don't change state
      if (apiError.isAuthError) {
        setAuthState(apiClient.getAuthState());
        setError(apiError.message);
        // Don't reset state to UNKNOWN on auth error - keep current state
        return;
      }

      // PHASE 4: UNKNOWN only on network/timeout/invalid JSON errors
      // PHASE 4: Never assume OFFLINE if API responds (even with error)
      if (apiError.isNetworkError || !apiError.statusCode) {
        // Network error or timeout - set UNKNOWN (true offline)
        setState(UIState.UNKNOWN);
        setError(apiError.message);
      } else {
        // Other HTTP errors - keep current state, show error
        // If we got an HTTP response, system is reachable (not OFFLINE)
        setError(apiError.message);
      }
    }
  }, []);

  /**
   * Manual refresh (exposed to UI)
   */
  const refresh = useCallback(async () => {
    setIsLoading(true);
    await fetchStatus();
    setIsLoading(false);
  }, [fetchStatus]);

  /**
   * PHASE 1: Initialize hardware-backed auth storage on mount
   */
  useEffect(() => {
    const initAuth = async () => {
      await initializeAuthStorage();
      const authState = await apiClient.getAuthState();
      setAuthState(authState);

      // Check biometric availability
      const isAvailable = await biometricAuth.isAvailable();
      setBiometricAvailable(isAvailable);

      // Check if locked out
      const lockedOut = await biometricAuth.isLockedOut();
      setIsBiometricLockedOut(lockedOut);
    };

    initAuth();
  }, []);

  /**
   * PHASE 5: Setup polling on mount - 1s desktop, 2s mobile
   */
  useEffect(() => {
    // Initial fetch
    fetchStatus();

    // Setup polling interval
    const startPolling = () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }

      pollIntervalRef.current = setInterval(async () => {
        await fetchStatus();
        updateLockedActionsState(); // Also update debounce state
      }, POLL_INTERVAL);
    };

    startPolling();

    // Cleanup
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
      if (actionTimeoutRef.current) {
        clearTimeout(actionTimeoutRef.current);
      }
    };
  }, [fetchStatus, updateLockedActionsState]);

  /**
   * Perform action with debounce - NO optimistic updates
   * 
   * Flow:
   * 1. Check debounce (can action execute?)
   * 2. Abort previous request if exists
   * 3. Lock action (prevent duplicates)
   * 4. Execute API call with timeout
   * 5. Handle response (success/error)
   * 6. Unlock action (with debounce delay)
   * 7. Status poll will reflect new state automatically
   */
  const performActionWithDebounce = useCallback(
    async (
      action: ActionType,
      apiCall: (signal: AbortSignal) => Promise<void>,
      abortControllerRef: MutableRefObject<AbortController | null>
    ): Promise<void> => {
      // PHASE 1: Check debounce
      if (!debounceManager.canExecuteAction(action)) {
        throw new Error(`Action ${action} is debounced or another action is in progress`);
      }

      // Abort previous request if exists
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      // Create new abort controller
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      // PHASE 1: Lock action
      debounceManager.lockAction(action);
      updateLockedActionsState();
      setIsLoading(true);
      setError(null);

      console.log(`[Action] ${action} started`);

      // PHASE 1: Set action timeout (safety net)
      actionTimeoutRef.current = setTimeout(() => {
        console.warn(`[Action] ${action} timed out after ${ACTION_TIMEOUT}ms`);
        abortController.abort();
        debounceManager.forceUnlock(action);
        updateLockedActionsState();
        setIsLoading(false);
        setError('Action timed out. Status will update on next poll.');
      }, ACTION_TIMEOUT);

      try {
        await apiCall(abortController.signal);

        // Clear timeout on success
        if (actionTimeoutRef.current) {
          clearTimeout(actionTimeoutRef.current);
          actionTimeoutRef.current = null;
        }

        console.log(`[Action] ${action} succeeded`);
        
        // Status poll will automatically reflect new state
        // No optimistic update - wait for /status poll
      } catch (err) {
        // Clear timeout on error
        if (actionTimeoutRef.current) {
          clearTimeout(actionTimeoutRef.current);
          actionTimeoutRef.current = null;
        }

        // Ignore abort errors
        if (abortController.signal.aborted) {
          console.log(`[Action] ${action} aborted`);
          return;
        }

        const apiError = err as APIError;

        console.error(`[Action] ${action} failed:`, {
          message: apiError.message,
          isNetworkError: apiError.isNetworkError,
          isAuthError: apiError.isAuthError,
          statusCode: apiError.statusCode,
        });

        // PHASE 4: Handle auth/biometric errors
        if (apiError.isAuthError || apiError.isBiometricError) {
          const authState = await apiClient.getAuthState();
          setAuthState(authState);
          
          // Check if locked out
          const lockedOut = await biometricAuth.isLockedOut();
          setIsBiometricLockedOut(lockedOut);
        }

        setError(apiError.message);
        
        // No state rollback - status poll will show actual state
      } finally {
        setIsLoading(false);
        
        // Clear abort controller if this is the current request
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
        }
        
        // PHASE 1: Unlock action (with debounce delay built into manager)
        debounceManager.unlockAction(action);
        
        // Update UI state after brief delay to show unlock
        setTimeout(() => {
          updateLockedActionsState();
        }, DEBOUNCE_CONFIG.LOCK_DURATION_MS + 50);
      }
    },
    [updateLockedActionsState]
  );

  /**
   * START action - NO optimistic update
   */
  const startEngine = useCallback(async () => {
    await performActionWithDebounce(
      'START',
      (signal) => apiClient.start(signal),
      startAbortControllerRef
    );
  }, [performActionWithDebounce]);

  /**
   * STOP action - NO optimistic update
   */
  const stopEngine = useCallback(async () => {
    await performActionWithDebounce(
      'STOP',
      (signal) => apiClient.stop(signal),
      stopAbortControllerRef
    );
  }, [performActionWithDebounce]);

  /**
   * KILL action - NO optimistic update
   * Note: KILL still uses debounce but is never blocked by state
   */
  const killEngine = useCallback(async () => {
    await performActionWithDebounce(
      'KILL',
      (signal) => apiClient.kill(signal),
      killAbortControllerRef
    );
  }, [performActionWithDebounce]);

  /**
   * PHASE 3 + 5: Determine if button should be disabled
   * Combines state logic with debounce state
   * PHASE 4: Includes biometric lockout check
   */
  const isButtonDisabled = useCallback((action: ActionType): boolean => {
    // PHASE 4: Disable if auth error (except for read operations)
    if (authState.authError && authState.isAuthRequired) {
      return true;
    }

    // PHASE 4: Disable if biometric locked out
    if (isBiometricLockedOut && action !== 'KILL') {
      // KILL still available even if locked out (emergency)
      return true;
    }

    // PHASE 1: Check debounce/lock state
    if (!canExecuteAction(action)) {
      return true;
    }

    // PHASE 3: EngineMode-based logic (control plane semantics)
    // EngineMode is authoritative - buttons control permissions, not lifecycle
    switch (action) {
      case 'START':
        // Disabled if already in PAPER mode (idempotent)
        return mode === 'PAPER';
      case 'STOP':
        // Disabled if already in RESEARCH mode (idempotent)
        return mode === 'RESEARCH';
      case 'KILL':
        // Disabled if already KILLED
        return mode === 'KILLED';
      default:
        return false;
    }
  }, [state, authState, isBiometricLockedOut, canExecuteAction]);

  return {
    state,
    mode,
    modeLabel,
    uptime,
    heartbeat,
    isLoading,
    error,
    lastUpdated,
    isActionInFlight,
    lockedActions,
    authState,
    biometricAvailable,
    isBiometricLockedOut,
    // PHASE 5: Health-based status details
    healthStatus,
    loopTick,
    heartbeatAge,
    broker,
    watchdog,
    refresh,
    startEngine,
    stopEngine,
    killEngine,
    canExecuteAction,
    isButtonDisabled,
  };
}
