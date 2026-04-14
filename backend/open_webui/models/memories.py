import json
import time
import uuid
from typing import Any, Optional

from sqlalchemy import BigInteger, Column, Float, String, Text, or_
from sqlalchemy.orm import Session

from open_webui.internal.db import Base, JSONField, get_db, get_db_context
from pydantic import BaseModel, ConfigDict, Field

####################
# Memory DB Schema
####################


class Memory(Base):
    __tablename__ = 'memory'

    id = Column(String, primary_key=True, unique=True)
    user_id = Column(String)
    content = Column(Text)
    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)
    # Long-term memory extensions (nullable for legacy rows)
    chat_id = Column(Text, nullable=True)
    category = Column(Text, nullable=True)
    normalized_content = Column(Text, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    importance_score = Column(Float, nullable=True)
    last_accessed_at = Column(BigInteger, nullable=True)
    access_count = Column(BigInteger, nullable=True)
    status = Column(Text, nullable=True)
    source_type = Column(Text, nullable=True)
    ltm_extra = Column(Text, nullable=True)
    folder_id = Column(Text, nullable=True)


class MemoryModel(BaseModel):
    id: str
    user_id: str
    content: str
    updated_at: int
    created_at: int
    chat_id: Optional[str] = None
    category: Optional[str] = None
    normalized_content: Optional[str] = None
    source_excerpt: Optional[str] = None
    confidence_score: Optional[float] = None
    importance_score: Optional[float] = None
    last_accessed_at: Optional[int] = None
    access_count: Optional[int] = None
    status: Optional[str] = None
    source_type: Optional[str] = None
    ltm_extra: Optional[dict[str, Any]] = None
    folder_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


def _row_to_model(m: Memory) -> MemoryModel:
    extra = None
    if getattr(m, 'ltm_extra', None):
        try:
            extra = json.loads(m.ltm_extra) if isinstance(m.ltm_extra, str) else m.ltm_extra
        except Exception:
            extra = None
    return MemoryModel(
        id=m.id,
        user_id=m.user_id,
        content=m.content or '',
        created_at=int(m.created_at or 0),
        updated_at=int(m.updated_at or 0),
        chat_id=getattr(m, 'chat_id', None),
        category=getattr(m, 'category', None),
        normalized_content=getattr(m, 'normalized_content', None),
        source_excerpt=getattr(m, 'source_excerpt', None),
        confidence_score=getattr(m, 'confidence_score', None),
        importance_score=getattr(m, 'importance_score', None),
        last_accessed_at=int(m.last_accessed_at) if getattr(m, 'last_accessed_at', None) is not None else None,
        access_count=int(m.access_count) if getattr(m, 'access_count', None) is not None else None,
        status=getattr(m, 'status', None),
        source_type=getattr(m, 'source_type', None),
        ltm_extra=extra,
        folder_id=getattr(m, 'folder_id', None),
    )


class MemoriesTable:
    def insert_new_memory(
        self,
        user_id: str,
        content: str,
        db: Optional[Session] = None,
        *,
        chat_id: Optional[str] = None,
        category: str = 'custom',
        normalized_content: Optional[str] = None,
        source_excerpt: Optional[str] = None,
        confidence_score: float = 1.0,
        importance_score: float = 0.75,
        source_type: str = 'manual',
        status: str = 'active',
        ltm_extra: Optional[dict] = None,
        folder_id: Optional[str] = None,
    ) -> Optional[MemoryModel]:
        with get_db_context(db) as db:
            mid = str(uuid.uuid4())
            now = int(time.time())
            nc = normalized_content or content
            row = Memory(
                **{
                    'id': mid,
                    'user_id': user_id,
                    'content': content,
                    'created_at': now,
                    'updated_at': now,
                    'chat_id': chat_id,
                    'category': category,
                    'normalized_content': nc,
                    'source_excerpt': source_excerpt,
                    'confidence_score': confidence_score,
                    'importance_score': importance_score,
                    'last_accessed_at': None,
                    'access_count': 0,
                    'status': status,
                    'source_type': source_type,
                    'ltm_extra': json.dumps(ltm_extra) if ltm_extra else None,
                    'folder_id': folder_id,
                }
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _row_to_model(row)

    def update_memory_by_id_and_user_id(
        self,
        id: str,
        user_id: str,
        content: str,
        db: Optional[Session] = None,
        **fields: Any,
    ) -> Optional[MemoryModel]:
        with get_db_context(db) as db:
            try:
                memory = db.get(Memory, id)
                if not memory or memory.user_id != user_id:
                    return None

                memory.content = content
                memory.updated_at = int(time.time())
                if fields.get('normalized_content') is not None:
                    memory.normalized_content = fields['normalized_content']
                else:
                    from open_webui.utils.long_term_memory.safety import normalize_for_dedupe

                    memory.normalized_content = normalize_for_dedupe(content)
                for k in (
                    'category',
                    'status',
                    'importance_score',
                    'confidence_score',
                    'source_excerpt',
                    'chat_id',
                    'source_type',
                    'folder_id',
                ):
                    if k in fields and fields[k] is not None:
                        setattr(memory, k, fields[k])
                if 'ltm_extra' in fields and fields['ltm_extra'] is not None:
                    memory.ltm_extra = json.dumps(fields['ltm_extra'])

                db.commit()
                db.refresh(memory)
                return _row_to_model(memory)
            except Exception:
                return None

    def increment_access(self, id: str, user_id: str, db: Optional[Session] = None) -> None:
        with get_db_context(db) as db:
            m = db.get(Memory, id)
            if not m or m.user_id != user_id:
                return
            n = int(m.access_count or 0)
            m.access_count = n + 1
            m.last_accessed_at = int(time.time())
            db.commit()

    def get_memories(self, db: Optional[Session] = None) -> Optional[list[MemoryModel]]:
        with get_db_context(db) as db:
            try:
                memories = db.query(Memory).all()
                return [_row_to_model(memory) for memory in memories]
            except Exception:
                return None

    def get_memories_by_user_id(
        self,
        user_id: str,
        db: Optional[Session] = None,
        *,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> list[MemoryModel]:
        with get_db_context(db) as db:
            try:
                qry = db.query(Memory).filter_by(user_id=user_id)
                if status == 'active':
                    qry = qry.filter(or_(Memory.status == 'active', Memory.status == None))
                elif status:
                    qry = qry.filter(Memory.status == status)
                memories = qry.order_by(Memory.updated_at.desc()).all()
                out = [_row_to_model(m) for m in memories]
                if q and q.strip():
                    low = q.strip().lower()
                    out = [m for m in out if low in (m.content or '').lower() or low in (m.category or '').lower()]
                return out
            except Exception:
                return []

    def get_memory_by_id(self, id: str, db: Optional[Session] = None) -> Optional[MemoryModel]:
        with get_db_context(db) as db:
            try:
                memory = db.get(Memory, id)
                return _row_to_model(memory) if memory else None
            except Exception:
                return None

    def delete_memory_by_id(self, id: str, db: Optional[Session] = None) -> bool:
        with get_db_context(db) as db:
            try:
                db.query(Memory).filter_by(id=id).delete()
                db.commit()
                return True
            except Exception:
                return False

    def delete_memories_by_user_id(self, user_id: str, db: Optional[Session] = None) -> bool:
        with get_db_context(db) as db:
            try:
                db.query(Memory).filter_by(user_id=user_id).delete()
                db.commit()
                return True
            except Exception:
                return False

    def delete_memory_by_id_and_user_id(self, id: str, user_id: str, db: Optional[Session] = None) -> bool:
        with get_db_context(db) as db:
            try:
                memory = db.get(Memory, id)
                if not memory or memory.user_id != user_id:
                    return False
                db.delete(memory)
                db.commit()
                return True
            except Exception:
                return False

    def archive_stale_memories(
        self,
        user_id: str,
        *,
        stale_days: int = 90,
        min_access_count: int = 1,
        min_importance: float = 0.3,
        db: Optional[Session] = None,
    ) -> int:
        """Archive memories that are old, rarely accessed, and low-importance."""
        cutoff = int(time.time()) - (stale_days * 86400)
        archived = 0
        with get_db_context(db) as db:
            try:
                rows = (
                    db.query(Memory)
                    .filter_by(user_id=user_id)
                    .filter(or_(Memory.status == 'active', Memory.status == None))
                    .all()
                )
                for m in rows:
                    ts = int(m.last_accessed_at or m.updated_at or m.created_at or 0)
                    ac = int(m.access_count or 0)
                    imp = float(m.importance_score or 0.5)
                    if ts < cutoff and ac <= min_access_count and imp < min_importance:
                        m.status = 'archived'
                        m.updated_at = int(time.time())
                        archived += 1
                if archived:
                    db.commit()
            except Exception:
                pass
        return archived

    def get_memory_stats(self, user_id: str, db: Optional[Session] = None) -> dict[str, Any]:
        """Return summary stats for a user's memories."""
        with get_db_context(db) as db:
            try:
                rows = db.query(Memory).filter_by(user_id=user_id).all()
                total = len(rows)
                active = sum(1 for r in rows if (r.status or 'active') == 'active')
                archived = sum(1 for r in rows if r.status == 'archived')
                cats: dict[str, int] = {}
                for r in rows:
                    c = r.category or 'custom'
                    cats[c] = cats.get(c, 0) + 1
                return {
                    'total': total,
                    'active': active,
                    'archived': archived,
                    'categories': cats,
                }
            except Exception:
                return {'total': 0, 'active': 0, 'archived': 0, 'categories': {}}


Memories = MemoriesTable()
