/**
 * Control Screen - Main UI for Sentinel X Rork (Mobile Hardened)
 * 
 * Integrates all hardening phases:
 * - PHASE 1: Mobile debounce
 * - PHASE 2: Latency smoothing (optimistic UI)
 * - PHASE 3: Status stability guards
 * - PHASE 4: Auth handling
 * - PHASE 5: Mobile UX safety
 * - PHASE 6: Network resilience
 */

import React, { useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  ScrollView,
  RefreshControl,
  Alert,
  Platform,
} from 'react-native';
import { useSystemStatus } from '../hooks/useSystemStatus';
import { useLiveMetrics } from '../hooks/useLiveMetrics';
import { useShadowComparison } from '../hooks/useShadowComparison';
import { useHealthWebSocket } from '../hooks/useHealthWebSocket';
import { SystemStatusCard } from '../components/SystemStatusCard';
import { LiveMetricsCard } from '../components/LiveMetricsCard';
import { ShadowComparisonCard } from '../components/ShadowComparisonCard';
import { ControlButtons } from '../components/ControlButtons';
import { Button } from 'react-native';
import { apiClient } from '../services/apiClient';

export const ControlScreen: React.FC = () => {
  const {
    state,
    mode,
    modeLabel,
    uptime,
    heartbeat,
    isLoading,
    error,
    lastUpdated,
    isActionInFlight,
    lockedActions,
    authState,
    biometricAvailable,
    isBiometricLockedOut,
    refresh,
    startEngine,
    stopEngine,
    killEngine,
    isButtonDisabled,
  } = useSystemStatus();

  // PHASE 6 — RORK REAL-TIME CONSUMPTION
  // Connect to WebSocket health stream for real-time updates
  const {
    health: healthSnapshot,
    isConnected: isHealthConnected,
    isReconnecting: isHealthReconnecting,
    error: healthError,
  } = useHealthWebSocket('http://127.0.0.1:8000');

  // PHASE 4: Live metrics
  const {
    metrics: liveMetrics,
    isLoading: isMetricsLoading,
    error: metricsError,
    refresh: refreshMetrics,
  } = useLiveMetrics();

  // SHADOW COMPARISON: Shadow vs Live comparison (observational only)
  const {
    data: shadowComparison,
    isLoading: isShadowLoading,
    error: shadowError,
    refresh: refreshShadow,
  } = useShadowComparison();

  /**
   * Handle START button press
   * PHASE 1: Debounce handled in hook
   * PHASE 2: Optimistic update handled in hook
   */
  const handleStart = useCallback(async () => {
    try {
      await startEngine();
    } catch (err: any) {
      // PHASE 2: Non-blocking warning (toast style)
      Alert.alert(
        'Start Failed',
        err.message || 'Failed to start engine',
        [{ text: 'OK', style: 'default' }],
        { cancelable: true }
      );
    }
  }, [startEngine]);

  /**
   * Handle STOP button press
   */
  const handleStop = useCallback(async () => {
    try {
      await stopEngine();
    } catch (err: any) {
      Alert.alert(
        'Stop Failed',
        err.message || 'Failed to stop engine',
        [{ text: 'OK', style: 'default' }],
        { cancelable: true }
      );
    }
  }, [stopEngine]);

  /**
   * Handle KILL button press with confirmation
   * PHASE 3: Two-step confirmation required
   */
  const handleKill = useCallback(() => {
    Alert.alert(
      '⚠️ Emergency Kill',
      'This will immediately stop trading and cancel all orders.',
      [
        {
          text: 'Cancel',
          style: 'cancel',
        },
        {
          text: 'KILL',
          style: 'destructive',
          onPress: async () => {
            try {
              await killEngine();
            } catch (err: any) {
              Alert.alert(
                'Kill Failed',
                err.message || 'Failed to trigger kill switch',
                [{ text: 'OK', style: 'default' }],
                { cancelable: true }
              );
            }
          },
        },
      ],
      { cancelable: true }
    );
  }, [killEngine]);

  /**
   * Handle TEST ORDER button press
   */
  const handleTestOrder = useCallback(async () => {
    try {
      await fetch("http://127.0.0.1:8000/test/order", { method: "POST" });
    } catch (err: any) {
      Alert.alert(
        'Test Order Failed',
        err.message || 'Failed to execute test order',
        [{ text: 'OK', style: 'default' }],
        { cancelable: true }
      );
    }
  }, []);

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl
            refreshing={isLoading && !isActionInFlight}
            onRefresh={refresh}
            colors={['#3B82F6']} // Android
            tintColor="#3B82F6" // iOS
          />
        }
        // PHASE 5: Prevent scroll during action
        scrollEnabled={!isActionInFlight}
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.title}>Sentinel X</Text>
          <Text style={styles.subtitle}>Trading System Control</Text>
          {/* PHASE 4: Auth status indicator */}
          <View style={styles.authStatusContainer}>
            {authState.isAuthenticated && (
              <View style={styles.authBadge}>
                <Text style={styles.authBadgeText}>
                  🔐 Authenticated
                  {authState.isHardwareBacked ? ' (Hardware-backed)' : ''}
                </Text>
              </View>
            )}
            {biometricAvailable && (
              <View style={styles.biometricBadge}>
                <Text style={styles.biometricBadgeText}>
                  👤 Biometric: Available
                </Text>
              </View>
            )}
            {isBiometricLockedOut && (
              <View style={styles.lockoutBadge}>
                <Text style={styles.lockoutBadgeText}>
                  ⚠️ Biometric locked out. Use device passcode.
                </Text>
              </View>
            )}
          </View>
        </View>

        {/* System Status Card */}
        {/* PHASE 3-5: System Status Card with health-based badges */}
        <SystemStatusCard
          state={state}
          mode={modeLabel}
          uptime={uptime}
          heartbeat={heartbeat}
          error={error || healthError || undefined}
          lastUpdated={lastUpdated}
          healthStatus={healthSnapshot?.status}
          loopTick={healthSnapshot?.loop_tick}
          loopTickAge={healthSnapshot?.loop_tick_age}
          heartbeatAge={healthSnapshot?.heartbeat_age}
          broker={healthSnapshot?.broker}
          watchdog={healthSnapshot?.watchdog}
          isConnected={isHealthConnected}
          isReconnecting={isHealthReconnecting}
        />

        {/* PHASE 4: Live Metrics Card */}
        <LiveMetricsCard
          metrics={liveMetrics}
          error={metricsError}
        />

        {/* SHADOW COMPARISON: Shadow vs Live Comparison Card (Observational Only) */}
        <ShadowComparisonCard
          data={shadowComparison}
          isLoading={isShadowLoading}
          error={shadowError}
        />

        {/* Control Buttons */}
        <ControlButtons
          state={state}
          isLoading={isLoading}
          isActionInFlight={isActionInFlight}
          lockedActions={lockedActions}
          onStart={handleStart}
          onStop={handleStop}
          onKill={handleKill}
          isButtonDisabled={isButtonDisabled}
          authError={authState.authError}
          biometricAvailable={biometricAvailable}
          isBiometricLockedOut={isBiometricLockedOut}
        />

        {/* PHASE 7: SECURITY LOCK - Trading controls removed from mobile */}
        {/* SAFETY: No POST /orders, No POST /strategies, No PUT /risk */}
        {/* SAFETY: Mobile = OBSERVE + FUND ONLY */}
        {/* Test Order Button REMOVED - mobile cannot place orders */}

        {/* Info Section */}
        <View style={styles.infoSection}>
          <Text style={styles.infoTitle}>System States</Text>
          <View style={styles.infoItem}>
            <View style={[styles.stateIndicator, { backgroundColor: '#6B7280' }]} />
            <Text style={styles.infoText}>
              <Text style={styles.infoBold}>STOPPED:</Text> Engine paused, no
              trading activity
            </Text>
          </View>
          <View style={styles.infoItem}>
            <View style={[styles.stateIndicator, { backgroundColor: '#3B82F6' }]} />
            <Text style={styles.infoText}>
              <Text style={styles.infoBold}>RUNNING:</Text> Engine active,
              transitioning between modes
            </Text>
          </View>
          <View style={styles.infoItem}>
            <View style={[styles.stateIndicator, { backgroundColor: '#F59E0B' }]} />
            <Text style={styles.infoText}>
              <Text style={styles.infoBold}>TRAINING:</Text> Backtesting
              strategies, no live trading
            </Text>
          </View>
          <View style={styles.infoItem}>
            <View style={[styles.stateIndicator, { backgroundColor: '#10B981' }]} />
            <Text style={styles.infoText}>
              <Text style={styles.infoBold}>TRADING:</Text> Live trading active
            </Text>
          </View>
        </View>

        {/* Safety Info */}
        <View style={styles.safetySection}>
          <Text style={styles.safetyTitle}>⚡ Control Safety</Text>
          <Text style={styles.safetyText}>
            • Buttons are debounced to prevent accidental double-taps
          </Text>
          <Text style={styles.safetyText}>
            • Only one action can be in progress at a time
          </Text>
          <Text style={styles.safetyText}>
            • Emergency KILL is always available
          </Text>
          <Text style={styles.safetyText}>
            • Status updates automatically every 2 seconds
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F3F4F6',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 16,
    paddingBottom: 32, // Extra bottom padding for scroll
  },
  header: {
    marginBottom: 24,
  },
  title: {
    fontSize: 32,
    fontWeight: '700',
    color: '#1F2937',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 16,
    color: '#6B7280',
  },
  authStatusContainer: {
    marginTop: 8,
    gap: 6,
  },
  authBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: '#DCFCE7',
    borderRadius: 12,
    alignSelf: 'flex-start',
  },
  authBadgeText: {
    fontSize: 12,
    color: '#166534',
    fontWeight: '500',
  },
  biometricBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: '#DBEAFE',
    borderRadius: 12,
    alignSelf: 'flex-start',
  },
  biometricBadgeText: {
    fontSize: 12,
    color: '#1E40AF',
    fontWeight: '500',
  },
  lockoutBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: '#FEE2E2',
    borderRadius: 12,
    alignSelf: 'flex-start',
  },
  lockoutBadgeText: {
    fontSize: 12,
    color: '#991B1B',
    fontWeight: '500',
  },
  infoSection: {
    marginTop: 24,
    padding: 16,
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.1,
        shadowRadius: 2,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  infoTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 12,
  },
  infoItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
  },
  stateIndicator: {
    width: 12,
    height: 12,
    borderRadius: 6,
    marginRight: 10,
  },
  infoText: {
    flex: 1,
    fontSize: 14,
    color: '#4B5563',
    lineHeight: 20,
  },
  infoBold: {
    fontWeight: '600',
    color: '#1F2937',
  },
  safetySection: {
    marginTop: 16,
    padding: 16,
    backgroundColor: '#EFF6FF',
    borderRadius: 12,
    borderLeftWidth: 4,
    borderLeftColor: '#3B82F6',
  },
  safetyTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1E40AF',
    marginBottom: 8,
  },
  safetyText: {
    fontSize: 13,
    color: '#1E3A8A',
    lineHeight: 20,
    marginBottom: 4,
  },
  testOrderContainer: {
    marginTop: 16,
    padding: 16,
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.1,
        shadowRadius: 2,
      },
      android: {
        elevation: 2,
      },
    }),
  },
});
