/**
 * API Types for Sentinel X Rork UI
 * 
 * PHASE 2: Enum mapping - matches backend EXACTLY
 */

// Backend state enum - MUST match sentinel_x/core/state.py BotState
export enum BotState {
  STOPPED = "STOPPED",
  RUNNING = "RUNNING",
  TRAINING = "TRAINING",
  TRADING = "TRADING",
}

// UI-only state for network issues
export enum UIState {
  UNKNOWN = "UNKNOWN", // Only before first successful poll or on network error
}

export type SystemState = BotState | UIState;

// Status response from GET /status
// SINGLE SOURCE OF TRUTH - mode is authoritative (EngineMode)
export interface StatusResponse {
  mode: string; // EngineMode: RESEARCH, PAPER, LIVE, PAUSED, KILLED (authoritative)
  uptime: number;
  active_strategies: number;
  broker_connectivity: boolean;
  shadow_trading: boolean;
  last_error: string | null;
  // Legacy fields (for backwards compatibility)
  state?: string; // Legacy bot state (deprecated)
  heartbeat_ts?: string | null; // Last heartbeat timestamp
}

// Action response from POST /start, /stop, /kill
export interface ActionResponse {
  ok: boolean;
  message: string;
}

// Health response from GET /health (PHASE 3)
export interface HealthResponse {
  status: "RUNNING" | "STALE" | "FROZEN";
  mode: "TRAINING" | "PAPER" | "RESEARCH" | "LIVE" | "PAUSED" | "KILLED";
  loop_phase?: string;
  loop_tick?: number;
  heartbeat_age?: number;
  loop_tick_age?: number;
  broker?: "ALPACA_PAPER" | "PAPER" | "TRADOVATE" | "NONE";
  watchdog?: "OK" | "STALE" | "FROZEN";
  timestamp?: string;
}

// Strategy view from GET /strategies (PHASE 3)
export interface StrategyView {
  id: string; // Strategy name
  status: "ACTIVE" | "INACTIVE" | "DISABLED";
  pnl?: number | null;
  win_rate?: number | null;
  last_tick?: number;
}

// Strategies response (now returns array directly, not wrapped)
export type StrategiesResponse = StrategyView[];

// Legacy strategies response (for backwards compatibility)
export interface LegacyStrategiesResponse {
  strategies: StrategyView[];
  count: number;
}

// Position view
export interface PositionView {
  symbol: string;
  qty: number;
  avg_price: number;
  current_price: number | null;
  unrealized_pnl: number;
  entry_time: string;
}

export interface PositionsResponse {
  positions: PositionView[];
  count: number;
  total_pnl: number;
}

// Account info
export interface AccountInfo {
  equity?: number;
  buying_power?: number;
  cash?: number;
  portfolio_value?: number;
  error?: string;
}

// Metrics response from GET /metrics (PHASE 3)
export interface MetricsResponse {
  equity?: number | null;
  daily_pnl?: number;
  uptime_seconds?: number;
  timestamp?: string;
}

// Risk response from GET /risk (PHASE 3)
export interface RiskResponse {
  max_drawdown?: "server_managed" | number;
  max_daily_loss?: "server_managed" | number;
  risk_state?: "NORMAL" | "WARNING" | "CRITICAL";
  timestamp?: string;
}

// Funding response from GET /funding (PHASE 3)
export interface FundingResponse {
  current_equity?: number | null;
  can_add_funds?: boolean;
  can_withdraw?: boolean;
  cooldown_active?: boolean;
  timestamp?: string;
}

// Live metrics summary (aggregated from multiple endpoints)
export interface LiveMetrics {
  equity: number | null;
  totalPnL: number;
  openPositionsCount: number;
  activeStrategiesCount: number;
  engineUptime: number;
  currentMode: string;
  lastUpdated: Date | null;
}

// Health snapshot from WebSocket /ws/health (PHASE 1)
export interface HealthSnapshot {
  status: 'RUNNING' | 'STALE' | 'FROZEN';
  mode: string; // EngineMode: RESEARCH, PAPER, LIVE, PAUSED, KILLED
  loop_phase: string;
  loop_tick: number;
  loop_tick_age: number; // seconds
  heartbeat_age: number; // seconds
  broker: string; // ALPACA_PAPER | PAPER | TRADOVATE | NONE
  watchdog: 'OK' | 'STALE' | 'FROZEN';
  timestamp: number; // monotonic timestamp
}