"""Request schemas (Pydantic v2). Unknown fields are rejected on every
mutating endpoint (CLAUDE.md §7 input handling)."""

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from solus_api.core.config import Settings
from solus_api.models import (
    Activity,
    Invite,
    Job,
    Membership,
    Notification,
    Project,
    Role,
    Team,
    User,
    ensure_utc,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _not_blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


class UserUpdate(StrictModel):
    name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)


class SettingsUpdate(StrictModel):
    sol_mode: Literal["guide", "expert"] | None = None


class TeamCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)

    _name_not_blank = field_validator("name")(_not_blank)


class TeamUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)

    _name_not_blank = field_validator("name")(_not_blank)


class MemberRoleUpdate(StrictModel):
    role: Literal["owner", "admin", "member", "viewer"]


class InviteCreate(StrictModel):
    email: EmailStr
    # Owner is granted only via the members route, by an existing owner.
    role: Literal["admin", "member", "viewer"] = "member"


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)

    _name_not_blank = field_validator("name")(_not_blank)


class ProjectUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)

    _name_not_blank = field_validator("name")(_not_blank)


# --- Response serializers (snake_case dicts inside the §1.4 envelope) ---


def serialize_team_summary(team: Team, role: Role, settings: Settings) -> dict[str, Any]:
    return {
        "team_id": team.id,
        "name": team.name,
        "role": role.value,
        "is_personal": team.is_personal,
        "plan_status": team.plan_status,
        "trial_ends_at": ensure_utc(team.created_at) + timedelta(days=settings.trial_days),
    }


def serialize_user(user: User, teams: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at,
        "teams": teams,
    }


def serialize_team_detail(team: Team, role: Role, member_count: int) -> dict[str, Any]:
    return {
        "id": team.id,
        "name": team.name,
        "is_personal": team.is_personal,
        "plan_status": team.plan_status,
        "created_at": team.created_at,
        "member_count": member_count,
        "role": role.value,
    }


def serialize_member(membership: Membership, user: User) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "role": membership.role.value,
        "joined_at": membership.created_at,
    }


def serialize_invite(invite: Invite, *, include_token: bool = False) -> dict[str, Any]:
    data = {
        "id": invite.id,
        "team_id": invite.team_id,
        "email": invite.email,
        "role": invite.role.value,
        "status": invite.status.value,
        "created_at": invite.created_at,
        "expires_at": invite.expires_at,
    }
    if include_token:
        # Secret shown once at creation (§2.1 pattern) — never on listings.
        data["token"] = invite.token
    return data


def serialize_project(project: Project, *, detail: bool = False) -> dict[str, Any]:
    data = {
        "id": project.id,
        "team_id": project.team_id,
        "name": project.name,
        "description": project.description,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
    if detail:
        # Graph stats and connected sources arrive with Phases 2–3.
        data["stats"] = {"entities": 0, "relations": 0}
        data["sources"] = []
    return data


def serialize_job(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "kind": job.kind.value,
        "status": job.status.value,
        "progress": job.progress,
        "result_ref": job.result_ref,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
    }


def serialize_notification(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "payload": notification.payload,
        "read_at": notification.read_at,
        "created_at": notification.created_at,
    }


def serialize_activity(activity: Activity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "type": activity.type,
        "domain": activity.domain,
        "actor_id": activity.actor_id,
        "project_id": activity.project_id,
        "payload": activity.payload,
        "created_at": activity.created_at,
    }
