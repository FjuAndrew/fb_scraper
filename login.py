"""
Step 1: 手動登入 Facebook，儲存 session
執行後會開啟瀏覽器視窗，你手動登入後按 Enter 儲存 session
之後爬蟲就不需要再登入
"""
from playwright.sync_api import sync_playwright

def save_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 有介面，讓你手動登入
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://www.facebook.com/")

        print("=" * 50)
        print("瀏覽器已開啟，請手動登入 Facebook")
        print("登入完成後回到這裡按 Enter")
        print("=" * 50)
        input("登入完成後按 Enter...")

        # 儲存 session
        context.storage_state(path="session.json")
        print("✅ Session 已儲存到 session.json")
        browser.close()

if __name__ == "__main__":
    save_session()