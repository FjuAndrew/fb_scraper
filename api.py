"""
Step 3: 啟動 RESTful API
執行: python api.py
文件: http://localhost:8000/docs
"""
import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional, Literal
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = "fbdata.db"

app = FastAPI(
    title="Facebook Group Content API",
    description="Facebook 社團貼文與留言查詢 API",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Schemas ───────────────────────────────────

class ContentItem(BaseModel):
    id: str
    type: str           # post | comment
    content: str
    created_at: str
    author: str
    parent_id: Optional[str] = None

class Meta(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int

class ContentResponse(BaseModel):
    data: list[ContentItem]
    meta: Meta

class StatsResponse(BaseModel):
    total_posts: int
    total_comments: int
    total: int
    earliest: Optional[str]
    latest: Optional[str]


# ── Helper ────────────────────────────────────

def query_db(sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def query_one(sql: str, params: tuple = ()):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


# ── Endpoints ─────────────────────────────────

@app.get("/", summary="Health Check")
def root():
    return {"status": "ok", "message": "Facebook Group Content API is running 🚀"}


@app.get(
    "/api/v1/contents",
    response_model=ContentResponse,
    summary="查詢貼文與留言",
    description="""
查詢近三個月 Facebook 社團的貼文與留言。

**欄位說明：**
- `type`: `post`（主文）或 `comment`（留言）
- `content`: 內容文字
- `created_at`: 發文時間（ISO 格式）
- `author`: 發文者 / 留言者名稱
- `parent_id`: 留言所屬的貼文 ID（主文為 null）
    """,
)
def get_contents(
    type: Optional[Literal["post", "comment"]] = Query(None, description="類型：post | comment"),
    start_date: Optional[date] = Query(None, description="開始日期 YYYY-MM-DD"),
    end_date: Optional[date] = Query(None, description="結束日期 YYYY-MM-DD"),
    author: Optional[str] = Query(None, description="發文者名稱（模糊搜尋）"),
    keyword: Optional[str] = Query(None, description="內容關鍵字搜尋"),
    page: int = Query(1, ge=1, description="頁碼"),
    limit: int = Query(20, ge=1, le=100, description="每頁筆數"),
):
    # 預設近三個月
    if not start_date:
        start_date = (datetime.now() - timedelta(days=90)).date()
    if not end_date:
        end_date = datetime.now().date()

    conditions = ["created_at >= ?", "created_at <= ?"]
    params = [str(start_date), str(end_date) + "T23:59:59"]

    if type:
        conditions.append("type = ?")
        params.append(type)
    if author:
        conditions.append("author LIKE ?")
        params.append(f"%{author}%")
    if keyword:
        conditions.append("content LIKE ?")
        params.append(f"%{keyword}%")

    where = " AND ".join(conditions)

    total = query_one(f"SELECT COUNT(*) FROM contents WHERE {where}", tuple(params))[0]

    offset = (page - 1) * limit
    rows = query_db(
        f"SELECT id, type, content, created_at, author, parent_id "
        f"FROM contents WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset)
    )

    return ContentResponse(
        data=[ContentItem(**r) for r in rows],
        meta=Meta(
            total=total,
            page=page,
            limit=limit,
            total_pages=max(1, -(-total // limit))
        )
    )


@app.get(
    "/api/v1/contents/{content_id}",
    response_model=ContentItem,
    summary="查詢單筆內容"
)
def get_by_id(content_id: str):
    rows = query_db("SELECT * FROM contents WHERE id = ?", (content_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="找不到此筆資料")
    return ContentItem(**rows[0])


@app.get(
    "/api/v1/posts/{post_id}/comments",
    response_model=ContentResponse,
    summary="查詢某貼文的所有留言"
)
def get_comments(
    post_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    total = query_one(
        "SELECT COUNT(*) FROM contents WHERE parent_id = ? AND type = 'comment'",
        (post_id,)
    )[0]

    offset = (page - 1) * limit
    rows = query_db(
        "SELECT id, type, content, created_at, author, parent_id "
        "FROM contents WHERE parent_id = ? AND type = 'comment' "
        "ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (post_id, limit, offset)
    )

    return ContentResponse(
        data=[ContentItem(**r) for r in rows],
        meta=Meta(total=total, page=page, limit=limit,
                  total_pages=max(1, -(-total // limit)))
    )


@app.get(
    "/api/v1/stats",
    response_model=StatsResponse,
    summary="資料統計"
)
def get_stats():
    row = query_one("""
        SELECT
            COUNT(CASE WHEN type='post' THEN 1 END)    as total_posts,
            COUNT(CASE WHEN type='comment' THEN 1 END) as total_comments,
            COUNT(*)                                    as total,
            MIN(created_at)                             as earliest,
            MAX(created_at)                             as latest
        FROM contents
    """)
    return StatsResponse(
        total_posts=row[0] or 0,
        total_comments=row[1] or 0,
        total=row[2] or 0,
        earliest=row[3],
        latest=row[4],
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)