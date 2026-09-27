"""Guarded HTTP operations for local Language Markdown files."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import config
import lifecycle
from database import get_user_db
from files_base import sources
from modules.language import documents
from suite_modules import require_enabled


def _enabled() -> None:
    try:
        require_enabled("language")
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error


router = APIRouter(prefix="/api/language", dependencies=[Depends(_enabled)])


def _source(connection, source_id: str) -> sources.Source:
    source = sources.get_source(connection, source_id)
    if source is None or source.role != "language" or not source.visible:
        raise HTTPException(404, "Language folder is unavailable")
    return source


def _document_call(operation, *args):
    try:
        return operation(*args)
    except documents.DocumentError as error:
        raise HTTPException(error.status_code, error.detail) from error


class CreateRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=256)


class RenameRequest(CreateRequest):
    name: str = Field(min_length=1, max_length=256)
    new_name: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=64, max_length=64)


class SaveRequest(CreateRequest):
    name: str = Field(min_length=1, max_length=256)
    content: str = Field(max_length=documents.MAX_BYTES)
    revision: str = Field(min_length=64, max_length=64)
    session_id: str = Field(min_length=32, max_length=32)


@router.get("/folders")
def folders():
    with get_user_db() as connection:
        return [{"source_id": source.source_id, "name": source.display_name}
                for source in sources.list_sources(connection) if source.role == "language" and source.visible]


@router.get("/documents")
def list_documents(source_id: str = Query(..., max_length=256)):
    with get_user_db() as connection:
        source = _source(connection, source_id)
        return {"files": _document_call(documents.list_documents, source, config.SUITE_HOME)}


@router.get("/document")
def read_document(source_id: str = Query(..., max_length=256), name: str = Query(..., max_length=256)):
    with get_user_db() as connection:
        source = _source(connection, source_id)
        return _document_call(documents.read_document, source, config.SUITE_HOME, name)


@router.post("/documents")
def create_document(payload: CreateRequest):
    with lifecycle.module_change_lock:
        _enabled()
        with get_user_db() as connection:
            source = _source(connection, payload.source_id)
            result = _document_call(documents.create_document, source, config.SUITE_HOME)
            documents.refresh_index(source, config.FILES_DB_PATH, result["name"])
            return result


@router.post("/document/rename")
def rename_document(payload: RenameRequest):
    with lifecycle.module_change_lock:
        _enabled()
        with get_user_db() as connection:
            source = _source(connection, payload.source_id)
            result = _document_call(documents.rename_document, source, config.SUITE_HOME,
                                    payload.name, payload.new_name, payload.revision)
            documents.refresh_index(source, config.FILES_DB_PATH, result["name"], payload.name)
            return result


@router.put("/document")
def save_document(payload: SaveRequest):
    with lifecycle.module_change_lock:
        _enabled()
        with get_user_db() as connection:
            source = _source(connection, payload.source_id)
            result = _document_call(documents.save_document, source, config.SUITE_HOME,
                                    config.MODULE_REGISTRY.require("language").home,
                                    payload.name, payload.content, payload.revision,
                                    payload.session_id)
            documents.refresh_index(source, config.FILES_DB_PATH, result["name"])
            return result
