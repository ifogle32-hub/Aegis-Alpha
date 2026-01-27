"""
Multi-Signature Approval System for ARMED State Promotion

PHASE 2 — MULTI-SIG APPROVAL MODEL
PHASE 3 — PROMOTION REQUEST FLOW
PHASE 4 — MOBILE CONFIRMATION REQUIREMENT

Implements secure, auditable promotion path from SHADOW → ARMED.
"""

import time
import threading
import uuid
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime


class ApprovalRequestStatus(Enum):
    """ARMED promotion request lifecycle states"""
    PENDING = "PENDING"
    APPROVED = "APPROVED"  # Has sufficient approvals
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ACTIVATED = "ACTIVATED"  # ARMED state activated
    REVOKED = "REVOKED"


class ApproverRole(Enum):
    """Approver role types"""
    ADMIN = "admin"
    OPERATOR = "operator"
    RISK = "risk"


class ApprovalMethod(Enum):
    """Approval methods"""
    MOBILE = "mobile"  # Required - at least one must be mobile
    API = "api"


@dataclass
class Approval:
    """
    PHASE 2 — APPROVAL SCHEMA
    
    Individual approval record for ARMED promotion request.
    """
    approver_id: str
    approver_role: ApproverRole
    approval_method: ApprovalMethod
    timestamp: float
    device_id: Optional[str] = None  # Required if approval_method == MOBILE
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert approval to dict"""
        return {
            "approver_id": self.approver_id,
            "approver_role": self.approver_role.value,
            "approval_method": self.approval_method.value,
            "timestamp": self.timestamp,
            "device_id": self.device_id,
        }


@dataclass
class ArmedRequest:
    """
    PHASE 3 — PROMOTION REQUEST LIFECYCLE
    
    ARMED promotion request with approval tracking.
    """
    request_id: str
    created_at: float
    expires_at: float
    reason: str
    status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING
    approvals: List[Approval] = field(default_factory=list)
    
    # PHASE 2: Approval requirements
    MIN_APPROVALS_REQUIRED: int = 2
    MIN_APPROVAL_WINDOW_SECONDS: int = 300  # 5 minutes minimum window
    MAX_APPROVAL_WINDOW_SECONDS: int = 3600  # 1 hour maximum window
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert request to dict"""
        now = time.time()
        return {
            "request_id": self.request_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "expires_in_seconds": max(0, int(self.expires_at - now)),
            "reason": self.reason,
            "status": self.status.value,
            "approvals": [a.to_dict() for a in self.approvals],
            "approval_count": len(self.approvals),
            "required_approvals": self.MIN_APPROVALS_REQUIRED,
            "has_mobile_approval": self._has_mobile_approval(),
            "is_expired": now >= self.expires_at,
        }
    
    def _has_mobile_approval(self) -> bool:
        """Check if request has at least one mobile approval"""
        return any(a.approval_method == ApprovalMethod.MOBILE for a in self.approvals)
    
    def _has_unique_approver(self, approver_id: str) -> bool:
        """Check if approver_id is unique (not already approved)"""
        return approver_id not in [a.approver_id for a in self.approvals]
    
    def can_add_approval(self, approver_id: str) -> Tuple[bool, str]:
        """
        Check if approval can be added.
        
        Returns:
            (allowed: bool, reason: str)
        """
        now = time.time()
        
        # Check if expired
        if now >= self.expires_at:
            return False, "Request has expired"
        
        # Check if already finalized
        if self.status in (ApprovalRequestStatus.APPROVED, ApprovalRequestStatus.ACTIVATED, 
                          ApprovalRequestStatus.REJECTED, ApprovalRequestStatus.REVOKED):
            return False, f"Request is already {self.status.value}"
        
        # Check if approver already approved
        if not self._has_unique_approver(approver_id):
            return False, f"Approver {approver_id} has already approved this request"
        
        return True, "Approval can be added"
    
    def add_approval(
        self,
        approver_id: str,
        approver_role: ApproverRole,
        approval_method: ApprovalMethod,
        device_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Add an approval to this request.
        
        PHASE 4: Enforces mobile confirmation requirement.
        
        Returns:
            (success: bool, message: str)
        """
        can_add, reason = self.can_add_approval(approver_id)
        if not can_add:
            return False, reason
        
        # PHASE 4: Mobile approval requires device_id
        if approval_method == ApprovalMethod.MOBILE and not device_id:
            return False, "Mobile approval requires device_id"
        
        # Create and add approval
        approval = Approval(
            approver_id=approver_id,
            approver_role=approver_role,
            approval_method=approval_method,
            timestamp=time.time(),
            device_id=device_id,
        )
        self.approvals.append(approval)
        
        # Check if request is now approved (has sufficient approvals + mobile approval)
        if (len(self.approvals) >= self.MIN_APPROVALS_REQUIRED and 
            self._has_mobile_approval()):
            self.status = ApprovalRequestStatus.APPROVED
            return True, f"Approval added. Request now APPROVED ({len(self.approvals)}/{self.MIN_APPROVALS_REQUIRED} approvals, mobile present)"
        else:
            mobile_status = "present" if self._has_mobile_approval() else "required"
            return True, f"Approval added ({len(self.approvals)}/{self.MIN_APPROVALS_REQUIRED} approvals, mobile {mobile_status})"
    
    def is_ready_for_activation(self) -> Tuple[bool, str]:
        """
        PHASE 5 — ARMED ACTIVATION CHECK
        
        Check if request is ready for ARMED activation.
        
        Returns:
            (ready: bool, reason: str)
        """
        now = time.time()
        
        # Check if expired
        if now >= self.expires_at:
            return False, "Request has expired"
        
        # Check if already activated
        if self.status == ApprovalRequestStatus.ACTIVATED:
            return False, "Request already activated"
        
        # Check status
        if self.status != ApprovalRequestStatus.APPROVED:
            return False, f"Request status is {self.status.value}, not APPROVED"
        
        # Check approval count
        if len(self.approvals) < self.MIN_APPROVALS_REQUIRED:
            return False, f"Insufficient approvals: {len(self.approvals)}/{self.MIN_APPROVALS_REQUIRED}"
        
        # PHASE 4: Check mobile approval requirement
        if not self._has_mobile_approval():
            return False, "Mobile approval is required but not present"
        
        # Check unique approvers
        approver_ids = [a.approver_id for a in self.approvals]
        if len(approver_ids) != len(set(approver_ids)):
            return False, "Duplicate approvers detected"
        
        return True, "Request is ready for activation"


class ApprovalManager:
    """
    PHASE 3 — PROMOTION REQUEST MANAGER
    
    Manages ARMED promotion requests and approvals.
    Thread-safe, in-memory only (no persistence).
    """
    
    def __init__(self):
        self._requests: Dict[str, ArmedRequest] = {}
        self._lock = threading.Lock()
        self._active_request_id: Optional[str] = None  # Only one active request at a time
    
    def create_request(
        self,
        reason: str,
        approval_window_seconds: int = 900  # 15 minutes default
    ) -> Tuple[Optional[str], str]:
        """
        PHASE 3: Create a new ARMED promotion request.
        
        Rules:
        - Only allowed when engine.state == SHADOW
        - Only one active request at a time
        - Approval window: 5 minutes minimum, 1 hour maximum
        
        Returns:
            (request_id: Optional[str], message: str)
        """
        with self._lock:
            # Check if there's already an active request
            if self._active_request_id:
                active_request = self._requests.get(self._active_request_id)
                if active_request and active_request.status == ApprovalRequestStatus.PENDING:
                    return None, f"Active request already exists: {self._active_request_id}"
            
            # Validate approval window
            if approval_window_seconds < 300:
                approval_window_seconds = 300  # Minimum 5 minutes
            if approval_window_seconds > 3600:
                approval_window_seconds = 3600  # Maximum 1 hour
            
            # Create request
            request_id = str(uuid.uuid4())
            now = time.time()
            request = ArmedRequest(
                request_id=request_id,
                created_at=now,
                expires_at=now + approval_window_seconds,
                reason=reason,
                status=ApprovalRequestStatus.PENDING,
            )
            
            self._requests[request_id] = request
            self._active_request_id = request_id
            
            return request_id, f"ARMED request created: {request_id}"
    
    def get_request(self, request_id: str) -> Optional[ArmedRequest]:
        """Get request by ID"""
        with self._lock:
            return self._requests.get(request_id)
    
    def get_active_request(self) -> Optional[ArmedRequest]:
        """Get active request (if any)"""
        with self._lock:
            if self._active_request_id:
                return self._requests.get(self._active_request_id)
            return None
    
    def add_approval(
        self,
        request_id: str,
        approver_id: str,
        approver_role: ApproverRole,
        approval_method: ApprovalMethod,
        device_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        PHASE 3: Add approval to request.
        
        PHASE 4: Enforces mobile confirmation requirement.
        
        Returns:
            (success: bool, message: str)
        """
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False, f"Request not found: {request_id}"
            
            return request.add_approval(approver_id, approver_role, approval_method, device_id)
    
    def mark_expired(self, request_id: str) -> bool:
        """Mark request as expired"""
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False
            
            now = time.time()
            if now >= request.expires_at and request.status == ApprovalRequestStatus.PENDING:
                request.status = ApprovalRequestStatus.EXPIRED
                if self._active_request_id == request_id:
                    self._active_request_id = None
                return True
            return False
    
    def mark_activated(self, request_id: str) -> bool:
        """Mark request as activated (ARMED state activated)"""
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False
            
            if request.status == ApprovalRequestStatus.APPROVED:
                request.status = ApprovalRequestStatus.ACTIVATED
                # Keep active_request_id so we can track which request activated ARMED
                return True
            return False
    
    def mark_revoked(self, request_id: str) -> bool:
        """Mark request as revoked"""
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False
            
            request.status = ApprovalRequestStatus.REVOKED
            if self._active_request_id == request_id:
                self._active_request_id = None
            return True
    
    def cleanup_expired(self) -> int:
        """Clean up expired requests (returns count cleaned)"""
        with self._lock:
            now = time.time()
            expired_ids = []
            for request_id, request in self._requests.items():
                if now >= request.expires_at and request.status == ApprovalRequestStatus.PENDING:
                    request.status = ApprovalRequestStatus.EXPIRED
                    expired_ids.append(request_id)
            
            for request_id in expired_ids:
                if self._active_request_id == request_id:
                    self._active_request_id = None
            
            return len(expired_ids)


# Global approval manager instance
_approval_manager: Optional[ApprovalManager] = None


def get_approval_manager() -> ApprovalManager:
    """Get global approval manager instance"""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
