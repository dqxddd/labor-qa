from datetime import datetime

from sqlalchemy import Column, Integer, Text, DateTime, Float, ForeignKey

from backend.core.db import Base
from backend.models.document import Chunk  # noqa: F401 保证建表时能解析到引用关系


# 9.18 评测用例表，先把表建出来，评测脚本后面再写
class EvalCase(Base):
    __tablename__ = "eval_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    expect_type = Column(Text, nullable=False)
    expect_answer = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


# 9.18 评测结果表，同上，功能还没做
class EvalResult(Base):
    __tablename__ = "eval_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Text, nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("eval_cases.id"), nullable=False)
    answer = Column(Text)
    refused = Column(Integer, nullable=False, default=0)
    correct = Column(Integer, nullable=False, default=0)
    hit_rate = Column(Float, nullable=False, default=0)
    run_at = Column(DateTime, nullable=False, default=datetime.now)
