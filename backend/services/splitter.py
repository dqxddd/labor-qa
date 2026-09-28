"""文本切分：把长文按 500 字一段切开，相邻段重叠 80 字。

9.16 参数都从 config 里取，不要在这里写死，
调优的时候只动 .env 就行。
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.core.config import CHUNK_SIZE, CHUNK_OVERLAP


def build_splitter():
    # 分隔符按优先级排，先按段落切，切不动再按句号、分号，最后才硬按字数切
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "；", "！", "？", "，", ""],
        keep_separator=True,
    )


def split_text(text):
    """返回片段列表，空片段丢掉"""
    pieces = build_splitter().split_text(text)
    return [p.strip() for p in pieces if p.strip()]
