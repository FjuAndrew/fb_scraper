"""
scraper.py - 根據實際 Facebook DOM 結構重寫
"""
import re
import time
import random
import sqlite3
import hashlib
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
import os
from dotenv import load_dotenv

load_dotenv()

GROUP_URL = os.getenv("GROUP_URL", "https://www.facebook.com/groups/443709852472133")
DB_PATH = "fbdata.db"
THREE_MONTHS_AGO = datetime.now() - timedelta(days=90)


# ── 資料庫 ────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            author      TEXT NOT NULL,
            parent_id   TEXT,
            scraped_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] 資料庫初始化完成")


def save_items(items: list[dict]) -> int:
    if not items:
        return 0
    conn = sqlite3.connect(DB_PATH)
    new_count = 0
    for item in items:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO contents
                (id, type, content, created_at, author, parent_id, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                item["id"], item["type"], item["content"],
                item["created_at"], item["author"],
                item.get("parent_id"), item["scraped_at"]
            ))
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                new_count += 1
        except Exception as e:
            print(f"[DB] 儲存失敗: {e}")
    conn.commit()
    conn.close()
    return new_count


def get_total_count() -> tuple[int, int]:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("""
        SELECT
            COUNT(CASE WHEN type='post' THEN 1 END),
            COUNT(CASE WHEN type='comment' THEN 1 END)
        FROM contents
    """).fetchone()
    conn.close()
    return row[0] or 0, row[1] or 0


def make_id(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:16]


# ── 時間解析 ──────────────────────────────────

def parse_time_from_aria(aria_label: str, now: datetime) -> str:
    """
    從留言的 aria-label 解析時間
    格式: '謝承融的留言3小時前' 或 '舞波比的留言昨天'
    """
    # 移除作者和「的留言」部分，只留時間
    text = re.sub(r'^.+的留言', '', aria_label).strip()
    return parse_relative_time(text, now)


def parse_time_from_link(text: str, now: datetime) -> str:
    """從貼文時間連結的混淆文字解析時間"""
    # 移除英文垃圾字元，保留數字和中文
    cleaned = re.sub(r'[a-zA-Z\s]', '', text)
    return parse_relative_time(cleaned, now)


def parse_relative_time(text: str, now: datetime) -> str:
    """解析相對或絕對時間字串"""
    # 完整日期: 月 日 上午/下午 時:分
    if '月' in text and '日' in text:
        try:
            nums = re.findall(r'\d+', text)
            month_idx = text.find('月')
            day_idx = text.find('日')
            colon_idx = text.find(':')

            before_month = re.findall(r'\d+', text[:month_idx])
            after_month = re.findall(r'\d+', text[month_idx:day_idx])

            if before_month and after_month:
                month = int(before_month[-1])
                day = int(after_month[-1])
                hour, minute = 0, 0

                if colon_idx > 0:
                    before_colon = re.findall(r'\d+', text[day_idx:colon_idx])
                    after_colon = re.findall(r'\d+', text[colon_idx+1:colon_idx+5])
                    if before_colon:
                        hour = int(before_colon[-1])
                    if after_colon:
                        minute = int(after_colon[0])
                    if '下午' in text and hour < 12:
                        hour += 12

                year = now.year
                dt = datetime(year, month, day, hour, minute)
                if dt > now:
                    dt = datetime(year - 1, month, day, hour, minute)
                return dt.isoformat()
        except Exception:
            pass

    # 昨天
    if '昨天' in text:
        colon_idx = text.find(':')
        if colon_idx > 0:
            try:
                before_colon = re.findall(r'\d+', text[:colon_idx])
                after_colon = re.findall(r'\d+', text[colon_idx+1:colon_idx+5])
                hour = int(before_colon[-1]) if before_colon else 0
                minute = int(after_colon[0]) if after_colon else 0
                if '下午' in text and hour < 12:
                    hour += 12
                dt = now - timedelta(days=1)
                return dt.replace(hour=hour, minute=minute, second=0).isoformat()
            except Exception:
                pass
        return (now - timedelta(days=1)).isoformat()

    # 小時前
    if '小' in text and '時' in text:
        idx = text.find('小')
        nums = re.findall(r'\d+', text[:idx])
        if nums:
            return (now - timedelta(hours=int(nums[-1]))).isoformat()

    # 分鐘前
    if '分' in text:
        idx = text.find('分')
        nums = re.findall(r'\d+', text[:idx])
        if nums:
            return (now - timedelta(minutes=int(nums[-1]))).isoformat()

    # 天前
    if '天' in text:
        idx = text.find('天')
        nums = re.findall(r'\d+', text[:idx])
        if nums:
            return (now - timedelta(days=int(nums[-1]))).isoformat()

    # 週前
    if '週' in text:
        idx = text.find('週')
        nums = re.findall(r'\d+', text[:idx])
        if nums:
            return (now - timedelta(weeks=int(nums[-1]))).isoformat()

    # 上午/下午 HH:MM（今天，無日期）
    if ('上午' in text or '下午' in text) and ':' in text:
        try:
            colon_idx = text.find(':')
            before_colon = re.findall(r'\d+', text[:colon_idx])
            after_colon = re.findall(r'\d+', text[colon_idx+1:colon_idx+5])
            if before_colon:
                hour = int(before_colon[-1])
                minute = int(after_colon[0]) if after_colon else 0
                if '下午' in text and hour < 12:
                    hour += 12
                elif '上午' in text and hour == 12:
                    hour = 0
                return now.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()
        except Exception:
            pass

    # 剛剛
    if '剛剛' in text:
        return now.isoformat()

    return now.isoformat()


