/**
 * Sentinel X Rork UI Schema - TypeScript Type Definitions
 * 
 * PRODUCTION-SAFE, REGULATOR-SAFE, REGRESSION-PROOF
 * 
 * This file defines TypeScript types that match the Rork UI schema exactly.
 * All types are derived from the authoritative backend engine behavior.
 * 
 * DO NOT MODIFY WITHOUT ARCHITECT REVIEW
 */

// ============================================================================
// PHASE 0 — GLOBAL APP CONTRACT
// ============================================================================

export interface RorkApp {
  id: "sentinel_x";
  name: "Sentinel X";
  type: "autonomous_trading_system";
  authority: "backend";
  ui_mode: "command_and_observe";
  always_on: true;
  backend_url: string;
  api_version: "v1";
}

// ============================================================================
// PHASE 1 — ENGINE STATE MODEL (LOCKED)
// ============================================================================

export type EngineState = "RESEARCH" | "PAPER" | "LIVE" | "PAUSED" | "KILLED";

export interface EngineStateMapping {
  RESEARCH: {
    label: "Training";
    description: "Research, backtests, and simulations run continuously. No trading execution.";
    is_trading: false;
    is_training: true;
    is_execution_enabled: false;
  };
  PAPER: {
    label: "Paper Trading";
    description: "Real execution via paper broker only. No real capital at risk.";
    is_trading: true;
    is_training: false;
    is_execution_enabled: true;
  };
  LIVE: {
    label: "Live Trading";
    description: "Real capital execution. Requires hardware approval and explicit promotion.";
    is_trading: true;
    is_training: false;
    is_execution_enabled: true;
    requires_hardware_auth: true;
  };
  PAUSED: {
    label: "Paused";
    description: "All execution blocked. Research continues.";
    is_trading: false;
    is_training: true;
    is_execution_enabled: false;
  };
  KILLED: {
    label: "Killed";
    description: "Emergency stop. Execution disabled globally. Irreversible without restart.";
    is_trading: false;
    is_training: false;
    is_execution_enabled: false;
    is_irreversible: true;
  };
}

// ============================================================================
// PHASE 2 — CONTROL SURFACE (COMMAND ONLY)
// ============================================================================

export type ControlCommandId = "START" | "STOP" | "EMERGENCY_KILL";

export interface ControlCommand {
  id: ControlCommandId;
  label: string;
  endpoint: string;
  requires_auth: boolean;
  visible_when: {
    engine_state: EngineState[];
  };
  payload?: Record<string, any>;
  resulting_state: EngineState;
  confirmation_required: boolean;
  confirmation_message?: string;
  rate_limit: string;
  timeout_seconds: number;
  overrides_all_commands?: boolean;
  ui_behavior: {
    wait_for_state_update: boolean;
    poll_interval_ms: number;
    max_wait_seconds: number;
    show_loading: boolean;
    show_critical_alert?: boolean;
    never_assume_success: boolean;
  };
}

// ============================================================================
// PHASE 3 — REAL-TIME TELEMETRY PANELS
// ============================================================================

export type TelemetryPanelId =
  | "equity_curve"
  | "pnl"
  | "drawdown"
  | "positions"
  | "broker_health"
  | "execution_latency"
  | "order_fill_quality"
  | "engine_heartbeat";

export interface TelemetryPanel {
  id: TelemetryPanelId;
  label: string;
  endpoint: string;
  poll_interval_ms: number;
  data_fields: Record<string, string>;
  visualization: string;
  read_only: true;
}

export interface EquityCurveData {
  equity: number;
  benchmark: number;
  timestamp: string;
}

export interface PnLData {
  daily_pnl: number;
  cumulative_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  timestamp: string;
}

export interface DrawdownData {
  current_drawdown: number;
  max_drawdown: number;
  drawdown_percent: number;
  timestamp: string;
}

export interface PositionData {
  symbol: string;
  qty: number;
  avg_price: number;
  current_price?: number;
  unrealized_pnl: number;
  entry_time: string;
}

export interface BrokerHealthData {
  active_broker: string;
  health_score: number;
  latency_ms: number;
  fill_rate: number;
  reliability_score: number;
  failover_history: Array<{
    timestamp: string;
    from_broker: string;
    to_broker: string;
    reason: string;
  }>;
}

export interface ExecutionLatencyData {
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  timestamp: string;
}

export interface OrderFillQualityData {
  avg_slippage_bps: number;
  fill_rate: number;
  partial_fill_rate: number;
  rejection_rate: number;
}

export interface EngineHeartbeatData {
  heartbeat_ts: string;
  uptime_seconds: number;
  is_alive: boolean;
}

// ============================================================================
// PHASE 4 — STRATEGY INTELLIGENCE
// ============================================================================

