# Facebook 社團爬蟲 + RESTful API

爬取指定 Facebook 社團的近三個月貼文與留言，並透過 RESTful API 提供查詢。

---

## 快速查看資料（已有現成資料庫）

repo 內已附上爬取好的 `fbdata.db`，不需要重新執行爬蟲，直接啟動 API 即可查看資料：

```bash
pip install fastapi uvicorn
python api.py
```

開啟瀏覽器前往 `http://localhost:8000/docs` 即可使用互動式查詢介面。

---

## 環境需求

- Python 3.10+
- 安裝套件：

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## 使用步驟

### Step 1：登入 Facebook，儲存 Session

```bash
python login.py
```

瀏覽器會開啟，手動登入 Facebook 後按 Enter，session 會儲存到 `session.json`。

### Step 2：執行爬蟲

```bash
python scraper.py
```

爬取 Facebook 社團貼文與留言，資料存入 `fbdata.db`（SQLite）。

### Step 3：啟動 API

```bash
python api.py
```

API 預設在 `http://localhost:8000` 執行。
互動式文件：`http://localhost:8000/docs`

---

## API 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/v1/contents` | 查詢貼文與留言（支援篩選、分頁） |
| GET | `/api/v1/contents/{id}` | 查詢單筆內容 |
| GET | `/api/v1/posts/{post_id}/comments` | 查詢某貼文的所有留言 |
| GET | `/api/v1/stats` | 資料統計 |

### 回傳欄位

| 欄位 | 說明 |
|------|------|
| `type` | `post`（主文）或 `comment`（留言） |
| `content` | 內容文字 |
| `created_at` | 發文時間（ISO 格式） |
| `author` | 發文者 / 留言者名稱 |
| `parent_id` | 留言所屬貼文 ID（主文為 null） |

### 查詢參數（`GET /api/v1/contents`）

| 參數 | 說明 |
|------|------|
| `type` | `post` 或 `comment` |
| `start_date` | 開始日期 `YYYY-MM-DD` |
| `end_date` | 結束日期 `YYYY-MM-DD` |
| `author` | 作者名稱（模糊搜尋） |
| `keyword` | 內容關鍵字 |
| `page` / `limit` | 分頁（預設 page=1, limit=20） |

---

## 注意事項

- `session.json` 包含 Facebook 登入憑證，**請勿上傳至公開儲存庫**（已加入 `.gitignore`）
- 爬蟲使用增量滾動方式，避免觸發 Facebook 虛擬 DOM 重置
