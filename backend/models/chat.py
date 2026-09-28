from datetime import datetime

from sqlalchemy import Column, Integer, Text, DateTime, Float, ForeignKey

from backend.core.db import Base
from backend.models.document import Chunk  # 引用表的定义要先被加载，不然建表时找不到 chunks


# 9.17 会话表：一次连续对话算一条
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


# 9.17 消息表：用户问的和系统答的都存这，refused 标记这条是不是拒答
class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    refused = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "refused": self.refused,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


# 9.17 引用记录：回答里 [1][2] 这些编号对应的原文片段，做溯源用
class Citation(Base):
    __tablename__ = "citations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), nullable=False)
    cite_index = Column(Integer, nullable=False)
    score = Column(Float, nullable=False, default=0)
    snippet = Column(Text, nullable=False)


# 工具调用记录。9.18 建表占位，9.22 晚业务工具上线后开始真的往里写
# （见 services/tools.py 和 qa._tool_round），事后复盘"当时算的是哪一天"靠它
class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id"))
    tool_name = Column(Text, nullable=False)
    arguments = Column(Text, nullable=False, default="{}")
    result = Column(Text)
    status = Column(Text, nullable=False, default="success")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
