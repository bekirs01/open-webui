"""Compact per-chat snapshots for cross-chat continuity (not full transcripts)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from open_webui.internal.db import Base, get_db_context

log = logging.getLogger(__name__)


class ChatContextSnapshot(Base):
    __tablename__ = 'chat_context_snapshot'
    __table_args__ = (UniqueConstraint('user_id', 'chat_id', name='uq_snapshot_user_chat'),)

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    chat_id = Column(String, nullable=False, index=True)
    title = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    key_points = Column(Text, nullable=True)  # JSON list
    preferences = Column(Text, nullable=True)
    ongoing_tasks = Column(Text, nullable=True)
    constraints = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


class ContextTransfer(Base):
    __tablename__ = 'context_transfer'

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    source_chat_id = Column(Text, nullable=False)
    target_chat_id = Column(Text, nullable=False)
    snapshot_id = Column(Text, nullable=True)
    transfer_mode = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)


class ChatContextSnapshotModel(BaseModel):
    id: str
    user_id: str
    chat_id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    key_points: Optional[list[str]] = None
    preferences: Optional[list[str]] = None
    ongoing_tasks: Optional[list[str]] = None
    constraints: Optional[list[str]] = None
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


def _loads_json_list(raw: Optional[str]) -> Optional[list[str]]:
    if not raw:
        return None
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else None
    except Exception:
        return None


def _row_to_model(row: ChatContextSnapshot) -> ChatContextSnapshotModel:
    return ChatContextSnapshotModel(
        id=row.id,
        user_id=row.user_id,
        chat_id=row.chat_id,
        title=row.title,
        summary=row.summary,
        key_points=_loads_json_list(row.key_points),
        preferences=_loads_json_list(row.preferences),
        ongoing_tasks=_loads_json_list(row.ongoing_tasks),
        constraints=_loads_json_list(row.constraints),
        created_at=int(row.created_at),
        updated_at=int(row.updated_at),
    )


class ChatContextSnapshotsTable:
    def upsert_snapshot(
        self,
        user_id: str,
        chat_id: str,
        *,
        title: Optional[str],
        summary: str,
        key_points: list[str],
        preferences: list[str],
        ongoing_tasks: list[str],
        constraints: list[str],
        db: Optional[Session] = None,
    ) -> Optional[ChatContextSnapshotModel]:
        now = int(time.time())
        with get_db_context(db) as db:
            existing = (
                db.query(ChatContextSnapshot)
                .filter_by(user_id=user_id, chat_id=chat_id)
                .first()
            )
            if existing:
                existing.title = title
                existing.summary = summary
                existing.key_points = json.dumps(key_points, ensure_ascii=False)
                existing.preferences = json.dumps(preferences, ensure_ascii=False)
                existing.ongoing_tasks = json.dumps(ongoing_tasks, ensure_ascii=False)
                existing.constraints = json.dumps(constraints, ensure_ascii=False)
                existing.updated_at = now
                db.commit()
                db.refresh(existing)
                return _row_to_model(existing)
            sid = str(uuid.uuid4())
            row = ChatContextSnapshot(
                id=sid,
                user_id=user_id,
                chat_id=chat_id,
                title=title,
                summary=summary,
                key_points=json.dumps(key_points, ensure_ascii=False),
                preferences=json.dumps(preferences, ensure_ascii=False),
                ongoing_tasks=json.dumps(ongoing_tasks, ensure_ascii=False),
                constraints=json.dumps(constraints, ensure_ascii=False),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _row_to_model(row)

    def get_by_id(self, snapshot_id: str, db: Optional[Session] = None) -> Optional[ChatContextSnapshotModel]:
        with get_db_context(db) as db:
            row = db.get(ChatContextSnapshot, snapshot_id)
            return _row_to_model(row) if row else None

    def get_by_chat_id(
        self, user_id: str, chat_id: str, db: Optional[Session] = None
    ) -> Optional[ChatContextSnapshotModel]:
        with get_db_context(db) as db:
            row = (
                db.query(ChatContextSnapshot)
                .filter_by(user_id=user_id, chat_id=chat_id)
                .first()
            )
            return _row_to_model(row) if row else None

    def list_for_user(self, user_id: str, limit: int = 80, db: Optional[Session] = None) -> list[ChatContextSnapshotModel]:
        with get_db_context(db) as db:
            rows = (
                db.query(ChatContextSnapshot)
                .filter_by(user_id=user_id)
                .order_by(ChatContextSnapshot.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_model(r) for r in rows]

    def delete_by_chat_id(self, user_id: str, chat_id: str, db: Optional[Session] = None) -> bool:
        with get_db_context(db) as db:
            q = db.query(ChatContextSnapshot).filter_by(user_id=user_id, chat_id=chat_id)
            n = q.delete()
            db.commit()
            return n > 0


class ContextTransfersTable:
    def log_transfer(
        self,
        user_id: str,
        source_chat_id: str,
        target_chat_id: str,
        snapshot_id: Optional[str],
        transfer_mode: str,
        db: Optional[Session] = None,
    ) -> None:
        now = int(time.time())
        tid = str(uuid.uuid4())
        with get_db_context(db) as db:
            db.add(
                ContextTransfer(
                    id=tid,
                    user_id=user_id,
                    source_chat_id=source_chat_id,
                    target_chat_id=target_chat_id,
                    snapshot_id=snapshot_id,
                    transfer_mode=transfer_mode,
                    created_at=now,
                )
            )
            db.commit()


ChatContextSnapshots = ChatContextSnapshotsTable()
ContextTransfers = ContextTransfersTable()
