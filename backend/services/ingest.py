"""入库：解析文件 -> 切分 -> 写 chunks 表 -> 重建检索索引。

9.18 现在整个流程是同步的，上传接口会一直等到跑完。
资料都不大（几十 KB），先这样，文件多了再改成后台任务。
"""

import os

from backend.core.config import UPLOAD_DIR
from backend.core.db import SessionLocal
from backend.models.document import Chunk, Document
from backend.services import indexer, loader, splitter


def _build_vector_id(doc_id, chunk_index):
    # 和简易索引 json 里的 key 对应，换成 Chroma 之后这里改成真实向量 id
    return "vec-%d-%d" % (doc_id, chunk_index)


def ingest_document(doc_id, file_path, file_type):
    """把一个已经落盘的文件切成片段入库，返回处理结果"""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            return {"ok": False, "msg": "资料记录不存在"}

        try:
            text = loader.load_text(file_path, file_type)
            pieces = splitter.split_text(text)
            if not pieces:
                raise loader.ParseError("切分之后没有内容")

            # 重新入库时先把老片段清掉
            db.query(Chunk).filter(Chunk.doc_id == doc.id).delete()
            for i, piece in enumerate(pieces, start=1):
                db.add(Chunk(
                    doc_id=doc.id,
                    chunk_index=i,
                    content=piece,
                    token_count=len(piece),
                    vector_id=_build_vector_id(doc.id, i),
                ))
            doc.chunk_count = len(pieces)
            doc.status = "ready"
            doc.error_msg = None
            db.commit()
        except loader.ParseError as e:
            doc.status = "failed"
            doc.error_msg = str(e)
            db.commit()
            return {"ok": False, "msg": str(e), "doc": doc.to_dict()}

        result = doc.to_dict()
    finally:
        db.close()

    indexer.build_index()   # 片段变了要重建索引（关键词 + 向量两条一起）
    return {"ok": True, "msg": "入库完成，共 %d 个片段" % result["chunk_count"], "doc": result}


def delete_document(doc_id):
    """删资料：片段、原始文件、索引一起清掉"""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            return False
        file_path = os.path.join(UPLOAD_DIR, doc.file_name)
        db.query(Chunk).filter(Chunk.doc_id == doc.id).delete()
        db.delete(doc)
        db.commit()
    finally:
        db.close()

    if os.path.exists(file_path):
        os.remove(file_path)
    indexer.build_index()
    return True


def import_sample_files():
    """把 data/knowledge 下的示例资料批量入库，演示用"""
    from backend.core.config import BASE_DIR

    folder = os.path.join(BASE_DIR, "data", "knowledge")
    if not os.path.isdir(folder):
        return {"ok": False, "msg": "示例资料目录不存在：%s" % folder, "count": 0}

    done = []
    for name in sorted(os.listdir(folder)):
        file_type = os.path.splitext(name)[1].lstrip(".").lower()
        if file_type not in loader.SUPPORTED_TYPES:
            continue

        db = SessionLocal()
        try:
            exists = db.query(Document).filter(Document.file_name == name).first()
            if exists is not None:
                continue
            doc = Document(file_name=name, file_type=file_type,
                           file_size=os.path.getsize(os.path.join(folder, name)))
            db.add(doc)
            db.commit()
            doc_id = doc.id
        finally:
            db.close()

        result = ingest_document(doc_id, os.path.join(folder, name), file_type)
        done.append({"file_name": name, "ok": result["ok"], "msg": result["msg"]})

    return {"ok": True, "msg": "导入结束", "count": len(done), "items": done}
