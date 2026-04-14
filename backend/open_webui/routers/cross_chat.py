"""APIs: refresh snapshot, continue in new chat, import context, clear import."""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_session
from open_webui.models.chat_context_snapshots import (
    ChatContextSnapshotModel,
    ChatContextSnapshots,
    ContextTransfers,
)
from open_webui.models.chats import ChatForm, ChatResponse, Chats
from open_webui.utils.access_control import has_permission
from open_webui.utils.auth import get_verified_user
from open_webui.utils.cross_chat.prompt_block import format_snapshot_for_prompt
from open_webui.utils.cross_chat.snapshot_llm import llm_build_snapshot

log = logging.getLogger(__name__)

router = APIRouter()


def _cross_chat_enabled(request: Request) -> bool:
    if not request.app.state.config.ENABLE_MEMORIES:
        return False
    return os.environ.get('ENABLE_CROSS_CHAT_CONTEXT', 'true').lower() == 'true'


class RefreshSnapshotBody(BaseModel):
    chat_id: str


class ContinueBody(BaseModel):
    source_chat_id: str


class ImportBody(BaseModel):
    target_chat_id: str
    source_chat_id: str
    refresh_snapshot: bool = True


class ClearImportBody(BaseModel):
    chat_id: str


@router.post('/snapshots/refresh', response_model=Optional[ChatContextSnapshotModel])
async def refresh_snapshot(
    request: Request,
    body: RefreshSnapshotBody,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    if not _cross_chat_enabled(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if not has_permission(user.id, 'features.memories', request.app.state.config.USER_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    src = Chats.get_chat_by_id_and_user_id(body.chat_id, user.id, db=db)
    if not src:
        raise HTTPException(status_code=404, detail='Chat not found')

    task_model = (
        os.environ.get('CROSS_CHAT_SNAPSHOT_MODEL')
        or request.app.state.config.TASK_MODEL
        or next(iter(request.app.state.MODELS.keys()), '')
    )
    snap_data = await llm_build_snapshot(request, user, src.chat, task_model_id=task_model)
    if not snap_data:
        raise HTTPException(status_code=500, detail='Snapshot generation failed')

    title = (src.chat or {}).get('title') or 'Chat'
    model = ChatContextSnapshots.upsert_snapshot(
        user.id,
        body.chat_id,
        title=str(title)[:200],
        summary=snap_data['summary'],
        key_points=snap_data['key_points'],
        preferences=snap_data['preferences'],
        ongoing_tasks=snap_data['ongoing_tasks'],
        constraints=snap_data['constraints'],
        db=db,
    )
    return model


@router.get('/snapshots', response_model=list[ChatContextSnapshotModel])
def list_snapshots(
    request: Request,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    if not _cross_chat_enabled(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if not has_permission(user.id, 'features.memories', request.app.state.config.USER_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)
    return ChatContextSnapshots.list_for_user(user.id, db=db)


@router.get('/snapshots/by-chat/{chat_id}', response_model=Optional[ChatContextSnapshotModel])
def get_snapshot_by_chat(
    chat_id: str,
    request: Request,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    if not _cross_chat_enabled(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if not has_permission(user.id, 'features.memories', request.app.state.config.USER_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)
    if not Chats.is_chat_owner(chat_id, user.id, db=db):
        raise HTTPException(status_code=404, detail='Chat not found')
    return ChatContextSnapshots.get_by_chat_id(user.id, chat_id, db=db)


@router.post('/continue', response_model=ChatResponse)
async def continue_in_new_chat(
    request: Request,
    body: ContinueBody,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    if not _cross_chat_enabled(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if not has_permission(user.id, 'features.memories', request.app.state.config.USER_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    src = Chats.get_chat_by_id_and_user_id(body.source_chat_id, user.id, db=db)
    if not src:
        raise HTTPException(status_code=404, detail='Source chat not found')

    task_model = (
        os.environ.get('CROSS_CHAT_SNAPSHOT_MODEL')
        or request.app.state.config.TASK_MODEL
        or next(iter(request.app.state.MODELS.keys()), '')
    )
    snap_data = await llm_build_snapshot(request, user, src.chat, task_model_id=task_model)
    if not snap_data:
        raise HTTPException(status_code=500, detail='Snapshot generation failed')

    title = (src.chat or {}).get('title') or 'Chat'
    snap = ChatContextSnapshots.upsert_snapshot(
        user.id,
        body.source_chat_id,
        title=str(title)[:200],
        summary=snap_data['summary'],
        key_points=snap_data['key_points'],
        preferences=snap_data['preferences'],
        ongoing_tasks=snap_data['ongoing_tasks'],
        constraints=snap_data['constraints'],
        db=db,
    )
    if not snap:
        raise HTTPException(status_code=500, detail='Could not store snapshot')

    src_models = (src.chat or {}).get('models') or []
    if not isinstance(src_models, list):
        src_models = []
    new_title = f"Continued — {str(title)[:72]}"
    chat_body = {
        'title': new_title,
        'models': src_models,
        'history': {'messages': {}, 'currentId': None},
        'params': (src.chat or {}).get('params') or {},
        'tags': [],
    }
    meta = {
        'cross_chat': {
            'snapshot_id': snap.id,
            'source_chat_id': body.source_chat_id,
            'label': str(title)[:120],
            'mode': 'continue',
        }
    }
    created = Chats.insert_new_chat(
        user.id,
        ChatForm(chat=chat_body, folder_id=src.folder_id, meta=meta),
        db=db,
    )
    if not created:
        raise HTTPException(status_code=400, detail='Could not create chat')

    ContextTransfers.log_transfer(
        user.id,
        body.source_chat_id,
        created.id,
        snap.id,
        'continue',
        db=db,
    )
    return ChatResponse(**created.model_dump())


@router.post('/import', response_model=ChatResponse)
async def import_context(
    request: Request,
    body: ImportBody,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    if not _cross_chat_enabled(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if not has_permission(user.id, 'features.memories', request.app.state.config.USER_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    tgt = Chats.get_chat_by_id_and_user_id(body.target_chat_id, user.id, db=db)
    src = Chats.get_chat_by_id_and_user_id(body.source_chat_id, user.id, db=db)
    if not tgt or not src:
        raise HTTPException(status_code=404, detail='Chat not found')

    snap: ChatContextSnapshotModel | None = None
    if body.refresh_snapshot:
        task_model = (
            os.environ.get('CROSS_CHAT_SNAPSHOT_MODEL')
            or request.app.state.config.TASK_MODEL
            or next(iter(request.app.state.MODELS.keys()), '')
        )
        snap_data = await llm_build_snapshot(request, user, src.chat, task_model_id=task_model)
        if not snap_data:
            raise HTTPException(status_code=500, detail='Snapshot generation failed')
        title = (src.chat or {}).get('title') or 'Chat'
        snap = ChatContextSnapshots.upsert_snapshot(
            user.id,
            body.source_chat_id,
            title=str(title)[:200],
            summary=snap_data['summary'],
            key_points=snap_data['key_points'],
            preferences=snap_data['preferences'],
            ongoing_tasks=snap_data['ongoing_tasks'],
            constraints=snap_data['constraints'],
            db=db,
        )
    else:
        snap = ChatContextSnapshots.get_by_chat_id(user.id, body.source_chat_id, db=db)

    if not snap:
        raise HTTPException(status_code=404, detail='No snapshot for source chat; try refresh first')

    stitle = (src.chat or {}).get('title') or 'Chat'
    updated = Chats.merge_chat_meta_by_id(
        body.target_chat_id,
        user.id,
        {
            'cross_chat': {
                'snapshot_id': snap.id,
                'source_chat_id': body.source_chat_id,
                'label': str(stitle)[:120],
                'mode': 'import',
            }
        },
        db=db,
    )
    if not updated:
        raise HTTPException(status_code=400, detail='Could not update chat')

    ContextTransfers.log_transfer(
        user.id,
        body.source_chat_id,
        body.target_chat_id,
        snap.id,
        'import',
        db=db,
    )
    return ChatResponse(**updated.model_dump())


@router.post('/clear-import', response_model=ChatResponse)
def clear_imported_context(
    request: Request,
    body: ClearImportBody,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    if not _cross_chat_enabled(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if not has_permission(user.id, 'features.memories', request.app.state.config.USER_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    updated = Chats.merge_chat_meta_by_id(body.chat_id, user.id, {'cross_chat': None}, db=db)
    if not updated:
        raise HTTPException(status_code=404, detail='Chat not found')
    return ChatResponse(**updated.model_dump())


@router.get('/preview/{snapshot_id}')
def preview_prompt_block(
    snapshot_id: str,
    request: Request,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    if not _cross_chat_enabled(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if not has_permission(user.id, 'features.memories', request.app.state.config.USER_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    snap = ChatContextSnapshots.get_by_id(snapshot_id, db=db)
    if not snap or snap.user_id != user.id:
        raise HTTPException(status_code=404, detail='Snapshot not found')
    return {'text': format_snapshot_for_prompt(snap)}
