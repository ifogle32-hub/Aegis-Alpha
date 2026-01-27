/**
 * State Normalization Utilities
 * 
 * PHASE 1: Status normalization
 * PHASE 2: Enum mapping with safe fallback
 */

import { BotState, UIState, SystemState, StatusResponse } from '../types/api';

/**
 * Normalize backend state string to typed BotState.
 * 
 * PHASE 2 RULE: Any unknown value → STOPPED (NOT UNKNOWN)
 * UNKNOWN is only used for network errors, not unknown backend states.
 */
export function normalizeState(backendState: string | undefined): BotState {
  if (!backendState) {
    return BotState.STOPPED; // Safe fallback
  }

  // Normalize to uppercase and trim
  const normalized = backendState.toUpperCase().trim();

  // Match against known states
  switch (normalized) {
    case 'STOPPED':
      return BotState.STOPPED;
    case 'RUNNING':
      return BotState.RUNNING;
    case 'TRAINING':
      return BotState.TRAINING;
    case 'TRADING':
      return BotState.TRADING;
    default:
      // PHASE 2: Unknown backend state → STOPPED (safe fallback)
      console.warn(`Unknown backend state: ${backendState}, falling back to STOPPED`);
      return BotState.STOPPED;
  }
}

/**
 * Map EngineMode to UI display label.
 * 
 * UI labels mapping:
 * - RESEARCH → "Training / Backtesting"
 * - PAPER → "Paper Trading"
 * - LIVE → "Live Trading"
 * - PAUSED → "Paused"
 * - KILLED → "Emergency Stop"
 * - UNKNOWN/OFFLINE → Only if API unreachable
 */
export function mapModeToLabel(mode: string): string {
  if (!mode) {
    return 'Unknown';
  }

  const normalized = mode.toUpperCase().trim();
  
  switch (normalized) {
    case 'RESEARCH':
      return 'Training / Backtesting';
    case 'PAPER':
      return 'Paper Trading';
    case 'LIVE':
      return 'Live Trading';
    case 'PAUSED':
      return 'Paused';
    case 'KILLED':
      return 'Emergency Stop';
    default:
      return mode; // Return as-is if unknown
  }
}

/**
 * Parse health response from /health endpoint (PHASE 3-4).
 * 
 * PHASE 4: Replace hard OFFLINE logic with heartbeat-based status
 * PHASE 4: If /health responds → system is ONLINE
 * PHASE 4: If heartbeat_age < threshold → green badge
 * PHASE 4: If stale → yellow badge
 * PHASE 4: If frozen → red badge
 * 
 * Expected schema from /health:
 * {
 *   "status": "RUNNING" | "STALE" | "FROZEN",
 *   "mode": "TRAINING" | "PAPER" | "RESEARCH" | "LIVE" | "PAUSED" | "KILLED",
 *   "loop_phase": "LOOP_START" | "STRATEGY_EVAL" | "ROUTING" | "BROKER_SUBMIT" | "IDLE",
 *   "loop_tick": int,
 *   "heartbeat_age": float (seconds),
 *   "loop_tick_age": float (seconds),
 *   "broker": "ALPACA_PAPER" | "PAPER" | "TRADOVATE" | "NONE",
 *   "watchdog": "OK" | "STALE" | "FROZEN"
 * }
 */
