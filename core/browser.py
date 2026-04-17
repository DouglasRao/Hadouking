import asyncio
import os
import base64

try:
    from playwright.async_api import async_playwright as _async_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False
    _async_playwright = None

class BrowserManager:
    def __init__(self, headless=True, use_vision=False):
        if not _HAS_PLAYWRIGHT:
            raise ImportError(
                "playwright is not installed. Browser features require it: "
                "pip install playwright && playwright install chromium"
            )
        self.headless = headless
        self.use_vision = use_vision
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.active = False

    async def start(self):
        """Starts the browser session."""
        if self.active:
            return
        if not _HAS_PLAYWRIGHT:
            raise ImportError(
                "playwright is not installed. Install with: "
                "pip install playwright && playwright install chromium"
            )
        self.playwright = await _async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        self.page = await self.context.new_page()
        self.active = True

    async def stop(self):
        """Stops the browser session."""
        if not self.active:
            return

        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        
        self.active = False

    async def navigate(self, url):
        """Navigates to a URL."""
        if not self.active:
            await self.start()
        try:
            await self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
            
            # Auto-fetch interactive elements
            elements = await self.get_interactive_elements()
            return f"Navigated to {url}\n\nInteractive Elements:\n{elements}"
        except Exception as e:
            return f"Error navigating to {url}: {str(e)}"

    async def get_interactive_elements(self):
        """Scans the page for interactive elements and returns a mapped list."""
        if not self.active:
            await self.start()
        if not self.page:
            return "Browser failed to start."
            
        try:
            # Inject script to find interactive elements
            script = """
            () => {
                const elements = document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"]');
                const visibleElements = [];
                let counter = 1;
                
                elements.forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
                        // Generate a simple selector
                        let selector = el.tagName.toLowerCase();
                        if (el.id) {
                            selector += `#${el.id}`;
                        } else if (el.className) {
                            selector += `.${el.className.split(' ').join('.')}`;
                        }
                        
                        // Get text content or value
                        let text = el.innerText || el.value || el.getAttribute('aria-label') || '';
                        text = text.slice(0, 50).replace(/\\n/g, ' '); // Truncate and clean
                        
                        visibleElements.push({
                            index: counter++,
                            tagName: el.tagName.toLowerCase(),
                            text: text,
                            selector: selector,
                            attributes: {
                                type: el.getAttribute('type'),
                                name: el.getAttribute('name'),
                                href: el.getAttribute('href')
                            }
                        });
                    }
                });
                return visibleElements;
            }
            """
            items = await self.page.evaluate(script)
            
            output = []
            for item in items:
                desc = f"[{item['index']}] {item['tagName']}"
                if item['text']:
                    desc += f": {item['text']}"
                if item['attributes']['href']:
                    desc += f" (href: {item['attributes']['href']})"
                
                # We provide a robust selector strategy hint if needed, 
                # but for now we just give the agent the info to construct one or use the simple one.
                # Actually, let's give the agent the simple selector we found, but it might be weak.
                # A better approach for the agent is to use the text or attributes to find it.
                # But to keep it simple for the agent, let's just list them.
                
                desc += f" | Selector: {item['selector']}"
                output.append(desc)
                
            return "\n".join(output) if output else "No interactive elements found."
            
        except Exception as e:
            return f"Error getting interactive elements: {str(e)}"

    async def get_content(self):
        """Returns the page content (text)."""
        if not self.active:
            await self.start()
        if not self.page:
            return "Browser failed to start."
        try:
            # Get visible text
            text = await self.page.evaluate("document.body.innerText")
            return text
        except Exception as e:
            return f"Error getting content: {str(e)}"

    async def screenshot(self, path="screenshot.png"):
        """Takes a screenshot and saves it."""
        if not self.active:
            await self.start()
        if not self.page:
            return "Browser failed to start."
        try:
            await self.page.screenshot(path=path)
            return f"Screenshot saved to {path}"
        except Exception as e:
            return f"Error taking screenshot: {str(e)}"

    async def screenshot_base64(self):
        """Takes a screenshot and returns it as base64 string."""
        if not self.active:
            await self.start()
        if not self.page:
            return None
        try:
            screenshot_bytes = await self.page.screenshot()
            return base64.b64encode(screenshot_bytes).decode('utf-8')
        except Exception as e:
            return None

    async def click(self, selector):
        """Clicks an element."""
        if not self.active:
            await self.start()
        if not self.page:
            return "Browser failed to start."
        try:
            await self.page.click(selector, timeout=5000)
            return f"Clicked {selector}"
        except Exception as e:
            return f"Error clicking {selector}: {str(e)}"

    async def type(self, selector, text):
        """Types text into an element."""
        if not self.active:
            await self.start()
        if not self.page:
            return "Browser failed to start."
        try:
            await self.page.fill(selector, text, timeout=5000)
            return f"Typed '{text}' into {selector}"
        except Exception as e:
            return f"Error typing into {selector}: {str(e)}"

    async def execute_script(self, script):
        """Executes custom JavaScript."""
        if not self.active:
            await self.start()
        if not self.page:
            return "Browser failed to start."
        try:
            result = await self.page.evaluate(script)
            return str(result)
        except Exception as e:
            return f"Error executing script: {str(e)}"
