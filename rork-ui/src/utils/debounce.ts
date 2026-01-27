/**
 * Debounce Utilities for Mobile Safety
 * 
 * PHASE 1: Mobile debounce (critical)
 * - Per-action debounce locks
 * - Prevents duplicate taps
 * - Mobile-safe timing (750-1200ms)
 */

// Debounce configuration
export const DEBOUNCE_CONFIG = {
  // Lock duration after button press (mobile-safe)
  LOCK_DURATION_MS: 1000, // 1 second - balanced for mobile
  
  // Minimum time between same action
  MIN_ACTION_INTERVAL_MS: 750,
  
  // Animation frame ignore window
  ANIMATION_IGNORE_MS: 100,
} as const;

/**
 * Action types for debounce tracking
 */
export type ActionType = 'START' | 'STOP' | 'KILL';

/**
 * Debounce state for each action
 */
interface ActionDebounceState {
  lastActionTime: number;
  isLocked: boolean;
  lockTimeoutId: NodeJS.Timeout | null;
}

/**
 * Global debounce state manager
 * Tracks per-action debounce state
 */
class DebounceManager {
  private actionStates: Map<ActionType, ActionDebounceState>;
  private globalActionInFlight: boolean;

  constructor() {
    this.actionStates = new Map();
    this.globalActionInFlight = false;
    
    // Initialize states for all actions
    const actions: ActionType[] = ['START', 'STOP', 'KILL'];
    actions.forEach(action => {
      this.actionStates.set(action, {
        lastActionTime: 0,
        isLocked: false,
        lockTimeoutId: null,
      });
    });
  }

  /**
   * Check if any action is currently in flight
   * RULE: Only ONE control action may be in-flight at a time
   */
  isAnyActionInFlight(): boolean {
    return this.globalActionInFlight;
  }

  /**
   * Check if specific action is debounced/locked
   */
  isActionLocked(action: ActionType): boolean {
    const state = this.actionStates.get(action);
    if (!state) return false;
    
    return state.isLocked;
  }

  /**
   * Check if action can be executed
   * Returns false if:
   * - Another action is in flight
   * - This action is locked (debounced)
   * - Too soon since last action of same type
   */
  canExecuteAction(action: ActionType): boolean {
    // Global lock: no concurrent actions
    if (this.globalActionInFlight) {
      return false;
    }

    const state = this.actionStates.get(action);
    if (!state) return true;

    // Per-action lock
    if (state.isLocked) {
      return false;
    }

    // Minimum interval check
    const now = Date.now();
    if (now - state.lastActionTime < DEBOUNCE_CONFIG.MIN_ACTION_INTERVAL_MS) {
      return false;
    }

    return true;
  }

  /**
   * Lock action before execution
   * Called when action is initiated
   */
  lockAction(action: ActionType): void {
    this.globalActionInFlight = true;
    
    const state = this.actionStates.get(action);
    if (state) {
      // Clear any existing timeout
      if (state.lockTimeoutId) {
        clearTimeout(state.lockTimeoutId);
      }

      state.isLocked = true;
      state.lastActionTime = Date.now();
    }
  }

  /**
   * Unlock action after completion
   * Called on success, error, or timeout
   */
  unlockAction(action: ActionType): void {
    this.globalActionInFlight = false;
    
    const state = this.actionStates.get(action);
    if (state) {
      // Keep locked for debounce duration to prevent rapid re-taps
      state.lockTimeoutId = setTimeout(() => {
        state.isLocked = false;
        state.lockTimeoutId = null;
      }, DEBOUNCE_CONFIG.LOCK_DURATION_MS);
    }
  }

  /**
   * Force unlock (for emergency/timeout scenarios)
   */
  forceUnlock(action: ActionType): void {
    this.globalActionInFlight = false;
    
    const state = this.actionStates.get(action);
    if (state) {
      if (state.lockTimeoutId) {
        clearTimeout(state.lockTimeoutId);
      }
      state.isLocked = false;
      state.lockTimeoutId = null;
    }
  }

  /**
   * Reset all debounce state
   */
  reset(): void {
    this.globalActionInFlight = false;
    this.actionStates.forEach((state, action) => {
      if (state.lockTimeoutId) {
        clearTimeout(state.lockTimeoutId);
      }
      this.actionStates.set(action, {
        lastActionTime: 0,
        isLocked: false,
        lockTimeoutId: null,
      });
    });
  }
}

// Export singleton instance
export const debounceManager = new DebounceManager();

/**
 * Hook-friendly debounce wrapper
 * Wraps an async action with debounce protection
 */
export async function withDebounce<T>(
  action: ActionType,
  fn: () => Promise<T>
): Promise<T> {
  if (!debounceManager.canExecuteAction(action)) {
    throw new Error(`Action ${action} is debounced or another action is in progress`);
  }

  debounceManager.lockAction(action);
  
  try {
    const result = await fn();
    return result;
  } finally {
    debounceManager.unlockAction(action);
  }
}