export function parseHealthResponse(response: any): {
  state: BotState | UIState;
  mode: string;
  modeLabel: string;
  uptime: number;
  heartbeat: string | null;
  status: string; // RUNNING | STALE | FROZEN
  loop_tick: number;
  heartbeat_age: number;
  broker: string;
  watchdog: string;
} {
  // PHASE 4: Treat missing fields as defaults (never crash)
  const status = response.status || 'FROZEN';
  const mode = response.mode || 'UNKNOWN';
  const modeLabel = mapModeToLabel(mode);
  const loop_tick = typeof response.loop_tick === 'number' ? response.loop_tick : 0;
  const heartbeat_age = typeof response.heartbeat_age === 'number' ? response.heartbeat_age : 999.9;
  const broker = response.broker || 'NONE';
  const watchdog = response.watchdog || 'FROZEN';
  
  // PHASE 4: Map health status to UI state
  // If /health responds, system is ONLINE (not OFFLINE)
  let uiState: BotState | UIState;
  if (status === 'RUNNING') {
    // Map mode to UI state
    if (mode === 'RESEARCH' || mode === 'TRAINING') {
      uiState = BotState.RUNNING; // Training mode = RUNNING
    } else if (mode === 'PAPER') {
      uiState = BotState.TRADING; // Paper trading = TRADING
    } else if (mode === 'LIVE') {
      uiState = BotState.TRADING; // Live trading = TRADING
    } else if (mode === 'PAUSED' || mode === 'KILLED') {
      uiState = BotState.STOPPED;
    } else {
      uiState = BotState.RUNNING; // Default to RUNNING if mode unknown
    }
  } else if (status === 'STALE' || status === 'FROZEN') {
    // System is online but unhealthy - still show as RUNNING (with badge)
    uiState = BotState.RUNNING;
  } else {
    // Unknown status - default to STOPPED (safe fallback)
    uiState = BotState.STOPPED;
  }
  
  // PHASE 5: Format heartbeat age for display
  const heartbeatDisplay = heartbeat_age < 999.0 ? `${heartbeat_age.toFixed(1)}s` : null;
  
  return {
    state: uiState,
    mode,
    modeLabel,
    uptime: 0, // Uptime not in /health response (use /metrics instead)
    heartbeat: heartbeatDisplay, // Heartbeat age in seconds
    status,
    loop_tick,
    heartbeat_age,
    broker,
    watchdog,
  };
}

/**
 * Parse status response from /status endpoint (legacy).
 * 
 * CONTROL PLANE: Now uses EngineMode as primary state.
 * - mode is the authoritative state (RESEARCH, PAPER, LIVE, PAUSED, KILLED)
 * - state is legacy field (for backwards compatibility)
 * 
 * Status mapping (legacy):
 * - state === "RUNNING"  -> UI: RUNNING
 * - state === "TRAINING" -> UI: RUNNING
 * - state === "STOPPED"  -> UI: STOPPED
 * - state === "TRADING"  -> UI: TRADING
 * - request error ONLY -> UI: UNKNOWN (handled in hook)
 */
export function parseStatusResponse(response: StatusResponse): {
  state: BotState | UIState;
  mode: string;
  modeLabel: string; // UI-friendly label
  uptime: number;
  heartbeat: string | null;
} {
  // Use mode from response (EngineMode is authoritative)
  const engineMode = response.mode || (response.state || 'UNKNOWN');
  const modeLabel = mapModeToLabel(engineMode);
  
  // Legacy state mapping (for backwards compatibility)
  const normalized = normalizeState(response.state);
  const uiState = normalized === BotState.TRAINING ? BotState.RUNNING : normalized;
  
  return {
    state: uiState,
    mode: engineMode,
    modeLabel,
    uptime: response.uptime || 0,
    heartbeat: response.heartbeat_ts || null,
  };
}

/**
 * Check if state is "active" (engine running in any mode).
 * Used for button state logic.
 */
export function isActiveState(state: SystemState): boolean {
  return (
    state === BotState.RUNNING ||
    state === BotState.TRAINING ||
    state === BotState.TRADING
  );
}

/**
 * Check if state is stopped.
 */
export function isStoppedState(state: SystemState): boolean {
  return state === BotState.STOPPED;
}

/**
 * Get display-friendly state name with color.
 */
export function getStateDisplay(state: SystemState): {
  label: string;
  color: string;
} {
  switch (state) {
    case BotState.STOPPED:
      return { label: 'Stopped', color: '#6B7280' }; // Gray
    case BotState.RUNNING:
      return { label: 'Running', color: '#3B82F6' }; // Blue
    case BotState.TRAINING:
      return { label: 'Training', color: '#F59E0B' }; // Amber
    case BotState.TRADING:
      return { label: 'Trading', color: '#10B981' }; // Green
    case UIState.UNKNOWN:
      return { label: 'Unknown', color: '#EF4444' }; // Red
    default:
      return { label: 'Unknown', color: '#EF4444' };
  }
}

