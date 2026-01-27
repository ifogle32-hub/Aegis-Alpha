# PHASE 8: LIVE-Arm Checklist (FUTURE-LOCKED)

## FUTURE LOCK — LIVE ENABLEMENT DISABLED
## DO NOT REMOVE WITHOUT MULTI-STEP REVIEW

---

## Overview

This document defines the requirements for enabling LIVE trading in Sentinel X.
**ALL requirements are MANDATORY** and must be satisfied before LIVE trading can be enabled.

**CURRENT STATUS: LIVE trading is DISABLED. This checklist is for future implementation only.**

---

## Requirements (ALL MANDATORY)

### 1. Separate Broker Adapter
- [ ] Implement separate LIVE broker adapter (independent of PAPER/TRAINING brokers)
- [ ] Adapter must be isolated from training infrastructure
- [ ] No code sharing between LIVE and TRAINING execution paths
- [ ] Separate connection pools and state management

### 2. Separate Config File
- [ ] Create dedicated LIVE configuration file (`live_config.yaml` or `.env.live`)
- [ ] Configuration must be explicitly separate from training config
- [ ] Must include: account IDs, API keys, risk limits, position sizing
- [ ] Config file location must be clearly documented
- [ ] Config file must be version-controlled but secrets excluded

### 3. Environment Variable: ENABLE_LIVE=true
- [ ] System requires explicit `ENABLE_LIVE=true` environment variable
- [ ] Default value: `ENABLE_LIVE=false`
- [ ] Variable must be set at engine startup (not runtime)
- [ ] System must validate this variable is explicitly set to `true`

### 4. Hardware-Key Approval
- [ ] Implement hardware key (YubiKey, etc.) authentication
- [ ] LIVE enablement requires physical hardware key presence
- [ ] Key must be inserted at startup and remain present during LIVE operation
- [ ] System must periodically verify hardware key is still present
- [ ] If key removed: immediately disable LIVE and revert to TRAINING

### 5. Cooldown Delay
- [ ] Implement mandatory cooldown period (minimum 24 hours) after LIVE enablement
- [ ] During cooldown: system runs in SHADOW mode only (no actual execution)
- [ ] Cooldown period must be configurable (minimum enforced)
- [ ] System must log cooldown start and completion
- [ ] Cooldown timer must survive engine restarts

### 6. Manual Confirmation
- [ ] Require explicit operator confirmation via secure channel
- [ ] Confirmation must include:
  - Account ID verification
  - Risk limits acknowledgment
  - Capital allocation confirmation
- [ ] Confirmation must be logged with operator identity and timestamp
- [ ] Confirmation cannot be automated or scripted

### 7. Independent Risk Limits
- [ ] LIVE risk limits must be separate from TRAINING limits
- [ ] Must include:
  - Max position size per strategy
  - Max daily loss limit
  - Max portfolio leverage
  - Max trades per day
  - Max drawdown threshold
- [ ] Risk limits must be validated against broker account constraints
- [ ] System must enforce limits independently of TRAINING system

---

## Implementation Checklist

### Code Changes Required
- [ ] Create `sentinel_x/execution/live_broker.py` (separate from paper/training)
- [ ] Create `sentinel_x/core/live_config.py` (separate config loader)
- [ ] Add hardware key authentication module
- [ ] Implement cooldown timer and state management
- [ ] Add manual confirmation endpoint (secure, requires API key + hardware key)
- [ ] Separate risk limit enforcement for LIVE mode

### Configuration Changes Required
- [ ] Add `live_config.yaml` template
- [ ] Document all required LIVE configuration parameters
- [ ] Create `.env.live.example` file
- [ ] Document hardware key setup process

### Testing Requirements
- [ ] Unit tests for all LIVE enablement checks
- [ ] Integration tests for hardware key authentication
- [ ] Cooldown timer tests (including restart scenarios)
- [ ] Risk limit enforcement tests
- [ ] End-to-end test with mock broker (NO real money)

### Documentation Requirements
- [ ] Update main README with LIVE enablement process
- [ ] Create `LIVE_SETUP.md` guide
- [ ] Document hardware key setup and configuration
- [ ] Document risk limit configuration and validation
- [ ] Create operator runbook for LIVE enablement

---

## Safety Guards

### Runtime Checks
- System must verify ALL requirements are met at startup
- If ANY requirement missing: immediately revert to TRAINING mode
- System must log which requirement(s) failed
- System must NOT attempt to connect to LIVE broker if checks fail

### Monitoring
- All LIVE enablement attempts must be audited
- System must log operator identity, timestamp, and configuration used
- Failed enablement attempts must be logged with reason
- System must monitor hardware key presence continuously

### Rollback
- System must support immediate rollback to TRAINING mode
- Rollback must disconnect from LIVE broker immediately
- Rollback must preserve audit logs and state
- Rollback can be triggered by hardware key removal or manual command

---

## Current Implementation Status

**LIVE trading is NOT implemented. This checklist is a design document for future implementation.**

All references to LIVE mode in the codebase are:
- Placeholder/future-locked
- Informational only
- Not functional

---

## Notes

- This checklist is a living document and may be updated based on requirements
- Any implementation must go through multi-step review process
- No implementation should begin without explicit approval from architecture team
- All changes must maintain backward compatibility with TRAINING mode
