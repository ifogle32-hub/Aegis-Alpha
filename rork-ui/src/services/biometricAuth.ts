/**
 * Biometric Authentication Service
 * 
 * PHASE 2: Biometric gate for control actions
 * 
 * Features:
 * - Face ID / Touch ID / Fingerprint / OS PIN
 * - Prompt appears ONLY on user action (START/STOP/KILL)
 * - Never on background polling
 * - Graceful fallback if biometrics unavailable
 */

/**
 * Biometric authentication result
 */
export interface BiometricResult {
  success: boolean;
  error?: string;
  errorCode?: string;
}

/**
 * Biometric type available on device
 */
export type BiometricType = 'FaceID' | 'TouchID' | 'Fingerprint' | 'None';

/**
 * Platform-specific biometric implementation
 */
class BiometricAuth {
  /**
   * Check if biometric authentication is available
   */
  async isAvailable(): Promise<boolean> {
    try {
      const platform = this.getPlatform();
      
      if (platform === 'ios' || platform === 'android') {
        // @ts-ignore - react-native-keychain
        const Keychain = require('react-native-keychain');
        const biometryType = await Keychain.getSupportedBiometryType();
        return biometryType !== null;
      }
      
      // Desktop: not available
      return false;
    } catch {
      return false;
    }
  }

  /**
   * Get biometric type available on device
   */
  async getBiometricType(): Promise<BiometricType> {
    try {
      const platform = this.getPlatform();
      
      if (platform === 'ios' || platform === 'android') {
        // @ts-ignore - react-native-keychain
        const Keychain = require('react-native-keychain');
        const biometryType = await Keychain.getSupportedBiometryType();
        
        if (biometryType === Keychain.BIOMETRY_TYPE.FACE_ID) {
          return 'FaceID';
        }
        if (biometryType === Keychain.BIOMETRY_TYPE.TOUCH_ID) {
          return 'TouchID';
        }
        if (biometryType === Keychain.BIOMETRY_TYPE.FINGERPRINT) {
          return 'Fingerprint';
        }
      }
      
      return 'None';
    } catch {
      return 'None';
    }
  }

  /**
   * Authenticate with biometrics
   * 
   * PHASE 2 RULE: Prompt appears ONLY on user action
   * Never called during background polling
   * 
   * @param reason - Optional reason for authentication (shown to user)
   * @returns Result with success/error
   */
  async authenticate(reason?: string): Promise<BiometricResult> {
    try {
      const platform = this.getPlatform();
      
      if (platform === 'ios' || platform === 'android') {
        // @ts-ignore - react-native-keychain
        const Keychain = require('react-native-keychain');
        
        // Use getGenericPassword with biometric prompt
        // This triggers biometric authentication
        const credentials = await Keychain.getGenericPassword({
          service: 'com.sentinelx.rork',
          authenticationPrompt: {
            title: reason || 'Authenticate',
            subtitle: 'Use biometrics to authorize this action',
            description: 'Confirm your identity to proceed',
            cancel: 'Cancel',
          },
          // Require biometric authentication
          accessControl: Keychain.ACCESS_CONTROL.BIOMETRY_ANY_OR_DEVICE_PASSCODE,
        });
        
        if (credentials) {
          // Biometric succeeded
          return { success: true };
        } else {
          // User cancelled or failed
          return {
            success: false,
            error: 'Authentication cancelled or failed',
            errorCode: 'USER_CANCELLED',
          };
        }
      }
      
      // Desktop fallback: no biometric required
      console.warn('[BiometricAuth] Biometric not available on desktop, allowing action');
      return { success: true };
    } catch (error: any) {
      // Handle specific error codes
      let errorCode = 'UNKNOWN_ERROR';
      let errorMessage = 'Authentication failed';
      
      // @ts-ignore
      if (error.code === 'AUTHENTICATION_FAILED') {
        errorCode = 'AUTHENTICATION_FAILED';
        errorMessage = 'Biometric authentication failed';
      } else if (error.code === 'USER_CANCEL') {
        errorCode = 'USER_CANCELLED';
        errorMessage = 'Authentication cancelled';
      } else if (error.code === 'SYSTEM_CANCEL') {
        errorCode = 'SYSTEM_CANCELLED';
        errorMessage = 'Authentication cancelled by system';
      } else if (error.code === 'BIOMETRY_NOT_AVAILABLE') {
        errorCode = 'BIOMETRY_NOT_AVAILABLE';
        errorMessage = 'Biometric authentication not available';
      } else if (error.code === 'BIOMETRY_LOCKOUT') {
        errorCode = 'BIOMETRY_LOCKOUT';
        errorMessage = 'Biometric authentication locked out. Please use device passcode.';
      } else if (error.code === 'BIOMETRY_NOT_ENROLLED') {
        errorCode = 'BIOMETRY_NOT_ENROLLED';
        errorMessage = 'No biometrics enrolled. Please set up Face ID, Touch ID, or fingerprint.';
      }
      
      console.error('[BiometricAuth] Authentication error:', errorMessage, errorCode);
      
      return {
        success: false,
        error: errorMessage,
        errorCode,
      };
    }
  }

