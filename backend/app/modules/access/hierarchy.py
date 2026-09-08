"""Enterprise Identity & Tenant Hierarchy — Organization, User, Project, Workspace, Device.

Supports:
- Multi-User Organizations (e.g. Alice, Bob, Charlie under Apex Mobility)
- Projects and Workspaces within an Organization
- Device & CLI API Token Generation with scoped capabilities
- Workspace RBAC membership & access delegation
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from app.common.ids import uuid7


class OrgRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


@dataclass
class Organization:
    org_id: str
    name: str
    slug: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "name": self.name,
            "slug": self.slug,
            "created_at": self.created_at.isoformat(),
            "settings": self.settings,
        }


@dataclass
class EnterpriseUser:
    user_id: str
    org_id: str
    email: str
    full_name: str
    role: OrgRole
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "org_id": self.org_id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role.value,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Project:
    project_id: str
    org_id: str
    name: str
    description: str
    created_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "org_id": self.org_id,
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class EnterpriseWorkspace:
    workspace_id: str
    org_id: str
    project_id: str
    name: str
    slug: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "org_id": self.org_id,
            "project_id": self.project_id,
            "name": self.name,
            "slug": self.slug,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class DeviceToken:
    """CLI Machine & Device Authentication Token."""

    token_id: str
    user_id: str
    org_id: str
    workspace_id: str
    device_name: str
    token_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(days=90))
    capabilities: list[str] = field(default_factory=list)


class EnterpriseIdentityStore:
    """In-memory & DB-backed enterprise identity management service."""

    def __init__(self) -> None:
        self._orgs: dict[str, Organization] = {}
        self._users: dict[str, EnterpriseUser] = {}
        self._projects: dict[str, Project] = {}
        self._workspaces: dict[str, EnterpriseWorkspace] = {}
        self._tokens: dict[str, DeviceToken] = {}  # token_hash -> DeviceToken
        self._user_workspaces: dict[str, set[str]] = {}  # user_id -> set(workspace_ids)

    def create_organization(
        self, name: str, slug: str, owner_email: str
    ) -> tuple[Organization, EnterpriseUser]:
        """Create a new tenant organization with an initial owner user."""
        org_id = f"org_{uuid7()}"
        user_id = f"usr_{uuid7()}"

        org = Organization(org_id=org_id, name=name, slug=slug)
        owner = EnterpriseUser(
            user_id=user_id,
            org_id=org_id,
            email=owner_email,
            full_name=owner_email.split("@")[0].title(),
            role=OrgRole.OWNER,
        )

        self._orgs[org_id] = org
        self._users[user_id] = owner
        return org, owner

    def invite_user_to_org(
        self,
        org_id: str,
        email: str,
        full_name: str,
        role: OrgRole = OrgRole.MEMBER,
    ) -> EnterpriseUser:
        """Add a colleague (e.g. Alice inviting Bob) to an existing organization."""
        if org_id not in self._orgs:
            raise ValueError(f"Organization '{org_id}' does not exist")

        user_id = f"usr_{uuid7()}"
        user = EnterpriseUser(
            user_id=user_id,
            org_id=org_id,
            email=email,
            full_name=full_name,
            role=role,
        )
        self._users[user_id] = user
        return user

    def create_project(
        self, org_id: str, name: str, description: str, creator_user_id: str
    ) -> Project:
        """Create a project within the organization."""
        if org_id not in self._orgs:
            raise ValueError(f"Organization '{org_id}' does not exist")

        proj_id = f"proj_{uuid7()}"
        project = Project(
            project_id=proj_id,
            org_id=org_id,
            name=name,
            description=description,
            created_by=creator_user_id,
        )
        self._projects[proj_id] = project
        return project

    def create_workspace(
        self,
        org_id: str,
        project_id: str,
        name: str,
        slug: str,
    ) -> EnterpriseWorkspace:
        """Create a workspace within an organization's project."""
        if org_id not in self._orgs:
            raise ValueError(f"Organization '{org_id}' does not exist")
        if project_id not in self._projects:
            raise ValueError(f"Project '{project_id}' does not exist")

        ws_id = f"ws_{uuid7()}"
        ws = EnterpriseWorkspace(
            workspace_id=ws_id,
            org_id=org_id,
            project_id=project_id,
            name=name,
            slug=slug,
        )
        self._workspaces[ws_id] = ws
        return ws

    def generate_device_token(
        self,
        user_id: str,
        org_id: str,
        workspace_id: str,
        device_name: str,
        capabilities: list[str] | None = None,
    ) -> tuple[str, DeviceToken]:
        """Generate a secure CLI/Device API token for `nexus login`."""
        raw_secret = f"nxt_{os.urandom(24).hex()}"
        token_hash = hashlib.sha256(raw_secret.encode()).hexdigest()

        token_obj = DeviceToken(
            token_id=f"tok_{uuid7()}",
            user_id=user_id,
            org_id=org_id,
            workspace_id=workspace_id,
            device_name=device_name,
            token_hash=token_hash,
            capabilities=capabilities or ["read", "analyze", "propose", "simulate"],
        )
        self._tokens[token_hash] = token_obj
        return raw_secret, token_obj

    def authenticate_device_token(self, raw_secret: str) -> DeviceToken | None:
        """Authenticate an incoming CLI request by token."""
        token_hash = hashlib.sha256(raw_secret.encode()).hexdigest()
        token = self._tokens.get(token_hash)
        if not token:
            return None
        if token.expires_at < datetime.now(UTC):
            return None
        return token

    def list_org_users(self, org_id: str) -> list[EnterpriseUser]:
        """List all users belonging to an organization."""
        return [u for u in self._users.values() if u.org_id == org_id]

    def list_org_workspaces(self, org_id: str) -> list[EnterpriseWorkspace]:
        """List all workspaces belonging to an organization."""
        return [w for w in self._workspaces.values() if w.org_id == org_id]


# Global identity store singleton
_global_identity: EnterpriseIdentityStore | None = None


def get_enterprise_identity_store() -> EnterpriseIdentityStore:
    """Retrieve or initialize the global enterprise identity store."""
    global _global_identity
    if _global_identity is None:
        _global_identity = EnterpriseIdentityStore()
    return _global_identity
