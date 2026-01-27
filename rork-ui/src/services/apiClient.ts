/**
 * API Client for Sentinel X Backend - Hardware-Backed Auth
 * 
 * PHASE 1: Secure token storage (hardware-backed)
 * PHASE 2: Biometric gate for control actions
 * PHASE 3: Auth header injection at request time
 * PHASE 4: Failure & lockout handling
 * 
 * Handles all communication with the FastAPI control plane.
 */

import {
  StatusResponse,
  ActionResponse,
  StrategiesResponse,
  PositionsResponse,
  AccountInfo,
  MetricsResponse,
} from '../types/api';
import { authStorage, isAuthError, getAuthErrorMessage } from '../utils/authStorage';
import { biometricAuth, BiometricResult, getBiometricErrorMessage } from './biometricAuth';

// Configuration
const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';
const REQUEST_TIMEOUT = 5000; // 5 seconds

/**
 * API Error with enhanced auth and biometric handling
 */
export class APIError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public isNetworkError: boolean = false,
    public isAuthError: boolean = false,
    public isBiometricError: boolean = false
  ) {
    super(message);
    this.name = 'APIError';
  }
}

/**
 * API Client singleton with hardware-backed auth
 */
class SentinelAPIClient {
  private baseUrl: string;

  constructor() {
    this.baseUrl = DEFAULT_BASE_URL;
  }

  /**
   * Configure API client
   * PHASE 1: Store token in hardware-backed storage
   */
  async configure(baseUrl: string, apiKey?: string): Promise<void> {
    this.baseUrl = baseUrl;
    
    // Store token securely in hardware-backed storage
    if (apiKey !== undefined) {
      await authStorage.setToken(apiKey || null);
    }
  }

  /**
   * Set auth required flag
   */
  setAuthRequired(required: boolean): void {
    authStorage.setAuthRequired(required);
  }

  /**
   * Get current auth state for UI
   */
  async getAuthState() {
    return await authStorage.getUIState();
  }

  /**
   * PHASE 2: Authenticate for control action
   * Requires biometric authentication before proceeding
   */
  private async authenticateForControlAction(action: 'START' | 'STOP' | 'KILL'): Promise<BiometricResult> {
    // Check if biometric is available
    const isAvailable = await biometricAuth.isAvailable();
    
    if (!isAvailable) {
      // PHASE 2 RULE: Graceful fallback - allow if biometric unavailable
      console.warn('[API] Biometric not available, allowing action without authentication');
      return { success: true };
    }

    // Require biometric authentication
    switch (action) {
      case 'START':
        return await biometricAuth.authenticateForStart();
      case 'STOP':
        return await biometricAuth.authenticateForStop();
      case 'KILL':
        return await biometricAuth.authenticateForKill();
      default:
        return await biometricAuth.authenticate('Authenticate Action');
    }
  }

