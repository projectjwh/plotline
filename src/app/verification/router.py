from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from src.app.context import AppContext
from src.app.deps import get_ctx, signed_in, verified
from src.app.entitlement.service import Viewer

router = APIRouter(tags=["verification"])


@router.post("/claims", status_code=201, summary="Submit an ownership/authority claim with documents")
async def submit(claim_type: str = Form(...), entity_ref: str = Form(...), role: str | None = Form(None),
                 entity_name: str | None = Form(None), files: list[UploadFile] = File(...),
                 v: Viewer = Depends(verified), ctx: AppContext = Depends(get_ctx)):
    limit = ctx.policy.app("verification", "max_file_mb", default=10) * 1024 * 1024
    blobs = [await f.read(limit + 1) for f in files]  # read at most limit+1 bytes; the service rejects oversize
    return ctx.verification.submit(v, claim_type, entity_ref, role, blobs, entity_name)


@router.get("/claims/mine")
def mine(v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return ctx.verification.mine(v)


@router.post("/claims/{claim_id}/withdraw", summary="Withdraw a pending claim; its documents are deleted now")
def withdraw(claim_id: str, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return ctx.verification.withdraw(v, claim_id)
