# Rork UI - Sentinel X Mobile Control Interface

Production-grade React Native mobile app for controlling and monitoring the Sentinel X trading system.

## Architecture

```
rork-ui/
├── src/
│   ├── types/           # TypeScript type definitions
│   │   └── api.ts       # API response types, BotState enum
│   ├── utils/           # Utility functions
│   │   └── stateNormalizer.ts  # PHASE 1 & 2: State normalization
│   ├── services/        # API communication
│   │   └── apiClient.ts # PHASE 6: Network-resilient API client
│   ├── hooks/           # React hooks
│   │   └── useSystemStatus.ts  # PHASE 4 & 5: Status polling + optimistic updates
│   ├── components/      # Reusable UI components
│   │   ├── SystemStatusCard.tsx  # Status display
│   │   └── ControlButtons.tsx    # PHASE 3: Button state logic
│   └── screens/         # Main screens
│       └── ControlScreen.tsx     # Main control interface
├── package.json
├── tsconfig.json
└── README.md
```

## Implementation Details

### PHASE 1: Status Normalization ✓
**File**: `src/utils/stateNormalizer.ts`

- `parseStatusResponse()` normalizes backend response
- UNKNOWN only shown:
  - Before first successful `/status` poll
  - OR when network request fails
- Never shown during normal operation

### PHASE 2: Enum Mapping ✓
**File**: `src/types/api.ts`

```typescript
export enum BotState {
  STOPPED = "STOPPED",
  RUNNING = "RUNNING",
  TRAINING = "TRAINING",
  TRADING = "TRADING",
}
```

- Matches backend `sentinel_x/core/state.py` exactly
- Safe fallback: unknown backend state → `STOPPED` (not UNKNOWN)
- `normalizeState()` handles case-insensitive matching

### PHASE 3: Button State Logic ✓
**File**: `src/components/ControlButtons.tsx`

**START button:**
- Disabled if state ∈ {RUNNING, TRAINING, TRADING}
- Enabled if state == STOPPED

**STOP button:**
- Enabled if state ∈ {RUNNING, TRAINING, TRADING}
- Disabled if state == STOPPED

**EMERGENCY KILL:**
- Always enabled
- Never blocked by state
- Requires confirmation dialog

### PHASE 4: Optimistic UI Updates ✓
**File**: `src/hooks/useSystemStatus.ts`

```typescript
performActionWithOptimisticUpdate(action, optimisticState)
```

- START → immediately sets UI to RUNNING
- STOP → immediately sets UI to STOPPED
- KILL → immediately sets UI to STOPPED
- Rollback only on API error
- Backend truth overrides on next poll

### PHASE 5: Status Refresh Loop ✓
**File**: `src/hooks/useSystemStatus.ts`

Polling strategy:
- Runs on mount (immediate fetch)
- Runs on interval (2 seconds)
- Runs after every action (500ms fast poll)
- Pull-to-refresh available in UI

### PHASE 6: Network Resilience ✓
**Files**: `src/services/apiClient.ts`, `src/hooks/useSystemStatus.ts`

Network error handling:
- Keep last known state (don't reset to UNKNOWN)
- Show subtle warning: "⚠️ Network error - using last known state"
- 5-second request timeout
- Distinguishes network errors from API errors
- State persists across network changes (hotspot, IP switch)

### PHASE 7: Verification Checklist ✓

**Verified behaviors:**

✓ Backend running → UI never shows UNKNOWN  
✓ START works without manual refresh  
✓ STOP works without manual refresh  
✓ KILL works instantly with confirmation  
✓ Status changes visible within one poll cycle (2s)  
✓ Optimistic updates provide instant feedback  
✓ Network errors don't clear state  
✓ Button states correctly reflect system state  

## Configuration

Edit `src/services/apiClient.ts` to configure backend URL:

```typescript
const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';
```

For production, use environment variables or runtime configuration.

## API Key Authentication

If backend has `ENABLE_API_AUTH=true`:

```typescript
apiClient.configure('http://your-backend-url', 'your-api-key');
```

## Usage

```typescript
import { ControlScreen } from './src/screens/ControlScreen';

// In your app navigation:
<ControlScreen />
```

## Testing Against Live Backend

1. Start Sentinel X backend:
```bash
cd sentinel_x
python main.py
```

2. Backend runs on `http://0.0.0.0:8000`

3. Test endpoints:
```bash
# Status (no auth)
curl http://127.0.0.1:8000/status

# Start (with auth if enabled)
curl -X POST -H "X-API-Key: your-key" http://127.0.0.1:8000/start

# Stop
curl -X POST -H "X-API-Key: your-key" http://127.0.0.1:8000/stop

# Kill
curl -X POST -H "X-API-Key: your-key" http://127.0.0.1:8000/kill
```

## Files Modified Summary

**UI Files Created (NO backend files touched):**

1. `rork-ui/src/types/api.ts` - Type definitions
2. `rork-ui/src/utils/stateNormalizer.ts` - State normalization
3. `rork-ui/src/services/apiClient.ts` - API client
4. `rork-ui/src/hooks/useSystemStatus.ts` - Status hook
5. `rork-ui/src/components/SystemStatusCard.tsx` - Status display
6. `rork-ui/src/components/ControlButtons.tsx` - Control buttons
7. `rork-ui/src/screens/ControlScreen.tsx` - Main screen
8. `rork-ui/package.json` - Dependencies
9. `rork-ui/tsconfig.json` - TypeScript config
10. `rork-ui/README.md` - Documentation

**Backend Files Modified:** NONE ✓

**UNKNOWN Eliminated:** ✓  
- Only shown before first poll or on network failure
- Never shown during normal operation with reachable backend

## Production Deployment

For production deployment:

1. **Environment Configuration:**
   - Use environment variables for backend URL
   - Securely store API keys (iOS Keychain, Android Keystore)

2. **Error Handling:**
   - Already implements retry logic
   - Network error detection
   - User-friendly error messages

3. **Performance:**
   - Optimistic updates for instant feedback
   - Efficient polling (2s interval)
   - Pull-to-refresh for manual updates

4. **Security:**
   - API key support built-in
   - HTTPS recommended for production
   - No sensitive data stored in UI state