  /**
   * Authenticate for START action
   */
  async authenticateForStart(): Promise<BiometricResult> {
    return this.authenticate('Start Trading Engine');
  }

  /**
   * Authenticate for STOP action
   */
  async authenticateForStop(): Promise<BiometricResult> {
    return this.authenticate('Stop Trading Engine');
  }

  /**
   * Authenticate for KILL action
   * PHASE 5: Clearly labeled as destructive
   */
  async authenticateForKill(): Promise<BiometricResult> {
    return this.authenticate('Emergency Kill Switch');
  }

  /**
   * Check if device is locked out
   * PHASE 4: Respect OS lockout rules
   */
  async isLockedOut(): Promise<boolean> {
    try {
      const platform = this.getPlatform();
      
      if (platform === 'ios' || platform === 'android') {
        // @ts-ignore - react-native-keychain
        const Keychain = require('react-native-keychain');
        
        try {
          // Try to access with biometric - will fail if locked out
          const credentials = await Keychain.getGenericPassword({
            service: 'com.sentinelx.rork',
            accessControl: Keychain.ACCESS_CONTROL.BIOMETRY_ANY_OR_DEVICE_PASSCODE,
            // Use device passcode as fallback
            showModal: false, // Don't show prompt, just check availability
          });
          
          return false; // Not locked out
        } catch (error: any) {
          // @ts-ignore
          if (error.code === 'BIOMETRY_LOCKOUT') {
            return true;
          }
          return false;
        }
      }
      
      return false;
    } catch {
      return false;
    }
  }

  /**
   * Get platform name
   */
  private getPlatform(): 'ios' | 'android' | 'web' | 'unknown' {
    // @ts-ignore
    if (typeof navigator !== 'undefined' && navigator.product === 'ReactNative') {
      // @ts-ignore
      const Platform = require('react-native').Platform;
      if (Platform.OS === 'ios') return 'ios';
      if (Platform.OS === 'android') return 'android';
    }
    
    if (typeof window !== 'undefined') {
      return 'web';
    }
    
    return 'unknown';
  }
}

// Export singleton instance
export const biometricAuth = new BiometricAuth();

/**
 * User-friendly error message for biometric failures
 * PHASE 4: Helpful error messages without exposing technical details
 */
export function getBiometricErrorMessage(errorCode?: string): string {
  switch (errorCode) {
    case 'USER_CANCELLED':
      return 'Action cancelled';
    case 'AUTHENTICATION_FAILED':
      return 'Authentication failed. Please try again.';
    case 'BIOMETRY_LOCKOUT':
      return 'Biometric authentication locked out. Please use your device passcode.';
    case 'BIOMETRY_NOT_ENROLLED':
      return 'No biometrics set up. Please configure Face ID, Touch ID, or fingerprint.';
    case 'BIOMETRY_NOT_AVAILABLE':
      return 'Biometric authentication not available on this device.';
    default:
      return 'Authentication required to perform this action.';
  }
}

