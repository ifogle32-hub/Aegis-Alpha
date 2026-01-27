/**
 * RealtimePnLChart - Real-time PnL visualization
 * 
 * PHASE 1 — SHADOW BACKTESTING UI
 * 
 * SAFETY: SHADOW MODE ONLY - read-only visualization
 * Displays PnL over time with shadow vs paper comparison
 */

import React, { useState, useEffect, useMemo } from 'react';
import { View, Text, StyleSheet, Dimensions } from 'react-native';
import { useShadowWebSocket, ShadowMetrics } from '../hooks/useShadowWebSocket';
import { apiClient } from '../services/apiClient';

interface RealtimePnLChartProps {
  strategyId: string;
  feed?: 'rest' | 'realtime' | 'compare';
  compareMode?: 'shadow' | 'paper' | 'overlay';
  height?: number;
}

interface PnLDataPoint {
  timestamp: string;
  pnl: number;
  source: 'shadow' | 'paper';
}

export function RealtimePnLChart({ 
  strategyId, 
  feed = 'realtime',
  compareMode = 'shadow',
  height = 200 
}: RealtimePnLChartProps) {
  const [pnlData, setPnlData] = useState<PnLDataPoint[]>([]);
  const [paperData, setPaperData] = useState<PnLDataPoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  
  // WebSocket hook for real-time data
  const { data: wsData, isConnected, isReconnecting } = useShadowWebSocket();
  
  // Fetch initial REST data
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        // Fetch shadow performance
        const shadowPerf = await apiClient.getShadowPerformance(strategyId);
        if (shadowPerf && shadowPerf.pnl !== undefined) {
          setPnlData([{
            timestamp: shadowPerf.end_date || new Date().toISOString(),
            pnl: shadowPerf.pnl,
            source: 'shadow'
          }]);
        }
        
        // Fetch paper data if in compare mode
        if (compareMode === 'overlay' || compareMode === 'paper') {
          try {
            // Note: Paper endpoint would need to be implemented
            // For now, we'll use shadow data as placeholder
            // const paperPerf = await apiClient.getPaperPerformance(strategyId);
          } catch (e) {
            // Paper data not available - continue with shadow only
          }
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load initial data');
      }
    };
    
    if (feed === 'rest' || feed === 'compare') {
      fetchInitialData();
    }
  }, [strategyId, feed, compareMode]);
  
  // Update from WebSocket real-time data
  useEffect(() => {
    if (feed === 'realtime' || feed === 'compare') {
      if (wsData && wsData.metrics[strategyId]) {
        const metrics: ShadowMetrics = wsData.metrics[strategyId];
        const newPoint: PnLDataPoint = {
          timestamp: wsData.timestamp,
          pnl: metrics.pnl,
          source: 'shadow'
        };
        
        setPnlData(prev => {
          const updated = [...prev, newPoint];
          // Keep last 100 points
          return updated.slice(-100);
        });
      }
    }
  }, [wsData, strategyId, feed]);
  
  // Calculate chart statistics
  const stats = useMemo(() => {
    if (pnlData.length === 0) return null;
    
    const pnls = pnlData.map(d => d.pnl);
    return {
      current: pnls[pnls.length - 1],
      max: Math.max(...pnls),
      min: Math.min(...pnls),
      avg: pnls.reduce((a, b) => a + b, 0) / pnls.length
    };
  }, [pnlData]);
  
  // Render simple line chart (placeholder - would use a charting library like react-native-chart-kit)
  const renderChart = () => {
    if (pnlData.length === 0) {
      return (
        <View style={styles.chartContainer}>
          <Text style={styles.noDataText}>No data available</Text>
        </View>
      );
    }
    
    // Simple text-based chart visualization
    // In production, use react-native-chart-kit or similar
    return (
      <View style={styles.chartContainer}>
        <View style={styles.chartArea}>
          {stats && (
            <>
              <Text style={styles.chartTitle}>PnL Over Time</Text>
              <Text style={styles.chartValue}>
                Current: ${stats.current.toFixed(2)}
              </Text>
              <Text style={styles.chartValue}>
                Max: ${stats.max.toFixed(2)} | Min: ${stats.min.toFixed(2)}
              </Text>
              <Text style={styles.chartValue}>
                Avg: ${stats.avg.toFixed(2)}
              </Text>
            </>
          )}
        </View>
      </View>
    );
  };
  
  return (
    <View style={[styles.container, { height }]}>
      <View style={styles.header}>
        <Text style={styles.title}>PnL Chart - {strategyId}</Text>
        <View style={styles.badgeContainer}>
          {isReconnecting && (
            <Text style={styles.badgeReconnecting}>Reconnecting...</Text>
          )}
          {isConnected && feed === 'realtime' && (
            <Text style={styles.badgeLive}>● LIVE</Text>
          )}
          {feed === 'rest' && (
            <Text style={styles.badgeRest}>REST</Text>
          )}
        </View>
      </View>
      
      {/* Trust Label */}
      <View style={styles.trustLabel}>
        <Text style={styles.trustText}>
          SHADOW DATA — NO REAL TRADES
        </Text>
      </View>
      
      {error && (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}
      
      {renderChart()}
      
      {/* Status Footer */}
      <View style={styles.footer}>
        <Text style={styles.footerText}>
          {feed === 'realtime' && isConnected 
            ? `Live feed • Last update: ${new Date().toLocaleTimeString()}`
            : feed === 'rest'
            ? 'REST API • Static data'
            : 'Data unavailable'}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#1a1a1a',
    borderRadius: 8,
    padding: 16,
    marginVertical: 8,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  title: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  badgeContainer: {
    flexDirection: 'row',
    gap: 8,
  },
  badgeLive: {
    color: '#00ff00',
    fontSize: 12,
    fontWeight: '600',
  },
  badgeReconnecting: {
    color: '#ffaa00',
    fontSize: 12,
    fontWeight: '600',
  },
  badgeRest: {
    color: '#888',
    fontSize: 12,
    fontWeight: '600',
  },
  trustLabel: {
    backgroundColor: '#333',
    padding: 4,
    borderRadius: 4,
    marginBottom: 8,
  },
  trustText: {
    color: '#888',
    fontSize: 10,
    textAlign: 'center',
  },
  errorContainer: {
    backgroundColor: '#ff000020',
    padding: 8,
    borderRadius: 4,
    marginBottom: 8,
  },
  errorText: {
    color: '#ff6666',
    fontSize: 12,
  },
  chartContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  chartArea: {
    width: '100%',
    padding: 16,
  },
  chartTitle: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 8,
  },
  chartValue: {
    color: '#ccc',
    fontSize: 12,
    marginVertical: 2,
  },
  noDataText: {
    color: '#888',
    fontSize: 12,
  },
  footer: {
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#333',
  },
  footerText: {
    color: '#888',
    fontSize: 10,
    textAlign: 'center',
  },
});
