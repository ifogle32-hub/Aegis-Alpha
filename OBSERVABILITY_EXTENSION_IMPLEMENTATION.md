# Observability Extension Implementation Plan

## Status: Implementation in Progress

This document tracks the implementation of real-time observability extensions for Sentinel X, including push notifications, strategy PnL streaming, replay buffer, and secure pause requests.

## Phases

### ✅ Phase 1: Push Notifications (FROZEN/RECOVERED) - PARTIALLY IMPLEMENTED
- [x] Added notification functions in `notifications.py`
- [x] Added state transition tracking in `rork_server.py`
- [x] State transition detection in `get_health_snapshot()`
- [ ] Test state transition notifications

### Phase 2: Strategy PnL WebSocket Stream - TODO
- [ ] Create `get_strategy_pnl_snapshot()` function
- [ ] Add `/ws/strategies` WebSocket endpoint
- [ ] Implement `broadcast_strategy_pnl()` background task
- [ ] Update startup/shutdown events

### Phase 3: Historical Replay Buffer - TODO
- [x] Added replay buffer infrastructure (deque)
- [ ] Update broadcast functions to populate replay buffer
- [ ] Add replay buffer delivery on WebSocket connect
- [ ] Test replay buffer delivery

### Phase 4: UI Reconnect Behavior - TODO
- [ ] Update WebSocket hooks to receive replay buffer
- [ ] Implement chronological replay logic
- [ ] Test UI reconnection flow

### Phase 5: Secure Pause Request - TODO
- [ ] Add `POST /control/request_pause` endpoint
- [ ] Implement pause request logging (non-actuating)
- [ ] Add pause request state tracking
- [ ] Test pause request endpoint

### Phase 6: Future Approval Gate - TODO
- [ ] Add placeholder approval state machine
- [ ] Add multi-sig requirement placeholder
- [ ] Add cooldown enforcement placeholder
- [ ] Mark all as # FUTURE LIVE FEATURE — NOT ENABLED

### Phase 7: UI Badges & States - TODO
- [ ] Update UI components for strategy badges
- [ ] Add pause request pending state display
- [ ] Test badge logic

### Phase 8-10: Failure Modes, Verification, Regression Locks - TODO
- [ ] Add comprehensive safety guards
- [ ] Add regression lock comments
- [ ] Implement verification tests
- [ ] Document failure modes

## Safety Guarantees

All implementations must maintain:
- ✅ Zero trading control exposure
- ✅ Zero execution risk
- ✅ Zero behavioral changes to engine
- ✅ No async deadlocks
- ✅ No blocking paths
- ✅ Engine loop NEVER awaits network I/O
- ✅ Control plane is READ-ONLY by default
- ✅ All control requests are REQUESTS, not commands

## Implementation Status

Current progress: ~30% complete
- Phase 1: 80% complete (notification functions added, transition detection added, testing needed)
- Phase 2: 0% complete
- Phase 3: 20% complete (infrastructure added, population logic needed)
- Phase 4: 0% complete
- Phase 5: 0% complete
- Phase 6: 0% complete
- Phase 7: 0% complete
- Phase 8-10: 0% complete
