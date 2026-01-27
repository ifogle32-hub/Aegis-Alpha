/**
 * ShadowDashboard - Main shadow strategy monitoring dashboard
 * 
 * PHASE 1 — SHADOW BACKTESTING DASHBOARD
 * 
 * SAFETY: SHADOW MODE ONLY - read-only visualization
 * Features:
 * - Real-time WebSocket feeds
 * - REST + WebSocket hybrid data pipeline
 * - Compare Mode (Shadow vs Paper)
 * - Mobile-optimized tabs
 */

import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { RealtimePnLChart } from './RealtimePnLChart';
import { useShadowWebSocket } from '../hooks/useShadowWebSocket';
import { apiClient } from '../services/apiClient';
import { useHealthWebSocket } from '../hooks/useHealthWebSocket';

type TabType = 'overview' | 'signals' | 'realtime' | 'compare';
type CompareMode = 'shadow' | 'paper' | 'overlay';

export function ShadowDashboard() {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [compareMode, setCompareMode] = useState<CompareMode>('shadow');
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
  const [strategies, setStrategies] = useState<any[]>([]);
  
  const { health } = useHealthWebSocket();
  const { data: shadowData, isConnected, isReconnecting } = useShadowWebSocket();
  
  // Load strategies on mount
  useEffect(() => {
    const loadStrategies = async () => {
      try {
        const data = await apiClient.getShadowStrategies();
        setStrategies(data);
        if (data.length > 0 && !selectedStrategy) {
          setSelectedStrategy(data[0].id);
        }
      } catch (err) {
        console.error('Error loading strategies:', err);
      }
    };
    loadStrategies();
  }, []);
  
  const renderTabs = () => (
    <View style={styles.tabsContainer}>
      {(['overview', 'signals', 'realtime', 'compare'] as TabType[]).map(tab => (
        <TouchableOpacity
          key={tab}
          style={[styles.tab, activeTab === tab && styles.tabActive]}
          onPress={() => setActiveTab(tab)}
        >
          <Text style={[styles.tabText, activeTab === tab && styles.tabTextActive]}>
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </Text>
        </TouchableOpacity>
      ))}
    </View>
  );
  
  const renderHeader = () => (
    <View style={styles.header}>
      <Text style={styles.headerTitle}>Shadow Strategy Monitor</Text>
      <View style={styles.badgeContainer}>
        <View style={[styles.badge, styles.badgeShadow]}>
          <Text style={styles.badgeText}>SHADOW</Text>
        </View>
        {health && (
          <View style={[styles.badge, health.status === 'RUNNING' ? styles.badgeOk : styles.badgeWarn]}>
            <Text style={styles.badgeText}>
              {health.status === 'RUNNING' ? '●' : '○'} {health.status}
            </Text>
          </View>
        )}
      </View>
    </View>
  );
  
  const renderCompareModeSelector = () => {
    if (activeTab !== 'compare') return null;
    
    return (
      <View style={styles.compareSelector}>
        <Text style={styles.compareLabel}>Mode:</Text>
        {(['shadow', 'paper', 'overlay'] as CompareMode[]).map(mode => (
          <TouchableOpacity
            key={mode}
            style={[styles.compareButton, compareMode === mode && styles.compareButtonActive]}
            onPress={() => setCompareMode(mode)}
          >
            <Text style={[styles.compareButtonText, compareMode === mode && styles.compareButtonTextActive]}>
              {mode.charAt(0).toUpperCase() + mode.slice(1)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
    );
  };
  
  const renderTrustLabels = () => (
    <View style={styles.trustContainer}>
      <Text style={styles.trustText}>SHADOW DATA — NO REAL TRADES</Text>
      {compareMode === 'overlay' && (
        <Text style={styles.trustTextPaper}>PAPER COMPARISON — SIMULATED EXECUTION</Text>
      )}
      <Text style={styles.trustTimestamp}>
        Last Updated: {shadowData?.timestamp ? new Date(shadowData.timestamp).toLocaleTimeString() : 'N/A'}
      </Text>
      {health && (
        <Text style={styles.trustHeartbeat}>
          Heartbeat: {health.heartbeat_age ? `${health.heartbeat_age.toFixed(1)}s ago` : 'N/A'}
        </Text>
      )}
    </View>
  );
  
  const renderContent = () => {
    if (!selectedStrategy) {
      return (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>No strategy selected</Text>
        </View>
      );
    }
    
    switch (activeTab) {
      case 'overview':
        return (
          <ScrollView style={styles.content}>
            <Text style={styles.sectionTitle}>Strategy Overview</Text>
            {shadowData?.metrics[selectedStrategy] && (
              <View style={styles.metricsCard}>
                <Text style={styles.metricLabel}>PnL: ${shadowData.metrics[selectedStrategy].pnl.toFixed(2)}</Text>
                <Text style={styles.metricLabel}>Sharpe: {shadowData.metrics[selectedStrategy].sharpe.toFixed(2)}</Text>
                <Text style={styles.metricLabel}>Max DD: {(shadowData.metrics[selectedStrategy].max_drawdown * 100).toFixed(2)}%</Text>
                <Text style={styles.metricLabel}>Trades: {shadowData.metrics[selectedStrategy].trade_count}</Text>
              </View>
            )}
          </ScrollView>
        );
      
      case 'signals':
        return (
          <ScrollView style={styles.content}>
            <Text style={styles.sectionTitle}>Recent Signals</Text>
            {shadowData?.signals.filter(s => s.strategy_id === selectedStrategy).slice(0, 20).map((signal, idx) => (
              <View key={idx} style={styles.signalCard}>
                <Text style={styles.signalSide}>{signal.side}</Text>
                <Text style={styles.signalConfidence}>{(signal.confidence * 100).toFixed(0)}%</Text>
                <Text style={styles.signalTime}>{new Date(signal.timestamp).toLocaleTimeString()}</Text>
              </View>
            ))}
          </ScrollView>
        );
      
      case 'realtime':
        return (
          <ScrollView style={styles.content}>
            {isReconnecting && (
              <View style={styles.reconnectingBanner}>
                <Text style={styles.reconnectingText}>Live feed paused. Reconnecting...</Text>
              </View>
            )}
            <RealtimePnLChart 
              strategyId={selectedStrategy} 
              feed="realtime"
              compareMode={compareMode}
            />
          </ScrollView>
        );
      
      case 'compare':
        return (
          <ScrollView style={styles.content}>
            {isReconnecting && (
              <View style={styles.reconnectingBanner}>
                <Text style={styles.reconnectingText}>Live feed paused. Reconnecting...</Text>
              </View>
            )}
            <RealtimePnLChart 
              strategyId={selectedStrategy} 
              feed="compare"
              compareMode={compareMode}
            />
          </ScrollView>
        );
      
      default:
        return null;
    }
  };
  
  return (
    <View style={styles.container}>
      {renderHeader()}
      {renderTrustLabels()}
      {renderTabs()}
      {renderCompareModeSelector()}
      {renderContent()}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    backgroundColor: '#1a1a1a',
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  headerTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
  badgeContainer: {
    flexDirection: 'row',
    gap: 8,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  badgeShadow: {
    backgroundColor: '#333',
  },
  badgeOk: {
    backgroundColor: '#00ff0020',
  },
  badgeWarn: {
    backgroundColor: '#ffaa0020',
  },
  badgeText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: '600',
  },
  trustContainer: {
    backgroundColor: '#1a1a1a',
    padding: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  trustText: {
    color: '#888',
    fontSize: 10,
    textAlign: 'center',
  },
  trustTextPaper: {
    color: '#ffaa00',
    fontSize: 10,
    textAlign: 'center',
    marginTop: 4,
  },
  trustTimestamp: {
    color: '#666',
    fontSize: 9,
    textAlign: 'center',
    marginTop: 4,
  },
  trustHeartbeat: {
    color: '#666',
    fontSize: 9,
    textAlign: 'center',
    marginTop: 2,
  },
  tabsContainer: {
    flexDirection: 'row',
    backgroundColor: '#1a1a1a',
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  tab: {
    flex: 1,
    paddingVertical: 12,
    alignItems: 'center',
    borderBottomWidth: 2,
    borderBottomColor: 'transparent',
  },
  tabActive: {
    borderBottomColor: '#00ff00',
  },
  tabText: {
    color: '#888',
    fontSize: 12,
    fontWeight: '500',
  },
  tabTextActive: {
    color: '#fff',
    fontWeight: '600',
  },
  compareSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: '#1a1a1a',
    gap: 8,
  },
  compareLabel: {
    color: '#fff',
    fontSize: 12,
    marginRight: 8,
  },
  compareButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 4,
    backgroundColor: '#333',
  },
  compareButtonActive: {
    backgroundColor: '#00ff0020',
  },
  compareButtonText: {
    color: '#888',
    fontSize: 12,
  },
  compareButtonTextActive: {
    color: '#00ff00',
  },
  content: {
    flex: 1,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyText: {
    color: '#888',
    fontSize: 14,
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
    padding: 16,
  },
  metricsCard: {
    backgroundColor: '#1a1a1a',
    padding: 16,
    margin: 16,
    borderRadius: 8,
    gap: 8,
  },
  metricLabel: {
    color: '#fff',
    fontSize: 14,
  },
  signalCard: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#1a1a1a',
    padding: 12,
    marginHorizontal: 16,
    marginVertical: 4,
    borderRadius: 4,
  },
  signalSide: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  signalConfidence: {
    color: '#00ff00',
    fontSize: 12,
  },
  signalTime: {
    color: '#888',
    fontSize: 11,
  },
  reconnectingBanner: {
    backgroundColor: '#ffaa0020',
    padding: 12,
    margin: 16,
    borderRadius: 4,
  },
  reconnectingText: {
    color: '#ffaa00',
    fontSize: 12,
    textAlign: 'center',
  },
});