  /**
   * Generic fetch wrapper with timeout, auth, and error handling
   * 
   * PHASE 3: Auth header injection at request time
   * - Token read from hardware-backed storage
   * - Injected only at request time
   * - Never cached or exposed
   */
  private async fetchWithTimeout(
    url: string,
    options: RequestInit = {},
    requiresBiometric: boolean = false,
    abortSignal?: AbortSignal
  ): Promise<Response> {
    // Check if already aborted
    if (abortSignal?.aborted) {
      throw new APIError('Request aborted', undefined, true, false, false);
    }
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    let abortHandler: (() => void) | null = null;
    
    // Combine with external abort signal if provided
    if (abortSignal) {
      // If external signal aborts, abort our controller
      abortHandler = () => {
        clearTimeout(timeoutId);
        controller.abort();
      };
      abortSignal.addEventListener('abort', abortHandler);
    }

    try {
      // PHASE 2: Biometric authentication for control actions
      if (requiresBiometric) {
        const biometricResult = await this.authenticateForControlAction(
          options.method === 'POST' ? (url.includes('/start') ? 'START' : url.includes('/stop') ? 'STOP' : 'KILL') : 'START'
        );

        if (!biometricResult.success) {
          // Biometric failed or cancelled
          const errorMessage = biometricResult.error || getBiometricErrorMessage(biometricResult.errorCode);
          authStorage.setAuthError(errorMessage);
          throw new APIError(errorMessage, undefined, false, false, true);
        }
      }

      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...options.headers,
      };

      // PHASE 3: Inject auth token at request time
      // RULE: Token read from hardware-backed storage, never cached
      const token = await authStorage.getToken();
      
      if (token) {
        // Inject both header formats for compatibility
        headers['X-API-Key'] = token;
        headers['Authorization'] = `Bearer ${token}`;
        
        // SECURITY: Never log the actual token
        console.log('[API] Auth header injected (token length:', token.length, ')');
        
        // PHASE 3: Clear token cache after use
        authStorage.clearCache();
      } else {
        // PHASE 3 RULE: Allow request if token missing (dev mode)
        console.warn('[API] No token available, proceeding without auth (dev mode)');
      }

      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      // PHASE 4: Handle auth errors
      if (isAuthError(response.status)) {
        const errorMessage = getAuthErrorMessage(response.status);
        authStorage.setAuthError(errorMessage);
        throw new APIError(errorMessage, response.status, false, true, false);
      }

      // Clear auth error on successful request
      authStorage.setAuthError(null);

      return response;
    } catch (error: any) {
      clearTimeout(timeoutId);
      
      // Clean up abort listener
      if (abortSignal && abortHandler) {
        abortSignal.removeEventListener('abort', abortHandler);
      }

      // Re-throw APIError as-is
      if (error instanceof APIError) {
        throw error;
      }

      // Network error, timeout, or abort
      if (error.name === 'AbortError') {
        // Check if it was aborted by external signal or timeout
        if (abortSignal?.aborted) {
          throw new APIError('Request aborted', undefined, true, false, false);
        }
        throw new APIError('Request timeout', undefined, true, false, false);
      }
      throw new APIError(
        error.message || 'Network error',
        undefined,
        true,
        false,
        false
      );
    }
  }

  /**
   * GET /health - No auth required (read-only)
   * PHASE 3: Canonical Sentinel X API health endpoint
   * PHASE 4: If /health responds → system is ONLINE
   */
  async getHealth(): Promise<any> {
    const response = await this.fetchWithTimeout(`${this.baseUrl}/health`, {}, false);

    if (!response.ok) {
      throw new APIError(
        `Health request failed: ${response.statusText}`,
        response.status
      );
    }

    try {
      return await response.json();
    } catch (err) {
      // Invalid JSON - treat as network/parsing error
      throw new APIError('Invalid JSON response from server', undefined, true, false, false);
    }
  }

  /**
   * GET /status - No auth required (read-only)
   * PHASE 2 RULE: Status polling NEVER requires biometrics
   * DEPRECATED: Prefer /health endpoint
   */
  async getStatus(): Promise<StatusResponse> {
    const response = await this.fetchWithTimeout(`${this.baseUrl}/status`, {}, false);

    if (!response.ok) {
      throw new APIError(
        `Status request failed: ${response.statusText}`,
        response.status
      );
    }

    try {
      return await response.json();
    } catch (err) {
      // Invalid JSON - treat as network/parsing error
      throw new APIError('Invalid JSON response from server', undefined, true, false, false);
    }
  }

  /**
   * POST /control/start - Set EngineMode = PAPER
   * CONTROL PLANE: Only changes execution permissions, never starts engine
   * PHASE 2: Requires biometric authentication
   */
  async start(abortSignal?: AbortSignal): Promise<ActionResponse> {
    const response = await this.fetchWithTimeout(
      `${this.baseUrl}/control/start`,
      { method: 'POST' },
      true, // Requires biometric
      abortSignal
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(
        error.detail || `Start failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * POST /control/stop - Set EngineMode = RESEARCH
   * CONTROL PLANE: Only changes execution permissions, never stops engine
   * PHASE 2: Requires biometric authentication
   */
  async stop(abortSignal?: AbortSignal): Promise<ActionResponse> {
    const response = await this.fetchWithTimeout(
      `${this.baseUrl}/control/stop`,
      { method: 'POST' },
      true, // Requires biometric
      abortSignal
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(
        error.detail || `Stop failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * POST /control/kill - Set EngineMode = KILLED + emergency_kill()
   * CONTROL PLANE: Hard stop, irreversible without restart
   * PHASE 2: Requires biometric authentication
   * PHASE 5: Clearly labeled as destructive
   */
  async kill(abortSignal?: AbortSignal): Promise<ActionResponse> {
    const response = await this.fetchWithTimeout(
      `${this.baseUrl}/control/kill`,
      { method: 'POST' },
      true, // Requires biometric
      abortSignal
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(
        error.detail || `Kill failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * GET /strategies - Read-only
   * PHASE 3: Returns array directly (not wrapped)
   */
  async getStrategies(): Promise<StrategiesResponse> {
    const response = await this.fetchWithTimeout(`${this.baseUrl}/strategies`);

    if (!response.ok) {
      throw new APIError(
        `Strategies request failed: ${response.statusText}`,
        response.status
      );
    }

    try {
      const data = await response.json();
      // PHASE 4: Handle both array and wrapped responses gracefully
      if (Array.isArray(data)) {
        return data;
      } else if (data.strategies && Array.isArray(data.strategies)) {
        return data.strategies; // Legacy wrapped response
      } else {
        return []; // Empty array on unexpected format
      }
    } catch (err) {
      throw new APIError('Invalid JSON response from server', undefined, true, false, false);
    }
  }

  /**
   * GET /positions - Read-only
   */
  async getPositions(): Promise<PositionsResponse> {
    const response = await this.fetchWithTimeout(`${this.baseUrl}/positions`);

    if (!response.ok) {
      throw new APIError(
        `Positions request failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * GET /account - Read-only
   */
  async getAccount(): Promise<AccountInfo> {
    const response = await this.fetchWithTimeout(`${this.baseUrl}/account`);

    if (!response.ok) {
      throw new APIError(
        `Account request failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * GET /metrics - Read-only
   * PHASE 3: Canonical Sentinel X API metrics endpoint
   */
  async getMetrics(): Promise<any> {
    const response = await this.fetchWithTimeout(`${this.baseUrl}/metrics`, {}, false);

    if (!response.ok) {
      throw new APIError(
        `Metrics request failed: ${response.statusText}`,
        response.status
      );
    }

    try {
      return await response.json();
    } catch (err) {
      throw new APIError('Invalid JSON response from server', undefined, true, false, false);
    }
  }

  /**
   * GET /risk - Read-only
   * PHASE 3: Canonical Sentinel X API risk endpoint
   */
  async getRisk(): Promise<any> {
    const response = await this.fetchWithTimeout(`${this.baseUrl}/risk`, {}, false);

    if (!response.ok) {
      throw new APIError(
        `Risk request failed: ${response.statusText}`,
        response.status
      );
    }

    try {
      return await response.json();
    } catch (err) {
      throw new APIError('Invalid JSON response from server', undefined, true, false, false);
    }
  }

  /**
   * GET /funding - Read-only
   * PHASE 3: Canonical Sentinel X API funding endpoint
   */
  async getFunding(): Promise<any> {
    const response = await this.fetchWithTimeout(`${this.baseUrl}/funding`, {}, false);

    if (!response.ok) {
      throw new APIError(
        `Funding request failed: ${response.statusText}`,
        response.status
      );
    }

    try {
      return await response.json();
    } catch (err) {
      throw new APIError('Invalid JSON response from server', undefined, true, false, false);
    }
  }

  /**
   * POST /test/order - Fire a test order (for UI testing)
   * PHASE 7: SECURITY LOCK - MOBILE FORBIDDEN
   * 
   * SAFETY: This endpoint should NOT be accessible from mobile.
   * Mobile = OBSERVE + FUND ONLY
   */
  async testOrder(): Promise<{ status: string; order_result?: any; reason?: string }> {
    // PHASE 7: Hard-coded mobile restriction
    // SAFETY: No POST /orders from mobile
    throw new APIError(
      'MOBILE RESTRICTION: Order placement is forbidden from mobile. Trading controlled server-side only.',
      403,
      false,
      false,
      false
    );
  }

  /**
   * GET /shadow/comparison - Get shadow vs live comparison (read-only)
   * OBSERVATIONAL ONLY - Never influences execution
   */
  async getShadowComparison(): Promise<any> {
    const response = await this.fetchWithTimeout(
      `${this.baseUrl}/shadow/comparison`,
      {},
      false // Read-only, no biometric required
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(
        error.detail || `Shadow comparison request failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * GET /shadow/strategies - Get all shadow strategy templates (read-only)
   * PHASE 1: SHADOW BACKTESTING
   */
  async getShadowStrategies(): Promise<any[]> {
    const response = await this.fetchWithTimeout(
      `${this.baseUrl}/shadow/strategies`,
      {},
      false // Read-only, no biometric required
    );

    if (!response.ok) {
      throw new APIError(
        `Shadow strategies request failed: ${response.statusText}`,
        response.status
      );
    }

    try {
      const data = await response.json();
      return Array.isArray(data) ? data : [];
    } catch (err) {
      throw new APIError('Invalid JSON response from server', undefined, true, false, false);
    }
  }

  /**
   * GET /shadow/strategies/{id}/performance - Get shadow backtest performance (read-only)
   * PHASE 1: SHADOW BACKTESTING
   */
  async getShadowPerformance(strategyId: string, startDate?: string, endDate?: string): Promise<any> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    
    const url = `${this.baseUrl}/shadow/strategies/${strategyId}/performance${params.toString() ? '?' + params.toString() : ''}`;
    const response = await this.fetchWithTimeout(url, {}, false);

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(
        error.detail || `Shadow performance request failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * GET /shadow/strategies/{id}/signals - Get shadow signals (read-only)
   * PHASE 1: SHADOW BACKTESTING
   */
  async getShadowSignals(strategyId: string, limit: number = 100, hours: number = 24): Promise<any> {
    const params = new URLSearchParams();
    params.append('limit', limit.toString());
    params.append('hours', hours.toString());
    
    const url = `${this.baseUrl}/shadow/strategies/${strategyId}/signals?${params.toString()}`;
    const response = await this.fetchWithTimeout(url, {}, false);

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(
        error.detail || `Shadow signals request failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * GET /shadow/overview - Get shadow strategy overview (read-only)
   * PHASE 1: SHADOW BACKTESTING
   */
  async getShadowOverview(): Promise<any> {
    const response = await this.fetchWithTimeout(
      `${this.baseUrl}/shadow/overview`,
      {},
      false // Read-only, no biometric required
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(
        error.detail || `Shadow overview request failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }

  /**
   * POST /shadow/strategies/{id}/backtest - Run shadow backtest (read-only, no execution)
   * PHASE 1: SHADOW BACKTESTING
   * SAFETY: SHADOW MODE ONLY - never triggers live execution
   */
  async runShadowBacktest(strategyId: string, config?: { start_date?: string; end_date?: string; initial_capital?: number }): Promise<any> {
    const response = await this.fetchWithTimeout(
      `${this.baseUrl}/shadow/strategies/${strategyId}/backtest`,
      {
        method: 'POST',
        body: JSON.stringify(config || {}),
      },
      false // Read-only shadow backtest, no biometric required
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(
        error.detail || `Shadow backtest request failed: ${response.statusText}`,
        response.status
      );
    }

    return response.json();
  }
}

// Export singleton instance
export const apiClient = new SentinelAPIClient();
