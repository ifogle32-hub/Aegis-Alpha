/**
 * Strategy Performance Panel Component
 * 
 * PHASE 7 — MULTI-STRATEGY VIEW
 * 
 * REGRESSION LOCK — mobile charts are read-only
 * REGRESSION LOCK — no persistence
 * 
 * Displays all strategies with their performance metrics and PnL charts.
 * 
 * RULE: NO gesture trading, NO editing
 */

import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useStrategyPerformance } from '../hooks/useStrategyPerformance';
import { StrategyChart } from './StrategyChart';

export const StrategyPerformancePanel: React.FC = () => {
  const { data, isConnected, error, lastUpdated, reconnect } = useStrategyPerformance();
  
  // Get strategy names sorted alphabetically
  const strategyNames = Object.keys(data).sort();
  
  // PHASE 8: Handle WebSocket disconnection warning
  const showDisconnectedWarning = !isConnected && strategyNames.length > 0;
  
  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Strategy Performance</Text>
        {lastUpdated && (
          <Text style={styles.lastUpdated}>
            Updated: {lastUpdated.toLocaleTimeString()}
          </Text>
        )}
      </View>
      
      {/* PHASE 8: Connection status indicator */}
      <View style={styles.statusBar}>
        <View
          style={[
            styles.statusIndicator,
            { backgroundColor: isConnected ? '#10B981' : '#EF4444' },
          ]}
        />
        <Text style={styles.statusText}>
          {isConnected ? 'Connected' : 'Disconnected'}
        </Text>
        {!isConnected && (
          <TouchableOpacity onPress={reconnect} style={styles.reconnectButton}>
            <Text style={styles.reconnectText}>Reconnect</Text>
          </TouchableOpacity>
        )}
      </View>
      
      {/* PHASE 8: Error message */}
      {error && (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>⚠️ {error}</Text>
        </View>
      )}
      
      {/* PHASE 8: Disconnected warning (show last known data) */}
      {showDisconnectedWarning && (
        <View style={styles.warningContainer}>
          <Text style={styles.warningText}>
            Showing last known data. Reconnecting...
          </Text>
        </View>
      )}
      
      {/* PHASE 8: Empty state */}
      {strategyNames.length === 0 && !error && (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>No strategies available</Text>
          <Text style={styles.emptySubtext}>
            {isConnected ? 'Waiting for data...' : 'Connecting...'}
          </Text>
        </View>
      )}
      
      {/* Strategy cards */}
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {strategyNames.map((strategyName) => {
          const strategyData = data[strategyName];
          
          // PHASE 8: Skip invalid strategy data
          if (!strategyData) {
            return null;
          }
          
          return (
            <View key={strategyName} style={styles.strategyCard}>
              {/* Strategy header */}
              <View style={styles.strategyHeader}>
                <Text style={styles.strategyName}>{strategyName}</Text>
                <View
                  style={[
                    styles.pnlBadge,
                    {
                      backgroundColor:
                        strategyData.pnl_total >= 0 ? '#D1FAE5' : '#FEE2E2',
                    },
                  ]}
                >
                  <Text
                    style={[
                      styles.pnlText,
                      {
                        color: strategyData.pnl_total >= 0 ? '#065F46' : '#991B1B',
                      },
                    ]}
                  >
                    {strategyData.pnl_total >= 0 ? '+' : ''}
                    {strategyData.pnl_total.toFixed(2)}
                  </Text>
                </View>
              </View>
              
              {/* Strategy metrics */}
              <View style={styles.metricsRow}>
                <View style={styles.metricItem}>
                  <Text style={styles.metricLabel}>Allocation</Text>
                  <Text style={styles.metricValue}>
                    {(strategyData.allocation_weight * 100).toFixed(1)}%
                  </Text>
                </View>
                <View style={styles.metricItem}>
                  <Text style={styles.metricLabel}>Trades</Text>
                  <Text style={styles.metricValue}>{strategyData.trades}</Text>
                </View>
              </View>
              
              {/* PHASE 8: Strategy chart with fallback handling */}
              <View style={styles.chartContainer}>
                <StrategyChart
                  series={strategyData.timeseries}
                  height={120}
                  smooth={true}
                />
              </View>
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  header: {
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: '#1F2937',
    marginBottom: 4,
  },
  lastUpdated: {
    fontSize: 12,
    color: '#9CA3AF',
  },
  statusBar: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: '#F9FAFB',
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  statusIndicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  statusText: {
    fontSize: 12,
    color: '#6B7280',
    flex: 1,
  },
  reconnectButton: {
    paddingHorizontal: 12,
    paddingVertical: 4,
    backgroundColor: '#3B82F6',
    borderRadius: 4,
  },
  reconnectText: {
    fontSize: 12,
    color: '#FFFFFF',
    fontWeight: '600',
  },
  errorContainer: {
    margin: 12,
    padding: 12,
    backgroundColor: '#FEF2F2',
    borderRadius: 6,
    borderLeftWidth: 3,
    borderLeftColor: '#EF4444',
  },
  errorText: {
    fontSize: 12,
    color: '#991B1B',
  },
  warningContainer: {
    margin: 12,
    padding: 12,
    backgroundColor: '#FEF3C7',
    borderRadius: 6,
    borderLeftWidth: 3,
    borderLeftColor: '#F59E0B',
  },
  warningText: {
    fontSize: 12,
    color: '#92400E',
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  emptyText: {
    fontSize: 16,
    color: '#6B7280',
    marginBottom: 8,
  },
  emptySubtext: {
    fontSize: 12,
    color: '#9CA3AF',
  },
  scrollView: {
    flex: 1,
  },
  strategyCard: {
    margin: 12,
    padding: 16,
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  strategyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  strategyName: {
    fontSize: 16,
    fontWeight: '700',
    color: '#1F2937',
    flex: 1,
  },
  pnlBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  pnlText: {
    fontSize: 14,
    fontWeight: '700',
  },
  metricsRow: {
    flexDirection: 'row',
    marginBottom: 12,
    gap: 12,
  },
  metricItem: {
    flex: 1,
    padding: 8,
    backgroundColor: '#F9FAFB',
    borderRadius: 6,
  },
  metricLabel: {
    fontSize: 11,
    color: '#6B7280',
    marginBottom: 4,
    fontWeight: '500',
  },
  metricValue: {
    fontSize: 14,
    fontWeight: '700',
    color: '#1F2937',
  },
  chartContainer: {
    marginTop: 8,
  },
});
