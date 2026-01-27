"""
PHASE 2 — SHADOW CONTROL API ENDPOINTS

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

API endpoints for enabling/disabling shadow mode.
All endpoints return 200 OK unless internal error occurs.
"""

from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from sentinel_x.monitoring.logger import logger
from sentinel_x.core.shadow_registry import get_shadow_controller, ShadowState

# Request ID context and auth (reused from rork_server)
try:
    from sentinel_x.api.rork_server import request_id_ctx, require_api_key
except ImportError:
    # Fallback if context not available
    from contextvars import ContextVar
    request_id_ctx: ContextVar[str] = ContextVar('request_id', default='')
    
    # Fallback require_api_key (no-op if not available)
    from fastapi import Request
    async def require_api_key(request: Request = None):
        """Fallback: no auth if require_api_key not available."""
        return True

router = APIRouter(prefix="/shadow", tags=["shadow_control"])


class ShadowStatusResponse(BaseModel):
    """Response model for shadow status endpoints."""
    enabled: bool
    timestamp: str
    mode: str
    trading_window: str = "UNKNOWN"
    last_transition: str | None = None
    reason: str | None = None


class ShadowEnableRequest(BaseModel):
    """Request model for enabling shadow mode."""
    reason: str | None = None


class ShadowDisableRequest(BaseModel):
    """Request model for disabling shadow mode."""
    reason: str | None = None


@router.post("/enable", response_model=ShadowStatusResponse)
async def enable_shadow(
    request: Request,
    auth_result = Depends(require_api_key)
):
    """
    Enable shadow mode.
    
    SAFETY: SHADOW MODE ONLY - never triggers order execution
    SAFETY: Engine continues running during state change
    
    Request body (optional):
    {
        "reason": "Optional reason for enabling"
    }
    
    Returns:
        ShadowStatusResponse with current state (always 200 OK unless internal error)
    """
    request_id = request_id_ctx.get()
    
    try:
        # Parse request body (optional)
        reason = None
        try:
            if request.headers.get("content-type") == "application/json":
                body = await request.json()
                reason = body.get("reason") if body else None
        except Exception:
            pass  # Body parsing is optional
        
        controller = get_shadow_controller()
        controller.enable(reason=reason)
        state_dict = controller.get_state_dict()
        
        logger.info(
            f"SHADOW_ENABLE_OK | request_id={request_id} | "
            f"reason={reason or 'none'}"
        )
        
        return ShadowStatusResponse(
            enabled=True,
            timestamp=datetime.utcnow().isoformat() + "Z",
            mode=state_dict["mode"],
            trading_window=state_dict["trading_window"],
            last_transition=state_dict["last_transition"],
            reason=state_dict["reason"]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error enabling shadow mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error enabling shadow mode: {str(e)}")


@router.post("/disable", response_model=ShadowStatusResponse)
async def disable_shadow(
    request: Request,
    auth_result = Depends(require_api_key)
):
    """
    Disable shadow mode.
    
    SAFETY: Engine continues running during state change
    
    Request body (optional):
    {
        "reason": "Optional reason for disabling"
    }
    
    Returns:
        ShadowStatusResponse with current state (always 200 OK unless internal error)
    """
    request_id = request_id_ctx.get()
    
    try:
        # Parse request body (optional)
        reason = None
        try:
            if request.headers.get("content-type") == "application/json":
                body = await request.json()
                reason = body.get("reason") if body else None
        except Exception:
            pass  # Body parsing is optional
        
        controller = get_shadow_controller()
        controller.disable(reason=reason)
        state_dict = controller.get_state_dict()
        
        logger.info(
            f"SHADOW_DISABLE_OK | request_id={request_id} | "
            f"reason={reason or 'none'}"
        )
        
        return ShadowStatusResponse(
            enabled=False,
            timestamp=datetime.utcnow().isoformat() + "Z",
            mode=state_dict["mode"],
            trading_window=state_dict["trading_window"],
            last_transition=state_dict["last_transition"],
            reason=state_dict["reason"]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling shadow mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error disabling shadow mode: {str(e)}")


@router.get("/status", response_model=ShadowStatusResponse)
async def get_shadow_status(request: Request):
    """
    Get current shadow mode status.
    
    SAFETY: Read-only, no authentication required
    
    Returns:
        ShadowStatusResponse with current state (always 200 OK)
    """
    request_id = request_id_ctx.get()
    
    try:
        controller = get_shadow_controller()
        state_dict = controller.get_state_dict()
        
        return ShadowStatusResponse(
            enabled=state_dict["shadow_enabled"],
            timestamp=datetime.utcnow().isoformat() + "Z",
            mode=state_dict["mode"],
            trading_window=state_dict["trading_window"],
            last_transition=state_dict["last_transition"],
            reason=state_dict["reason"]
        )
    except Exception as e:
        logger.error(f"Error getting shadow status: {e}", exc_info=True)
        # Return safe defaults on error (always 200 OK)
        return ShadowStatusResponse(
            enabled=False,
            timestamp=datetime.utcnow().isoformat() + "Z",
            mode="DISABLED",
            trading_window="UNKNOWN",
            last_transition=None,
            reason=None
        )
