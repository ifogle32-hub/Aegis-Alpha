/**
 * Live Metrics Card Component - PHASE 4
 * 
 * Displays aggregated live metrics:
 * - Equity
 * - PnL
 * - Open positions count
 * - Active strategies
 * - Engine uptime
 * - Current mode
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { LiveMetrics } from '../types/api';

interface LiveMetricsCardProps {
  metrics: LiveMetrics;
  error: string | null;
}

export const LiveMetricsCard: React.FC<LiveMetricsCardProps> = ({
  metrics,
  error,
}) => {
  const formatCurrency = (value: number | null): string => {
    if (value === null) return 'N/A';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  };

  const formatUptime = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hours}h ${minutes}m ${secs}s`;
  };

  const formatPnL = (pnl: number): { text: string; color: string } => {
    if (pnl > 0) {
      return { text: `+${formatCurrency(pnl)}`, color: '#10B981' }; // Green
    } else if (pnl < 0) {
      return { text: formatCurrency(pnl), color: '#EF4444' }; // Red
    }
    return { text: formatCurrency(pnl), color: '#6B7280' }; // Gray
  };

  const pnlDisplay = formatPnL(metrics.totalPnL);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Live Metrics</Text>
      
      {/* Error indicator */}
      {error && (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>⚠️ {error}</Text>
        </View>
      )}

      {/* Metrics Grid */}
      <View style={styles.metricsGrid}>
        {/* Equity */}
        <View style={styles.metricItem}>
          <Text style={styles.metricLabel}>Equity</Text>
          <Text style={styles.metricValue}>
            {formatCurrency(metrics.equity)}
          </Text>
        </View>

        {/* Total P&L */}
        <View style={styles.metricItem}>
          <Text style={styles.metricLabel}>Total P&L</Text>
          <Text style={[styles.metricValue, { color: pnlDisplay.color }]}>
            {pnlDisplay.text}
          </Text>
        </View>

        {/* Open Positions */}
        <View style={styles.metricItem}>
          <Text style={styles.metricLabel}>Open Positions</Text>
          <Text style={styles.metricValue}>{metrics.openPositionsCount}</Text>
        </View>

        {/* Active Strategies */}
        <View style={styles.metricItem}>
          <Text style={styles.metricLabel}>Active Strategies</Text>
          <Text style={styles.metricValue}>{metrics.activeStrategiesCount}</Text>
        </View>

        {/* Engine Uptime */}
        <View style={styles.metricItem}>
          <Text style={styles.metricLabel}>Engine Uptime</Text>
          <Text style={styles.metricValue}>
            {formatUptime(metrics.engineUptime)}
          </Text>
        </View>

        {/* Current Mode */}
        <View style={styles.metricItem}>
          <Text style={styles.metricLabel}>Mode</Text>
          <Text style={styles.metricValue}>{metrics.currentMode}</Text>
        </View>
      </View>

      {/* Last updated timestamp */}
      {metrics.lastUpdated && (
        <Text style={styles.lastUpdated}>
          Updated: {metrics.lastUpdated.toLocaleTimeString()}
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
  title: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1F2937',
    marginBottom: 12,
  },
  errorContainer: {
    marginBottom: 12,
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
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  metricItem: {
    flex: 1,
    minWidth: '48%',
    padding: 12,
    backgroundColor: '#F9FAFB',
    borderRadius: 8,
  },
  metricLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 4,
    fontWeight: '500',
  },
  metricValue: {
    fontSize: 16,
    fontWeight: '700',
    color: '#1F2937',
  },
  lastUpdated: {
    marginTop: 12,
    fontSize: 10,
    color: '#9CA3AF',
    textAlign: 'right',
  },
});