export type StrategyStatus = "ACTIVE" | "DISABLED" | "SHADOW";

export interface StrategyView {
  name: string;
  status: StrategyStatus;
  pnl: number;
  sharpe: number;
  drawdown: number;
  expectancy: number;
  health_score: number;
  auto_disabled: boolean;
  promotion_score?: number;
  paper_approved?: boolean;
  live_approved?: boolean;
}

// ============================================================================
// PHASE 5 — SHADOW vs LIVE COMPARISON
// ============================================================================

export interface ShadowComparisonData {
  shadow_equity: number;
  paper_equity: number;
  divergence: number;
  divergence_percent: number;
  signal_agreement_percent: number;
  slippage_comparison: number;
  fill_rate_comparison: number;
}

// ============================================================================
// PHASE 6 — CAPITAL & FUNDING (SAFE) - Legacy interface
// ============================================================================

// Note: See PHASE 7 for extended FundingSchedule interface

export interface BankConnectionStatus {
  connected: boolean;
  bank_name?: string;
  last_sync?: string;
  status: "active" | "inactive" | "error";
}

// ============================================================================
// PHASE 7 — MULTI-BROKER & EXECUTION VISIBILITY
// ============================================================================

export interface BrokerDecision {
  intent_id: string;
  selected_broker: string;
  health_score: number;
  reasoning: string;
  alternatives_considered: string[];
}

export interface BrokerHealthScores {
  [brokerName: string]: {
    latency_ms: number;
    fill_rate: number;
    slippage_bps: number;
    reliability_score: number;
  };
}

export interface MultiBrokerData {
  active_broker: string;
  available_brokers: string[];
  failover_history: Array<{
    timestamp: string;
    from_broker: string;
    to_broker: string;
    reason: string;
  }>;
  broker_decisions: BrokerDecision[];
  health_scores: BrokerHealthScores;
  retry_counts: Record<string, number>;
}

// ============================================================================
// PHASE 8 — ALERTING & INCIDENTS
// ============================================================================

export type AlertSeverity = "critical" | "error" | "warning" | "info";

export type AlertType =
  | "kill_switch_armed"
  | "strategy_disabled"
  | "drawdown_breach"
  | "broker_failure"
  | "risk_rejection";

export interface Alert {
  id: string;
  type: AlertType;
  severity: AlertSeverity;
  message: string;
  timestamp: string;
  auto_dismiss: boolean;
  notification_channels: string[];
}

// ============================================================================
// PHASE 9 — AUDIT & REGULATORY EXPORTS
// ============================================================================

export type ExportType =
  | "executions"
  | "broker_decisions"
  | "strategy_changes"
  | "risk_rejections"
  | "capital_movements";

export type ExportFormat = "CSV" | "JSON" | "PDF";

// ============================================================================
// PHASE 10 — MOBILE & INVESTOR MODE
// ============================================================================

export interface MobileUIPanel {
  id: string;
  endpoint: string;
  poll_interval_ms: number;
}

export interface InvestorViewPanel {
  id: string;
  endpoint: string;
  poll_interval_ms: number;
}

// ============================================================================
// PHASE 11 — UI GUARANTEES (NON-NEGOTIABLE)
// ============================================================================

export interface UIGuarantee {
  id: string;
  description: string;
  enforcement: string;
}

// ============================================================================
// API CONTRACT
// ============================================================================

export interface APIContract {
  base_url: string;
  authentication: {
    type: "api_key";
    header: "X-API-Key";
    required_for: string[];
  };
  rate_limiting: {
    control_endpoints: string;
    read_endpoints: string;
    kill_endpoint: "bypass";
  };
  timeouts: {
    control_endpoints: number;
    read_endpoints: number;
    kill_endpoint: number;
  };
  error_handling: {
    retry_strategy: "exponential_backoff";
    max_retries: number;
    backoff_multiplier: number;
  };
  state_sync: {
    poll_interval_ms: number;
    max_wait_seconds: number;
    never_assume_success: true;
  };
}

// ============================================================================
// STATUS RESPONSE (Backend Authority)
// ============================================================================

export interface StatusResponse {
  mode: EngineState;
  uptime: number;
  active_strategies: number;
  broker_connectivity: boolean;
  shadow_trading: boolean;
  last_error?: string;
  state?: string; // Legacy field
  heartbeat_ts?: string; // Legacy field
}

// ============================================================================
// ACTION RESPONSE
// ============================================================================

export interface ActionResponse {
  ok: boolean;
  message: string;
}

// ============================================================================
// PHASE 1 — HARDWARE-KEY APPROVAL FLOW
// ============================================================================

