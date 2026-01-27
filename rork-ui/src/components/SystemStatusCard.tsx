/**
 * System Status Card Component
 * 
 * Displays current system state with visual indicators.
 * PHASE 1: Never shows UNKNOWN during normal operation
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { SystemState } from '../types/api';
import { getStateDisplay } from '../utils/stateNormalizer';

interface SystemStatusCardProps {
  state: SystemState;
  mode: string;
  uptime: number;
  heartbeat: string | null;
  error: string | null;
  lastUpdated: Date | null;
  // PHASE 7: Health-based badge props (from WebSocket)
  healthStatus?: "RUNNING" | "STALE" | "FROZEN";
  loopTick?: number;
  loopTickAge?: number;
  heartbeatAge?: number;
  broker?: string;
  watchdog?: string;
  isConnected?: boolean;
  isReconnecting?: boolean;
}

export const SystemStatusCard: React.FC<SystemStatusCardProps> = ({
  state,
  mode,
  uptime,
  heartbeat,
  error,
  lastUpdated,
  healthStatus,
  loopTick,
  loopTickAge,
  heartbeatAge,
  broker,
  watchdog,
  isConnected,
  isReconnecting,
}) => {
  const stateDisplay = getStateDisplay(state);

  /**
   * PHASE 7 — UI BADGE LOGIC (LIVE)
   * 
   * Badge logic driven by WebSocket data:
   * - GREEN: heartbeat_age < 10s AND loop_tick_age < 10s
   * - YELLOW: heartbeat_age >= 10s AND loop_tick_age < 30s
   * - RED: loop_tick_age >= 30s
   */
  const getEngineBadge = (): { badge: string; color: string; label: string } => {
    if (!healthStatus || loopTickAge === undefined || heartbeatAge === undefined) {
      return { badge: "⚪", color: '#9CA3AF', label: 'UNKNOWN' };
    }
    
    // PHASE 7: Badge logic based on heartbeat_age and loop_tick_age
    if (heartbeatAge < 10 && loopTickAge < 10) {
      return { badge: "🟢", color: '#10B981', label: 'RUNNING' };
    } else if (heartbeatAge >= 10 && loopTickAge < 30) {
      return { badge: "🟡", color: '#F59E0B', label: 'STALE' };
    } else {
      return { badge: "🔴", color: '#EF4444', label: 'FROZEN' };
    }
  };

  const engineBadge = getEngineBadge();

  const formatUptime = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hours}h ${minutes}m ${secs}s`;
  };

  const formatHeartbeat = (timestamp: string | null): string => {
    if (!timestamp) return 'N/A';
    // PHASE 5: Display heartbeat age if available
    if (typeof timestamp === 'string' && timestamp.includes('s')) {
      return `Age: ${timestamp}`;
    }
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString();
    } catch {
      return 'Invalid';
    }
  };

  return (
    <View style={styles.container}>
      {/* PHASE 7: Engine Status Badge (WebSocket-based) */}
      <View style={styles.stateContainer}>
        <View
          style={[
            styles.healthBadge,
            { backgroundColor: engineBadge.color },
          ]}
        >
          <Text style={styles.badgeText}>{engineBadge.badge}</Text>
          <Text style={styles.badgeLabel}>{engineBadge.label}</Text>
        </View>
        <View style={styles.stateInfo}>
          <Text style={styles.modeText}>Mode: {mode}</Text>
          {loopTick !== undefined && (
            <Text style={styles.loopTickText}>Loop Tick: {loopTick.toLocaleString()}</Text>
          )}
          {isReconnecting && (
            <Text style={styles.reconnectingText}>Reconnecting...</Text>
          )}
          {!isConnected && !isReconnecting && (
            <Text style={styles.disconnectedText}>Disconnected</Text>
          )}
        </View>
      </View>
      
      {/* PHASE 7: Real-time Health Metrics (from WebSocket) */}
      {(loopTickAge !== undefined || heartbeatAge !== undefined) && (
        <View style={styles.healthMetricsContainer}>
          {loopTickAge !== undefined && (
            <View style={styles.healthMetric}>
              <Text style={styles.healthMetricLabel}>Loop Tick Age</Text>
              <Text style={styles.healthMetricValue}>{loopTickAge.toFixed(1)}s</Text>
            </View>
          )}
          {heartbeatAge !== undefined && (
            <View style={styles.healthMetric}>
              <Text style={styles.healthMetricLabel}>Heartbeat Age</Text>
              <Text style={styles.healthMetricValue}>{heartbeatAge.toFixed(1)}s</Text>
            </View>
          )}
          {broker && broker !== 'NONE' && (
            <View style={styles.healthMetric}>
              <Text style={styles.healthMetricLabel}>Broker</Text>
              <Text style={styles.healthMetricValue}>{mode === 'RESEARCH' || mode === 'TRAINING' ? 'PAPER' : broker}</Text>
            </View>
          )}
          {watchdog && (
            <View style={styles.healthMetric}>
              <Text style={styles.healthMetricLabel}>Watchdog</Text>
              <Text style={[styles.healthMetricValue, { color: engineBadge.color }]}>{watchdog}</Text>
            </View>
          )}
        </View>
      )}

      {/* Metrics */}
      <View style={styles.metricsContainer}>
        <View style={styles.metric}>
          <Text style={styles.metricLabel}>Uptime</Text>
          <Text style={styles.metricValue}>{formatUptime(uptime)}</Text>
        </View>
        <View style={styles.metric}>
          <Text style={styles.metricLabel}>Heartbeat</Text>
          <Text style={styles.metricValue}>{formatHeartbeat(heartbeat)}</Text>
        </View>
        {broker && broker !== 'NONE' && (
          <View style={styles.metric}>
            <Text style={styles.metricLabel}>Broker</Text>
            <Text style={styles.metricValue}>{broker}</Text>
          </View>
        )}
        {watchdog && (
          <View style={styles.metric}>
            <Text style={styles.metricLabel}>Watchdog</Text>
            <Text style={[styles.metricValue, { color: engineBadge.color }]}>
              {watchdog}
            </Text>
          </View>
        )}
      </View>

      {/* PHASE 6: Network error indicator (subtle, not UNKNOWN) */}
      {error && (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>⚠️ {error}</Text>
        </View>
      )}

      {/* PHASE 7: Security banner */}
      <View style={styles.securityBanner}>
        <Text style={styles.securityText}>
          🔒 Monitoring & Funding Only — Trading Controlled Server-Side
        </Text>
      </View>

      {/* Last updated timestamp */}
      {lastUpdated && (
        <Text style={styles.lastUpdated}>
          Updated: {lastUpdated.toLocaleTimeString()}
        </Text>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  stateContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  healthBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 20,
    marginRight: 12,
  },
  badgeText: {
    fontSize: 20,
    marginRight: 6,
  },
  badgeLabel: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '700',
  },
  stateInfo: {
    flex: 1,
  },
  modeText: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 4,
  },
  loopTickText: {
    fontSize: 12,
    color: '#9CA3AF',
  },
  metricsContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  metric: {
    flex: 1,
  },
  metricLabel: {
    fontSize: 12,
    color: '#9CA3AF',
    marginBottom: 4,
  },
  metricValue: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
  },
  errorContainer: {
    marginTop: 12,
    padding: 8,
    backgroundColor: '#FEF2F2',
    borderRadius: 6,
    borderLeftWidth: 3,
    borderLeftColor: '#EF4444',
  },
  errorText: {
    fontSize: 12,
    color: '#991B1B',
  },
  securityBanner: {
    marginTop: 12,
    padding: 10,
    backgroundColor: '#FEF3C7',
    borderRadius: 6,
    borderLeftWidth: 3,
    borderLeftColor: '#F59E0B',
  },
  securityText: {
    fontSize: 11,
    color: '#92400E',
    fontWeight: '500',
    textAlign: 'center',
  },
  lastUpdated: {
    marginTop: 8,
    fontSize: 10,
    color: '#9CA3AF',
    textAlign: 'right',
  },
  healthMetricsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
  },
  reconnectingText: {
    fontSize: 12,
    color: '#F59E0B',
    fontStyle: 'italic',
  },
  disconnectedText: {
    fontSize: 12,
    color: '#9CA3AF',
    fontStyle: 'italic',
  },
  healthMetric: {
    width: '50%',
    marginBottom: 8,
  },
  healthMetricLabel: {
    fontSize: 11,
    color: '#6B7280',
    marginBottom: 2,
  },
  healthMetricValue: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
  },
});

