"""资料管理接口：上传、列表、查看片段、删除、导入示例资料。

9.18 上传是一次性的同步流程，传完就解析入库了，前端等几秒。
按设计文档，格式不支持或者解析出错都会写进 documents 表，
status=failed，error_msg 记原因，不直接把文件丢掉。
"""

import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.core.config import UPLOAD_DIR
from backend.core.db import SessionLocal
from backend.models.document import Chunk, Document
from backend.services import ingest

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _safe_name(name):
    """去掉路径成分，防止有人传 ../../x.md 这种文件名"""
    name = os.path.basename(name or "")
    return name.replace("..", "_").strip() or "未命名.md"


@router.post("")
async def upload_document(file: UploadFile = File(...)):
    file_name = _safe_name(file.filename)
    file_type = os.path.splitext(file_name)[1].lstrip(".").lower()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件是空的")

    save_path = os.path.join(UPLOAD_DIR, file_name)
    with open(save_path, "wb") as f:
        f.write(content)

    db = SessionLocal()
    try:
        # 同名文件重传：先把老记录和它的片段清掉，再重新入库
        old = db.query(Document).filter(Document.file_name == file_name).first()
        if old is not None:
            db.query(Chunk).filter(Chunk.doc_id == old.id).delete()
            db.delete(old)
            db.commit()

        doc = Document(file_name=file_name, file_type=file_type, file_size=len(content))
        db.add(doc)
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    result = ingest.ingest_document(doc_id, save_path, file_type)
    return result


@router.post("/import-samples")
def import_samples():
    """一键导入 data/knowledge 下的示例资料，演示时用"""
    return ingest.import_sample_files()


@router.get("")
def list_documents():
    db = SessionLocal()
    try:
        docs = db.query(Document).order_by(Document.id.desc()).all()
        return {"total": len(docs), "items": [d.to_dict() for d in docs]}
    finally:
        db.close()


@router.get("/{doc_id}/chunks")
def list_chunks(doc_id: int):
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            raise HTTPException(status_code=404, detail="资料不存在")
        chunks = (db.query(Chunk).filter(Chunk.doc_id == doc_id)
                  .order_by(Chunk.chunk_index).all())
        return {
            "doc": doc.to_dict(),
            "total": len(chunks),
            "items": [c.to_dict() for c in chunks],
        }
    finally:
        db.close()


@router.delete("/{doc_id}")
def delete_document(doc_id: int):
    ok = ingest.delete_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="资料不存在")
    return {"ok": True, "msg": "已删除，片段和索引一起清掉了"}