export type ApprovalActionType = "ENABLE_LIVE" | "WITHDRAW" | "STRATEGY_PROMOTION" | "KILL_RESET";
export type ApprovalDeviceType = "YubiKey" | "SecureEnclave" | "WebAuthn";
export type ApprovalStatus = "PENDING" | "APPROVED" | "EXPIRED" | "REJECTED";

export interface ApprovalRequest {
  request_id: string;
  action_type: ApprovalActionType;
  created_at: string;
  expires_at: string;
  required_device: ApprovalDeviceType;
  status: ApprovalStatus;
  metadata?: Record<string, any>;
}

// ============================================================================
// PHASE 2 — INVESTOR MOBILE-ONLY SCHEMA
// ============================================================================

export interface InvestorMobilePanel {
  id: string;
  label: string;
  endpoint: string;
  poll_interval_ms: number;
  display?: string;
}

// ============================================================================
// PHASE 3 — CHAOS TEST VISUALIZER
// ============================================================================

export type ChaosFaultType = "LATENCY" | "BROKER_DOWN" | "PARTIAL_FILL" | "PRICE_GAP" | "NETWORK_PARTITION";
export type ChaosTestOutcome = "PASS" | "FAIL" | "TIMEOUT";

export interface ChaosTestRun {
  test_id: string;
  fault_type: ChaosFaultType;
  injected_at: string;
  duration_seconds: number;
  affected_components: string[];
  engine_response: string;
  outcome: ChaosTestOutcome;
  strategy_survivability?: Record<string, any>;
  broker_failover_paths?: Array<{
    timestamp: string;
    from_broker: string;
    to_broker: string;
    reason: string;
  }>;
  kill_switch_triggers?: Array<{
    timestamp: string;
    reason: string;
  }>;
}

// ============================================================================
// PHASE 4 — LLM STRATEGY SYNTHESIS UI
// ============================================================================

export type LifecycleState = "CANDIDATE" | "SHADOW_TESTING" | "PAPER_APPROVED" | "LIVE_APPROVED" | "ARCHIVED";

export interface SynthesizedStrategy {
  strategy_id: string;
  strategy_name: string;
  summary: string;
  hypothesis: string;
  backtest_results: {
    sharpe: number;
    max_drawdown: number;
    win_rate: number;
    profit_factor: number;
    expectancy: number;
    total_trades: number;
    final_return: number;
  };
  regimes_tested: string[];
  performance_score: number;
  promotion_eligibility: {
    eligible: boolean;
    reason: string;
    score: number;
  };
  lifecycle_state: LifecycleState;
  generated_at: string;
}

export interface PromotionReadinessScore {
  strategy_name: string;
  overall_score: number;
  performance_score: number;
  risk_score: number;
  stability_score: number;
  regime_robustness_score: number;
  timestamp: string;
  metrics_snapshot: Record<string, any>;
}

// ============================================================================
// PHASE 5 — TRADINGVIEW CHART BINDINGS
// ============================================================================

export type ChartId =
  | "equity_vs_benchmark"
  | "per_strategy_equity"
  | "drawdown"
  | "exposure_by_asset"
  | "execution_markers"
  | "shadow_vs_paper";

export interface ChartBinding {
  id: ChartId;
  label: string;
  endpoint: string;
  websocket?: string;
  data_fields: Record<string, string>;
}

export interface ChartData {
  timestamp: string;
  [key: string]: any;
}

export type ChartExportFormat = "PNG" | "PDF" | "SVG";

// ============================================================================
// PHASE 6 — SHADOW VS LIVE COMPARISON UI
// ============================================================================

export type PromotionStatus = "ELIGIBLE" | "NOT_ELIGIBLE" | "PENDING";

export interface PerformanceMetrics {
  equity: number;
  pnl: number;
  sharpe: number;
  drawdown: number;
  trades: number;
}

export interface ShadowComparison {
  strategy_id: string;
  strategy_name: string;
  paper_performance: PerformanceMetrics;
  live_performance: PerformanceMetrics;
  divergence_score: number;
  promotion_status: PromotionStatus;
  signal_agreement_percent: number;
}

// ============================================================================
// PHASE 7 — MOBILE FUNDING SCHEDULER
// ============================================================================

export type FundingDirection = "DEPOSIT" | "WITHDRAW";
export type FundingFrequency = "ONCE" | "DAILY" | "WEEKLY" | "MONTHLY";
export type FundingScheduleStatus = "PENDING" | "APPROVED" | "EXECUTED" | "CANCELLED";

export interface FundingSchedule {
  schedule_id: string;
  direction: FundingDirection;
  amount: number;
  frequency: FundingFrequency;
  execution_time: string;
  bank_link_id: string;
  approval_required: true;
  status: FundingScheduleStatus;
  created_at: string;
  approved_at?: string;
}
