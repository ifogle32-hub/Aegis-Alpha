/**
 * Control Buttons Component - Mobile Hardened
 * 
 * PHASE 1: Mobile debounce (critical)
 * PHASE 3: Button state logic
 * PHASE 5: Mobile UX safety
 * 
 * Features:
 * - Per-action debounce locks
 * - Increased tap targets
 * - Visual feedback on press
 * - Loading indicators
 * - Disabled state styling
 */

import React, { useCallback, useRef } from 'react';
import {
  View,
  TouchableOpacity,
  Text,
  StyleSheet,
  ActivityIndicator,
  Animated,
  Platform,
} from 'react-native';
import { SystemState } from '../types/api';
import { ActionType } from '../utils/debounce';

// PHASE 5: Mobile UX constants
const TAP_DEBOUNCE_MS = 100; // Ignore taps within 100ms (animation frame)
const BUTTON_MIN_HEIGHT = 56; // Minimum touch target (iOS HIG: 44pt, Android: 48dp)
const BUTTON_HIT_SLOP = { top: 8, bottom: 8, left: 8, right: 8 }; // Extra touch area

interface ControlButtonsProps {
  state: SystemState;
  isLoading: boolean;
  isActionInFlight: boolean;
  lockedActions: Set<ActionType>;
  onStart: () => void;
  onStop: () => void;
  onKill: () => void;
  isButtonDisabled: (action: ActionType) => boolean;
  authError?: string | null;
  biometricAvailable?: boolean;
  isBiometricLockedOut?: boolean;
}

