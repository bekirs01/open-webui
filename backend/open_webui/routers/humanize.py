"""
humanize.py — FastAPI router for the Humanize feature.

POST /api/humanize
  Accepts: { "text": str, "intensity": float (0.0–1.0) }
  Returns: humanize_text() result dict
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from open_webui.utils.auth import get_verified_user
from open_webui.utils.humanizer import humanize_text

router = APIRouter()


class HumanizeRequest(BaseModel):
    text: str
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)


@router.post("")
async def humanize(
    body: HumanizeRequest,
    user=Depends(get_verified_user),
):
    """
    Rewrite AI-generated text to sound more human using local NLP.
    Requires a verified (logged-in) user.
    """
    return humanize_text(body.text, body.intensity)
