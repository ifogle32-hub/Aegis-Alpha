/**
 * Shadow vs Live Comparison Card Component
 * 
 * OBSERVATIONAL ONLY - Read-only display of shadow vs execution comparison
 * UI must NEVER influence execution.
 * 
 * Displays:
 * - Equity curve (Shadow vs Paper vs Live)
 * - PnL delta over time
 * - Per-strategy accuracy
 * - Execution latency
 * - Divergence warnings
 */

import React from 'react';
import { View, Text, StyleSheet, ScrollView, Platform } from 'react-native';

interface ShadowComparisonData {
  strategy_deltas: Record<string, {
    shadow_pnl: number;
    execution_pnl: number;
    pnl_delta: number;
  }>;
  aggregate_shadow_pnl: number;
  aggregate_execution_pnl: number;
  aggregate_pnl_delta: number;
  slippage: {
    avg: number;
    max: number;
    count: number;
  };
  execution_latency: {
    avg_ms: number;
    max_ms: number;
    count: number;
  };
  divergence_alerts_count: number;
  timestamp: string;
}

interface ShadowComparisonCardProps {
  data: ShadowComparisonData | null;
  isLoading?: boolean;
  error?: string | null;
}

export const ShadowComparisonCard: React.FC<ShadowComparisonCardProps> = ({
  data,
  isLoading = false,
  error = null,
}) => {
  if (isLoading && !data) {
    return (
      <View style={styles.container}>
        <Text style={styles.loadingText}>Loading shadow comparison...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.container}>
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>⚠️ {error}</Text>
        </View>
      </View>
    );
  }

  if (!data) {
    return (
      <View style={styles.container}>
        <Text style={styles.emptyText}>No shadow comparison data available</Text>
      </View>
    );
  }

  const formatCurrency = (value: number): string => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}$${value.toFixed(2)}`;
  };

  const formatPercentage = (value: number): string => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${(value * 100).toFixed(2)}%`;
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>📊 Shadow vs Live Comparison</Text>
      
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Aggregate Summary */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Aggregate Equity</Text>
          <View style={styles.metricRow}>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>Shadow PnL</Text>
              <Text style={[styles.metricValue, { color: '#3B82F6' }]}>
                {formatCurrency(data.aggregate_shadow_pnl)}
              </Text>
            </View>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>Execution PnL</Text>
              <Text style={[styles.metricValue, { 
                color: data.aggregate_execution_pnl >= 0 ? '#10B981' : '#EF4444' 
              }]}>
                {formatCurrency(data.aggregate_execution_pnl)}
              </Text>
            </View>
          </View>
          <View style={styles.deltaRow}>
            <Text style={styles.deltaLabel}>PnL Delta:</Text>
            <Text style={[styles.deltaValue, {
              color: data.aggregate_pnl_delta >= 0 ? '#10B981' : '#EF4444'
            }]}>
              {formatCurrency(data.aggregate_pnl_delta)}
            </Text>
          </View>
        </View>

        {/* Per-Strategy Deltas */}
        {Object.keys(data.strategy_deltas).length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>🎯 Per-Strategy Accuracy</Text>
            {Object.entries(data.strategy_deltas).map(([strategy, delta]) => (
              <View key={strategy} style={styles.strategyRow}>
                <Text style={styles.strategyName}>{strategy}</Text>
                <View style={styles.strategyMetrics}>
                  <Text style={styles.strategyMetric}>
                    Shadow: {formatCurrency(delta.shadow_pnl)}
                  </Text>
                  <Text style={styles.strategyMetric}>
                    Exec: {formatCurrency(delta.execution_pnl)}
                  </Text>
                  <Text style={[styles.strategyDelta, {
                    color: delta.pnl_delta >= 0 ? '#10B981' : '#EF4444'
                  }]}>
                    Δ: {formatCurrency(delta.pnl_delta)}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        )}

        {/* Execution Metrics */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>⏱️ Execution Metrics</Text>
          <View style={styles.metricRow}>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>Avg Latency</Text>
              <Text style={styles.metricValue}>
                {data.execution_latency.avg_ms.toFixed(2)}ms
              </Text>
            </View>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>Max Latency</Text>
              <Text style={styles.metricValue}>
                {data.execution_latency.max_ms.toFixed(2)}ms
              </Text>
            </View>
          </View>
          <View style={styles.metricRow}>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>Avg Slippage</Text>
              <Text style={styles.metricValue}>
                {formatCurrency(data.slippage.avg)}
              </Text>
            </View>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>Max Slippage</Text>
              <Text style={[styles.metricValue, {
                color: Math.abs(data.slippage.max) > 0.01 ? '#EF4444' : '#6B7280'
              }]}>
                {formatCurrency(data.slippage.max)}
              </Text>
            </View>
          </View>
        </View>

        {/* Divergence Alerts */}
        {data.divergence_alerts_count > 0 && (
          <View style={styles.section}>
            <View style={styles.divergenceContainer}>
              <Text style={styles.divergenceTitle}>
                ⚠️ Divergence Alerts: {data.divergence_alerts_count}
              </Text>
              <Text style={styles.divergenceText}>
                Significant differences detected between shadow and execution.
                Review export data for details.
              </Text>
            </View>
          </View>
        )}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    minHeight: 200,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 3,
      },
    }),
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1F2937',
    marginBottom: 16,
  },
  scrollView: {
    maxHeight: 400,
  },
  section: {
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
    marginBottom: 12,
  },
  metricRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  metricItem: {
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
  deltaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
  },
  deltaLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
    marginRight: 8,
  },
  deltaValue: {
    fontSize: 18,
    fontWeight: '700',
  },
  strategyRow: {
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  strategyName: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 4,
  },
  strategyMetrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  strategyMetric: {
    fontSize: 12,
    color: '#6B7280',
  },
  strategyDelta: {
    fontSize: 12,
    fontWeight: '600',
  },
  divergenceContainer: {
    padding: 12,
    backgroundColor: '#FEF2F2',
    borderRadius: 8,
    borderLeftWidth: 4,
    borderLeftColor: '#EF4444',
  },
  divergenceTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#991B1B',
    marginBottom: 4,
  },
  divergenceText: {
    fontSize: 12,
    color: '#991B1B',
    lineHeight: 18,
  },
  loadingText: {
    fontSize: 14,
    color: '#6B7280',
    textAlign: 'center',
    padding: 20,
  },
  errorContainer: {
    padding: 12,
    backgroundColor: '#FEF2F2',
    borderRadius: 8,
    borderLeftWidth: 4,
    borderLeftColor: '#EF4444',
  },
  errorText: {
    fontSize: 12,
    color: '#991B1B',
  },
  emptyText: {
    fontSize: 14,
    color: '#9CA3AF',
    textAlign: 'center',
    padding: 20,
  },
});
