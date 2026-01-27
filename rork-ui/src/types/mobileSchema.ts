/**
 * Rork-Specific Mobile Schema - Version 1
 * 
 * PHASE 1 — RORK-SPECIFIC SCHEMA DEFINITION
 * 
 * Mobile-optimized schema explicitly for Rork.
 * 
 * Rules:
 * - Schema is read-only
 * - Missing fields allowed (graceful degradation)
 * - Versioned for backward compatibility
 * 
 * MOBILE READ-ONLY GUARANTEE
 * PUSH IS ALERT-ONLY
 * METRICS ARE OBSERVABILITY-ONLY
 * LIVE CONTROL NOT ENABLED
 */

export const SCHEMA_VERSION = "v1";

/**
 * Root mobile state object
 */
export interface SentinelXMobileState {
  schema_version: string;
  engine: EngineStatus;
  broker: BrokerStatus;
  strategies: StrategySummary[];
  portfolio: PortfolioSummary;
  risk: RiskSnapshot;
  system: SystemHealth;
  timestamps: TimeInfo;
}

/**
 * Engine status information
 */
export interface EngineStatus {
  mode: "TRAINING" | "SHADOW" | "LIVE_DISABLED" | "PAUSED" | "KILLED";
  state: "RUNNING" | "STALE" | "FROZEN" | "STOPPED";
  loop_tick: number;
  heartbeat_age: number;  // seconds
  loop_tick_age: number;  // seconds
  uptime_sec: number;  // seconds
  loop_phase?: string;  // Optional: current engine phase
}

/**
 * Broker status information
 */
export interface BrokerStatus {
  broker_type: "ALPACA_PAPER" | "PAPER" | "TRADOVATE" | "NONE";
  connected: boolean;
  degraded?: boolean;  // Optional: broker health status
  last_successful_call_ts?: number;  // Optional: monotonic timestamp
}

/**
 * Strategy summary (per-strategy performance)
 */
export interface StrategySummary {
  strategy_id: string;
  status: "ACTIVE" | "PAUSED" | "DISABLED";
  pnl: number;  // Total PnL for this strategy
  drawdown: number;  // Current drawdown (negative for drawdown)
  win_rate: number;  // Win rate (0.0-1.0)
  trades_today: number;  // Number of trades today
  last_trade_ts?: number;  // Optional: timestamp of last trade (monotonic)
  composite_score?: number;  // Optional: strategy composite score
  ranking?: number;  // Optional: strategy ranking
}

/**
 * Portfolio summary
 */
export interface PortfolioSummary {
  equity: number | null;  // Current equity (null if unavailable)
  total_pnl: number;  // Total portfolio PnL
  unrealized_pnl: number;  // Unrealized PnL
  realized_pnl: number;  // Realized PnL
  open_positions: number;  // Number of open positions
  buying_power?: number | null;  // Optional: available buying power
}

/**
 * Risk snapshot
 */
export interface RiskSnapshot {
  max_drawdown: number;  // Maximum drawdown (negative value)
  current_drawdown: number;  // Current drawdown (negative value)
  daily_drawdown?: number;  // Optional: daily drawdown
  drawdown_threshold?: number;  // Optional: drawdown threshold
  risk_score?: number;  // Optional: aggregate risk score (0.0-1.0)
}

/**
 * System health information
 */
export interface SystemHealth {
  watchdog: "OK" | "STALE" | "FROZEN";
  cpu_usage?: number | null;  // Optional: CPU usage percentage
  memory_usage?: number | null;  // Optional: memory usage percentage
  disk_usage?: number | null;  // Optional: disk usage percentage
  errors_last_hour?: number;  // Optional: error count in last hour
}

/**
 * Timestamp information
 */
export interface TimeInfo {
  server_time: number;  // Server monotonic timestamp
  server_time_iso: string;  // Server time in ISO format
  client_received_ts?: number;  // Optional: client-received timestamp (set by client)
  time_since_last_update?: number;  // Optional: seconds since last update
}

/**
 * Push notification payload (sent via APNs)
 */
export interface PushNotificationPayload {
  title: string;
  body: string;
  severity: "info" | "warning" | "critical";
  timestamp: number;  // Monotonic timestamp
  event_type: "ENGINE_FROZEN" | "ENGINE_RECOVERED" | "WATCHDOG_RESTART" | "STRATEGY_DISABLED";
  metadata?: Record<string, any>;  // Optional: additional metadata (non-sensitive)
}

/**
 * Device registration request
 */
export interface DeviceRegistrationRequest {
  device_id: string;
  device_token: string;  // APNs device token
  platform: "ios" | "android";  // Platform type
  app_version?: string;  // Optional: app version
  push_enabled: boolean;  // User opt-in for push notifications
}

/**
 * Device registration response
 */
export interface DeviceRegistrationResponse {
  device_id: string;
  registered: boolean;
  push_enabled: boolean;
  registered_at: string;  // ISO timestamp
}
