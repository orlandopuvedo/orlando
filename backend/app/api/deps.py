from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db

DB = Depends(get_db)


def to_dict(obj, exclude: set[str] | None = None) -> dict[str, Any]:
    if obj is None:
        return None
    exclude = exclude or set()
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns if c.key not in exclude}


def get_or_404(db: Session, model, id_: int):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


def apply_updates(obj, data: dict, allowed: set[str] | None = None) -> None:
    cols = {c.key for c in obj.__table__.columns} - {"id", "created_at", "updated_at"}
    for k, v in data.items():
        if k in cols and (allowed is None or k in allowed):
            setattr(obj, k, v)