export const ControlButtons: React.FC<ControlButtonsProps> = ({
  state,
  isLoading,
  isActionInFlight,
  lockedActions,
  onStart,
  onStop,
  onKill,
  isButtonDisabled,
  authError,
  biometricAvailable = false,
  isBiometricLockedOut = false,
}) => {
  // PHASE 5: Track last tap time to prevent accidental double-taps
  const lastTapTimeRef = useRef<{ [key in ActionType]?: number }>({});

  /**
   * PHASE 5: Wrap handler with tap debounce
   * Prevents accidental multi-presses during animation frames
   */
  const withTapDebounce = useCallback(
    (action: ActionType, handler: () => void) => {
      return () => {
        const now = Date.now();
        const lastTap = lastTapTimeRef.current[action] || 0;

        // Ignore taps within debounce window
        if (now - lastTap < TAP_DEBOUNCE_MS) {
          console.log(`[Button] ${action} tap ignored (too fast)`);
          return;
        }

        lastTapTimeRef.current[action] = now;
        handler();
      };
    },
    []
  );

  /**
   * Get button state for each action
   */
  const isStartDisabled = isButtonDisabled('START');
  const isStopDisabled = isButtonDisabled('STOP');
  const isKillDisabled = isButtonDisabled('KILL');

  /**
   * Check if action is currently locked (debounced)
   */
  const isStartLocked = lockedActions.has('START');
  const isStopLocked = lockedActions.has('STOP');
  const isKillLocked = lockedActions.has('KILL');

  /**
   * Render loading indicator or text
   */
  const renderButtonContent = (
    action: ActionType,
    text: string,
    isLocked: boolean
  ) => {
    if (isLocked || (isActionInFlight && isLoading)) {
      return (
        <View style={styles.buttonContentContainer}>
          <ActivityIndicator color="#FFFFFF" size="small" />
          <Text style={[styles.buttonText, styles.buttonTextLoading]}>
            {text}
          </Text>
        </View>
      );
    }
    return <Text style={styles.buttonText}>{text}</Text>;
  };

  return (
    <View style={styles.container}>
      {/* PHASE 4: Auth error banner */}
      {authError && (
        <View style={styles.authErrorBanner}>
          <Text style={styles.authErrorText}>🔒 {authError}</Text>
        </View>
      )}

      {/* START Button */}
      <TouchableOpacity
        style={[
          styles.button,
          styles.startButton,
          (isStartDisabled || isStartLocked) && styles.buttonDisabled,
          isStartLocked && styles.buttonLocked,
        ]}
        onPress={withTapDebounce('START', onStart)}
        disabled={isStartDisabled || isStartLocked}
        activeOpacity={0.7}
        hitSlop={BUTTON_HIT_SLOP}
        accessibilityLabel="Start trading engine"
        accessibilityRole="button"
        accessibilityState={{ disabled: isStartDisabled || isStartLocked }}
      >
        {renderButtonContent('START', '▶ START', isStartLocked)}
      </TouchableOpacity>

      {/* STOP Button */}
      <TouchableOpacity
        style={[
          styles.button,
          styles.stopButton,
          (isStopDisabled || isStopLocked) && styles.buttonDisabled,
          isStopLocked && styles.buttonLocked,
        ]}
        onPress={withTapDebounce('STOP', onStop)}
        disabled={isStopDisabled || isStopLocked}
        activeOpacity={0.7}
        hitSlop={BUTTON_HIT_SLOP}
        accessibilityLabel="Stop trading engine"
        accessibilityRole="button"
        accessibilityState={{ disabled: isStopDisabled || isStopLocked }}
      >
        {renderButtonContent('STOP', '■ STOP', isStopLocked)}
      </TouchableOpacity>

      {/* EMERGENCY KILL Button */}
      <TouchableOpacity
        style={[
          styles.button,
          styles.killButton,
          isKillLocked && styles.buttonLocked,
          // KILL is never disabled by state, only by debounce
        ]}
        onPress={withTapDebounce('KILL', onKill)}
        disabled={isKillLocked}
        activeOpacity={0.7}
        hitSlop={BUTTON_HIT_SLOP}
        accessibilityLabel="Emergency kill switch"
        accessibilityRole="button"
        accessibilityState={{ disabled: isKillLocked }}
      >
        {renderButtonContent('KILL', '⚠ EMERGENCY KILL', isKillLocked)}
      </TouchableOpacity>

      {/* PHASE 2: Biometric status indicator */}
      {biometricAvailable && (
        <View style={styles.biometricIndicator}>
          <Text style={styles.biometricIndicatorText}>
            👤 Biometric authentication required for control actions
          </Text>
        </View>
      )}

      {/* PHASE 4: Lockout indicator */}
      {isBiometricLockedOut && (
        <View style={styles.lockoutIndicator}>
          <Text style={styles.lockoutIndicatorText}>
            ⚠️ Biometric locked out. Control actions disabled. Use device passcode to unlock.
          </Text>
        </View>
      )}

      {/* PHASE 1: Debounce indicator */}
      {isActionInFlight && (
        <View style={styles.debounceIndicator}>
          <Text style={styles.debounceText}>
            Processing... Please wait
          </Text>
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    gap: 12,
  },
  button: {
    paddingVertical: 16,
    paddingHorizontal: 24,
    borderRadius: 12, // Slightly larger radius for modern look
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: BUTTON_MIN_HEIGHT,
    // PHASE 5: Shadow for depth
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.15,
        shadowRadius: 4,
      },
      android: {
        elevation: 3,
      },
    }),
  },
  buttonContentContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  startButton: {
    backgroundColor: '#10B981', // Green
  },
  stopButton: {
    backgroundColor: '#F59E0B', // Amber
  },
  killButton: {
    backgroundColor: '#EF4444', // Red
    marginTop: 8,
    // PHASE 5: Extra visual distinction for KILL
    borderWidth: 2,
    borderColor: '#DC2626',
  },
  buttonDisabled: {
    backgroundColor: '#D1D5DB', // Gray
    opacity: 0.6,
    // Remove shadow when disabled
    ...Platform.select({
      ios: {
        shadowOpacity: 0,
      },
      android: {
        elevation: 0,
      },
    }),
  },
  buttonLocked: {
    // Visual indicator that button is temporarily locked
    opacity: 0.8,
  },
  buttonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  buttonTextLoading: {
    opacity: 0.8,
  },
  debounceIndicator: {
    marginTop: 8,
    padding: 8,
    backgroundColor: '#FEF3C7',
    borderRadius: 6,
    alignItems: 'center',
  },
  debounceText: {
    fontSize: 12,
    color: '#92400E',
    fontWeight: '500',
  },
  authErrorBanner: {
    marginBottom: 12,
    padding: 12,
    backgroundColor: '#FEE2E2',
    borderRadius: 8,
    borderLeftWidth: 4,
    borderLeftColor: '#EF4444',
  },
  authErrorText: {
    fontSize: 14,
    color: '#991B1B',
    fontWeight: '500',
  },
  biometricIndicator: {
    marginTop: 8,
    padding: 10,
    backgroundColor: '#EFF6FF',
    borderRadius: 6,
    borderLeftWidth: 3,
    borderLeftColor: '#3B82F6',
  },
  biometricIndicatorText: {
    fontSize: 12,
    color: '#1E40AF',
    fontWeight: '500',
  },
  lockoutIndicator: {
    marginTop: 8,
    padding: 10,
    backgroundColor: '#FEF2F2',
    borderRadius: 6,
    borderLeftWidth: 3,
    borderLeftColor: '#EF4444',
  },
  lockoutIndicatorText: {
    fontSize: 12,
    color: '#991B1B',
    fontWeight: '500',
  },
});
<Button
  title="Fire Test Order"
  onPress={async () => {
    await fetch("/test-order", { method: "POST" });
  }}
/>