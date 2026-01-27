#!/usr/bin/env python3
"""
Bootstrap entrypoint for Sentinel X.
NO business logic. NO strategies. NO imports beyond main().

REGRESSION LOCK:
Bootstrap must not depend on strategy lifecycle or intelligence modules.
Only sentinel_x.main is imported - all other logic stays in main module.

────────────────────────────────────────
PHASE 8 — REGRESSION LOCK
────────────────────────────────────────

REGRESSION LOCK:
Do NOT modify engine loop, broker wiring, or order schemas
without architect approval. Changes here can cause
silent trading failures or engine crashes.

ENFORCE:
• No lifecycle module imports in bootstrap
• No default/non-default argument order violations
• No schema assumptions
"""

# ============================================================
# REGRESSION LOCK — DO NOT MODIFY
# Stable execution baseline.
# Changes require architectural review.
# ============================================================
# NO future changes may:
#   • Alter executor signatures
#   • Change router → executor contracts
#   • Introduce lifecycle dependencies in bootstrap
#   • Affect TRAINING auto-connect behavior
# ============================================================

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    try:
        from sentinel_x.main import main
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"FATAL: Bootstrap failed: {e}", file=sys.stderr)
        sys.exit(1)