# ── 工具 ─────────────────────────────────────

def human_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))


# ── 主爬蟲 ────────────────────────────────────

class FBGroupScraper:

    def __init__(self):
        self.pw = None
        self.browser = None
        self.page = None
        self.scraped_ids = set()
        self._now = datetime.now()  # 固定 session 開始時間，確保相對時間計算一致

    def start(self):
        if not os.path.exists("session.json"):
            raise FileNotFoundError("找不到 session.json，請先執行 login.py")

        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = self.browser.new_context(
            storage_state="session.json",
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
        )
        self.page = context.new_page()
        stealth_sync(self.page)
        print("[Browser] 瀏覽器啟動完成")

    def stop(self):
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

    def go_to_group(self):
        print(f"[Nav] 前往社團: {GROUP_URL}")
        self.page.goto(GROUP_URL, wait_until="domcontentloaded", timeout=30000)
        human_delay(3, 5)
        if "login" in self.page.url or "checkpoint" in self.page.url:
            raise RuntimeError("Session 已過期，請重新執行 login.py")
        print("[Nav] 成功進入社團頁面")

    def dismiss_popups(self):
        for sel in [
            '[aria-label="關閉"]', '[aria-label="Close"]',
            'div[role="button"]:has-text("不用了")',
            'div[role="button"]:has-text("略過")',
        ]:
            try:
                btn = self.page.query_selector(sel)
                if btn:
                    btn.click()
                    human_delay(0.5, 1)
            except Exception:
                pass

    def _expand_post_content(self, card):
        """展開貼文的查看更多"""
        try:
            msg = card.query_selector('[data-ad-rendering-role="story_message"]')
            if msg:
                see_more = msg.query_selector(
                    'div[role="button"]:has-text("查看更多"), '
                    'div[role="button"]:has-text("See more")'
                )
                if see_more:
                    see_more.click()
                    human_delay(0.5, 1)
        except Exception:
            pass

    def _get_post_time(self, card) -> str:
        """從貼文時間連結取得時間，優先使用 span[title] 精確屬性"""
        try:
            links = card.query_selector_all('a')
            best_text = ""
            best_score = 0

            for link in links:
                # 優先：從 span[title] 取得精確時間（Facebook 標準格式）
                for span in link.query_selector_all('span[title]'):
                    title = span.get_attribute("title") or ""
                    if '年' in title and '月' in title:
                        cleaned = re.sub(r'\s+', '', title)
                        parsed = parse_relative_time(cleaned, self._now)
                        if parsed != self._now.isoformat():
                            return parsed

                # Fallback：從連結文字解析
                text = link.inner_text().strip()
                if not text or len(text) < 3:
                    continue
                score = 0
                if '月' in text and '日' in text:
                    score += 5
                if '下午' in text or '上午' in text:
                    score += 3
                if ':' in text:
                    score += 2
                if '昨天' in text:
                    score += 4
                if '小' in text and '時' in text:
                    score += 2
                if '分' in text:
                    score += 1
                if '天' in text or '週' in text:
                    score += 1
                if '剛剛' in text:
                    score += 1

                if score > best_score:
                    best_score = score
                    best_text = text

            if best_text and best_score > 0:
                return parse_time_from_link(best_text, self._now)
        except Exception:
            pass
        return self._now.isoformat()

    def _parse_post(self, card, now_str: str) -> dict | None:
        """解析貼文"""
        # 內容
        content_el = card.query_selector('[data-ad-rendering-role="story_message"]')
        if not content_el:
            return None
        content = content_el.inner_text().strip()
        if not content or len(content) < 5:
            return None

        # 作者（只取名字，不要打卡地點）
        author = "未知用戶"
        profile_el = card.query_selector('[data-ad-rendering-role="profile_name"]')
        if profile_el:
            # 只取第一行（名字），避免抓到打卡地點
            full_text = profile_el.inner_text().strip()
            author = full_text.split('\n')[0].strip()

        # 時間
        created_at = self._get_post_time(card)

        post_id = make_id(f"post_{author}_{created_at}_{content[:50]}")

        return {
            "id": post_id,
            "type": "post",
            "content": content,
            "created_at": created_at,
            "author": author,
            "parent_id": None,
            "scraped_at": now_str,
        }

    def _parse_comments(self, card, post_id: str, now_str: str) -> list[dict]:
        """解析留言"""
        comments = []

        # 不做任何 click（避免觸發頁面導航或 scroll 重置），直接讀取可見留言

        # 找留言元素
        comment_els = card.query_selector_all('[role="article"]')

        for el in comment_els:
            try:
                aria_label = el.get_attribute("aria-label") or ""
                if '留言' not in aria_label:
                    continue

                # 作者和時間從 aria-label 解析
                # 格式: '謝承融的留言3小時前'
                author_match = re.match(r'^(.+?)的留言', aria_label)
                author = author_match.group(1) if author_match else "未知用戶"
                created_at = parse_time_from_aria(aria_label, self._now)

                # 內容：取 dir="auto" 的第三個（跳過作者名和「作者」標籤）
                dir_auto_els = el.query_selector_all('[dir="auto"]')
                content = ""
                texts = []
                for d in dir_auto_els:
                    t = d.inner_text().strip()
                    if t and t != author and t != '作者':
                        texts.append(t)

                if texts:
                    # 取最長的那個作為留言內容
                    content = max(texts, key=len)

                if not content:
                    continue

                comment_id = make_id(f"comment_{post_id}_{author}_{content[:30]}")
                comments.append({
                    "id": comment_id,
                    "type": "comment",
                    "content": content,
                    "created_at": created_at,
                    "author": author,
                    "parent_id": post_id,
                    "scraped_at": now_str,
                })
            except Exception:
                continue

        return comments

    def _process_new_cards(self, now_str: str) -> bool:
        """處理頁面上新出現的貼文卡片"""
        cards = self.page.query_selector_all('div[style*="card-corner-radius"]')
        reached_old = False 

        for card in cards:
            if not card.query_selector('[data-ad-rendering-role="story_message"]'):
                continue

            try:
                post = self._parse_post(card, now_str)
                if not post:
                    continue

                card_key = post["id"]
                if card_key in self.scraped_ids:
                    continue
                self.scraped_ids.add(card_key)

                comments = self._parse_comments(card, post["id"], now_str)
                save_items([post] + comments)

                total_posts, total_comments = get_total_count()
                print(f"\n{'─'*50}")
                print(f"  作者 : {post['author']}")
                print(f"  時間 : {post['created_at'][:19]}")
                print(f"  內容 : {post['content'][:80]}{'...' if len(post['content']) > 80 else ''}")
                print(f"  留言 : {len(comments)} 則")
                for c in comments[:2]:
                    print(f"    └ [{c['author']}] {c['content'][:40]}")
                if len(comments) > 2:
                    print(f"    └ ...還有 {len(comments)-2} 則")
                print(f"  [累計] {total_posts} 篇貼文 / {total_comments} 則留言")

            except Exception as e:
                print(f"[Parse] 失敗: {e}")

        return reached_old

    def run(self):
        print("=" * 50)
        print("Facebook 社團爬蟲啟動")
        print(f"目標: {GROUP_URL}")
        print(f"收錄範圍: 全部")
        print("=" * 50)

        init_db()
        self.start()

        try:
            self.go_to_group()
            self.dismiss_popups()

            now_str = datetime.now().isoformat()

            MAX_BATCHES = 300
            SCROLL_PX = 1200       # 每次滾動量（漸進式，避免觸發虛擬 DOM 回收）
            SCROLLS_PER_BATCH = 3  # 每批滾幾次後立即收割
            no_new_batches = 0
            last_scroll_y = -1
            stuck_count = 0

            for batch in range(MAX_BATCHES):
                # 漸進式滾動（不跳到底部，避免 Facebook 回收頂部節點）
                for _ in range(SCROLLS_PER_BATCH):
                    self.page.mouse.wheel(0, SCROLL_PX)
                    human_delay(0.8, 1.2)

                # 等待新內容載入
                try:
                    self.page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                human_delay(1.5, 2.5)

                # 用 scrollY 判斷是否真的滾動了（比 scrollHeight 可靠）
                current_y = self.page.evaluate("window.scrollY")
                if current_y <= last_scroll_y:
                    stuck_count += 1
                else:
                    stuck_count = 0
                    last_scroll_y = current_y

                # 立即收割（趁貼文還在 DOM 中）
                try:
                    before = len(self.scraped_ids)
                    reached_old = self._process_new_cards(now_str)
                    new_found = len(self.scraped_ids) - before

                    # 若 comment_btn.click() 導致頁面捲回頂部，恢復位置
                    post_y = self.page.evaluate("window.scrollY")
                    if post_y < current_y - 1000:
                        self.page.evaluate(f"window.scrollTo(0, {current_y})")
                        human_delay(0.5, 1)

                    print(f"\n[Batch {batch+1}] scrollY={current_y} 新增 {new_found} 篇")
                except Exception as e:
                    print(f"[警告] 頁面狀態異常，停止: {e}")
                    break

                if reached_old:
                    print("\n[完成] 已抓到三個月前的貼文，停止")
                    break

                # 卡住（scrollY 不再增加）且無新內容 → 到底了
                if stuck_count >= 3 and new_found == 0:
                    print("[完成] 已到頁面底部，停止")
                    break

                if new_found == 0:
                    no_new_batches += 1
                    if no_new_batches >= 15:
                        print("[完成] 連續 15 批無新內容，停止")
                        break
                else:
                    no_new_batches = 0

        finally:
            self.stop()
            total_posts, total_comments = get_total_count()
            print("\n" + "=" * 50)
            print(f"[完成] 爬蟲結束")
            print(f"   貼文: {total_posts} 篇")
            print(f"   留言: {total_comments} 則")
            print(f"   資料位置: {DB_PATH}")
            print("=" * 50)


if __name__ == "__main__":
    scraper = FBGroupScraper()
    scraper.run()       