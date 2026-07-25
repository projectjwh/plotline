import asyncio
import random
import os
from datetime import datetime
from playwright.async_api import async_playwright, Page, BrowserContext
import yaml

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
with open(CONFIG_PATH, "r") as f:
    CONFIG = yaml.safe_load(f)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
]

class WebComicScraper:
    def __init__(self, headless=True):
        self.headless = headless
        self.browser = None
        self.context = None
        
    async def start(self):
        """Initialize the browser with stealth settings."""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=self.headless)
        
        # Configure context for stealth
        self.context = await self.browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1920, 'height': 1080},
            java_script_enabled=True,
            has_touch=False
        )
        
        # Add stealth scripts (simplified version - normally we'd inject more)
        await self.context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    async def _random_sleep(self):
        """Sleep for a random interval to mimic human behavior."""
        min_delay = CONFIG['scraping']['min_delay_seconds']
        max_delay = CONFIG['scraping']['max_delay_seconds']
        delay = random.uniform(min_delay, max_delay)
        print(f"Sleeping for {delay:.2f}s...")
        await asyncio.sleep(delay)

    async def fetch_page_snapshot(self, url: str, save_prefix: str, source_name: str) -> str:
        """
        Navigates to a URL, scrolls to load content, and saves the HTML.
        Returns the path to the saved file.
        """
        page = await self.context.new_page()
        
        try:
            print(f"Navigating to {url}...")
            await page.goto(url, wait_until="networkidle", timeout=CONFIG['scraping']['timeout_seconds'] * 1000)
            
            # Simulate scrolling to trigger lazy loading
            await self._simulate_scroll(page)
            
            await self._random_sleep()
            
            # Save Snapshot
            today = datetime.now().strftime("%Y-%m-%d")
            base_dir = os.path.join(CONFIG['storage']['bronze_path'], source_name, today)
            os.makedirs(base_dir, exist_ok=True)
            
            filename = f"{save_prefix}_{int(datetime.now().timestamp())}.html"
            filepath = os.path.join(base_dir, filename)
            
            content = await page.content()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
            print(f"Snapshot saved to {filepath}")
            return filepath
            
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return None
        finally:
            await page.close()

    async def _simulate_scroll(self, page: Page):
        """Scroll down the page slowly to trigger lazy loaded elements."""
        previous_height = await page.evaluate("document.body.scrollHeight")
        
        while True:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000) # Wait for load
            
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == previous_height:
                break
            previous_height = new_height

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()

    async def extract_comic_links(self, page: Page) -> list[str]:
        """Extracts comic detail URLs from a listing page."""
        # Selector for Webtoon 'Daily' and 'Genre' cards
        # Note: These selectors are based on common patterns and might need tuning
        selectors = [
            "ul.daily_card li a.daily_card_item", 
            "ul.card_lst li a",
            "ul.webtoon_list li a.link"
        ]
        
        urls = set()
        for selector in selectors:
            elements = await page.locator(selector).all()
            for el in elements:
                href = await el.get_attribute("href")
                if href:
                    if not href.startswith("http"):
                        href = CONFIG['scraping']['targets']['webtoon_global']['base_url'] + href
                    urls.add(href)
        
        print(f"Found {len(urls)} comic links.")
        return list(urls)

    async def run_daily_cycle(self):
        """Orchestrates the daily scraping routine for ALL targets (High Volume)."""
        await self.start()
        
        try:
            targets = CONFIG['scraping']['targets']
            print(f"Starting cycle for {len(targets)} targets: {list(targets.keys())}")
            
            for source_name, config in targets.items():
                print(f"\n--- Processing Target: {source_name} ---")
                try:
                    urls_to_scrape = []
                    
                    # 1. Add Daily/Ranking URL
                    if config.get('daily_schedule_url'):
                        urls_to_scrape.append(('daily_schedule', config['daily_schedule_url']))
                        
                    # 2. Add Genre URLs (if configured)
                    if config.get('genres') and config.get('genre_url_template'):
                        for genre in config['genres']:
                            url = config['genre_url_template'].format(genre_name=genre)
                            urls_to_scrape.append((f"listing_{genre}", url))
                            
                    print(f"[{source_name}] Found {len(urls_to_scrape)} listing pages to scrape.")
                    
                    # 3. Scrape All Listings (Bronze Layer)
                    extracted_links = set()
                    
                    for page_type, url in urls_to_scrape:
                        print(f"  -> Fetching {page_type}: {url}")
                        filepath = await self.fetch_page_snapshot(url, page_type, source_name)
                        
                        if filepath:
                            # Quick link extraction to find details
                            from bs4 import BeautifulSoup
                            with open(filepath, 'r', encoding='utf-8') as f:
                                soup = BeautifulSoup(f.read(), 'html.parser')
                            
                            # Heuristic Link Extraction
                            # We want to find "comic detail" links
                            for a in soup.find_all('a', href=True):
                                href = a['href']
                                # Basic filters for Webtoon/Generic
                                is_comic = False
                                
                                # Webtoon specific
                                if source_name == 'webtoon_global':
                                    if "title_no=" in href and "episode_no=" not in href: is_comic = True
                                
                                # Generic filter
                                elif "series" in href or "comic" in href or "novel" in href:
                                    is_comic = True
                                    
                                if is_comic:
                                    full_url = href if href.startswith("http") else config.get('base_url', '') + href
                                    extracted_links.add(full_url)
                                    
                    print(f"[{source_name}] Unique comic links found: {len(extracted_links)}")
                    
                    # 4. Deep Scrape (Optional / Sample)
                    # User said "find as many LISTINGS as possible", which implies the listing parsing is key.
                    # Deep scraping 1000s of links takes hours. We'll grab a sample 'Deep' set, 
                    # but rely on the listing snapshots for the bulk stats.
                    
                    deep_limit = 5 
                    print(f"[{source_name}] Deep scraping top {deep_limit} for detailed metadata...")
                    for idx, url in enumerate(list(extracted_links)[:deep_limit]):
                         await self.fetch_page_snapshot(url, "comic_detail", source_name)

                except Exception as e:
                    print(f"Error processing {source_name}: {e}")
                
        finally:
            await self.close()

async def main():
    scraper = WebComicScraper(headless=CONFIG['scraping']['headless'])
    await scraper.run_daily_cycle()

if __name__ == "__main__":
    asyncio.run(main())
