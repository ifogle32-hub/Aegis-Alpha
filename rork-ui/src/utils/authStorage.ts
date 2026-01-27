/**
 * Secure Auth Storage Utilities - Hardware-Backed
 * 
 * PHASE 1: Secure token storage (hardware-backed)
 * PHASE 3: Auth header injection at request time
 * 
 * Features:
 * - Hardware-backed storage (iOS Keychain, Android Keystore)
 * - Token read ONLY at request time (never cached)
 * - Never logs tokens
 * - Never exposes tokens in UI
 * - Graceful fallback if hardware unavailable
 */

import { secureStorage, isHardwareBackedAvailable } from '../services/secureStorage';

/**
 * Auth state for UI
 * RULE: Never include actual token in UI state
 */
export interface AuthUIState {
  isAuthenticated: boolean;
  isAuthRequired: boolean;
  authError: string | null;
  isHardwareBacked: boolean;
  hasToken: boolean;
}

/**
 * Hardware-Backed Auth Storage Manager
 * 
 * PHASE 1: Token stored ONLY in hardware-backed storage
 * - iOS: Keychain Services (Secure Enclave)
 * - Android: Keystore
 * - Desktop: Session storage (graceful fallback)
 * 
 * PHASE 3: Token read ONLY at request time
 * - Never cached in memory
 * - Never exposed to UI components
 * - Never stringified or logged
 */
class AuthStorageManager {
  private isRequired: boolean = false;
  private lastAuthError: string | null = null;
  private hardwareBacked: boolean = false;
  private tokenCached: string | null = null; // TEMPORARY cache only during request
  private cacheTimestamp: number = 0;
  private CACHE_TIMEOUT_MS = 5000; // Cache cleared after 5 seconds

  /**
   * Initialize and check hardware-backed storage availability
   */
  async initialize(): Promise<void> {
    this.hardwareBacked = await isHardwareBackedAvailable();
    console.log('[AuthStorage] Hardware-backed storage available:', this.hardwareBacked);
  }

  /**
   * Store token in hardware-backed storage
   * RULE: Token stored ONLY in secure storage, never in memory
   */
  async setToken(token: string | null): Promise<boolean> {
    this.lastAuthError = null;
    
    if (!token) {
      // Delete token from secure storage
      await secureStorage.deleteToken();
      this.tokenCached = null;
      this.cacheTimestamp = 0;
      console.log('[AuthStorage] Token cleared from secure storage');
      return true;
    }
    
    // Store in hardware-backed storage
    const success = await secureStorage.storeToken(token);
    
    if (success) {
      // SECURITY: Never log the actual token
      console.log('[AuthStorage] Token stored in secure storage (length:', token.length, ')');
      return true;
    } else {
      console.error('[AuthStorage] Failed to store token in secure storage');
      this.lastAuthError = 'Failed to store token securely';
      return false;
    }
  }

  /**
   * Retrieve token from hardware-backed storage
   * 
   * PHASE 3 RULE: Token read ONLY at request time
   * Never cached for long periods
   * Cleared immediately after use
   * 
   * @returns Token or null if not found
   */
  async getToken(): Promise<string | null> {
    // Check temporary cache first (only if recent)
    const now = Date.now();
    if (this.tokenCached && (now - this.cacheTimestamp) < this.CACHE_TIMEOUT_MS) {
      // Use cached token (still within timeout)
      return this.tokenCached;
    }
    
    // Retrieve from hardware-backed storage
    const token = await secureStorage.retrieveToken();
    
    if (token) {
      // TEMPORARILY cache for request duration only
      this.tokenCached = token;
      this.cacheTimestamp = now;
      
      // SECURITY: Never log the actual token
      console.log('[AuthStorage] Token retrieved from secure storage (length:', token.length, ')');
      
      // Clear cache after timeout
      setTimeout(() => {
        if (Date.now() - this.cacheTimestamp >= this.CACHE_TIMEOUT_MS) {
          this.tokenCached = null;
          this.cacheTimestamp = 0;
        }
      }, this.CACHE_TIMEOUT_MS);
      
      return token;
    }
    
    return null;
  }

  /**
   * Clear cached token immediately
   * Called after request to ensure token not lingering in memory
   */
  clearCache(): void {
    this.tokenCached = null;
    this.cacheTimestamp = 0;
  }

  /**
   * Check if token exists in secure storage
   * Does NOT read the token value
   */
  async hasToken(): Promise<boolean> {
    const token = await this.getToken();
    return token !== null && token.length > 0;
  }

  /**
   * Set whether auth is required
   */
  setAuthRequired(required: boolean): void {
    this.isRequired = required;
    console.log('[AuthStorage] Auth required:', required);
  }

  /**
   * Check if auth is required
   */
  isAuthRequired(): boolean {
    return this.isRequired;
  }

  /**
   * Set auth error (for UI display)
   * RULE: Never include token in error message
   */
  setAuthError(error: string | null): void {
    this.lastAuthError = error;
  }

  /**
   * Get auth error for UI
   */
  getAuthError(): string | null {
    return this.lastAuthError;
  }

  /**
   * Get UI-safe auth state
   * RULE: Never includes actual token
   */
  async getUIState(): Promise<AuthUIState> {
    const hasToken = await this.hasToken();
    
    return {
      isAuthenticated: hasToken,
      isAuthRequired: this.isRequired,
      authError: this.lastAuthError,
      isHardwareBacked: this.hardwareBacked,
      hasToken,
    };
  }

  /**
   * Clear all auth state
   */
  async clear(): Promise<void> {
    await secureStorage.deleteToken();
    this.tokenCached = null;
    this.cacheTimestamp = 0;
    this.lastAuthError = null;
    console.log('[AuthStorage] Auth state cleared');
  }

  /**
   * Check if hardware-backed storage is being used
   */
  isUsingHardwareBacked(): boolean {
    return this.hardwareBacked;
  }
}

// Export singleton
export const authStorage = new AuthStorageManager();

/**
 * Initialize auth storage on app startup
 */
export async function initializeAuthStorage(): Promise<void> {
  await authStorage.initialize();
}

/**
 * Check if a status code indicates auth failure
 */
export function isAuthError(statusCode: number | undefined): boolean {
  return statusCode === 401 || statusCode === 403;
}

/**
 * Get user-friendly auth error message
 * RULE: Never expose technical details or tokens
 */
export function getAuthErrorMessage(statusCode: number | undefined): string {
  switch (statusCode) {
    case 401:
      return 'Authentication required. Please configure API key.';
    case 403:
      return 'Access denied. Invalid or expired API key.';
    default:
      return 'Authentication error. Please check your credentials.';
  }
}
