from datetime import datetime

from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey

from backend.core.db import Base


# 9.15 资料表：上传的法规文件都记在这里，字段照设计文档 5.3.1 写
class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(Text, nullable=False, unique=True)
    file_type = Column(Text, nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    status = Column(Text, nullable=False, default="pending")
    chunk_count = Column(Integer, nullable=False, default=0)
    error_msg = Column(Text)
    upload_time = Column(DateTime, nullable=False, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "status": self.status,
            "chunk_count": self.chunk_count,
            "error_msg": self.error_msg,
            "upload_time": self.upload_time.strftime("%Y-%m-%d %H:%M:%S") if self.upload_time else None,
        }


# 9.17 片段表：一份资料切成好几段，doc_id 指回资料表
class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    page = Column(Integer)
    token_count = Column(Integer, nullable=False, default=0)
    vector_id = Column(Text, nullable=False, unique=True)

    def to_dict(self):
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "page": self.page,
            "token_count": self.token_count,
            "vector_id": self.vector_id,
        }
