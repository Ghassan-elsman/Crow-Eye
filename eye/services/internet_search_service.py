"""
Internet Search Service for EYE AI Assistant.

This module provides real-time web research capabilities using DuckDuckGo.
It is designed to be lightweight, privacy-focused, and requires no API keys.
"""

import urllib.request
import urllib.parse
import logging
from typing import List, Dict, Any
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def _require_http_url(url: str) -> None:
    """Raise ValueError unless ``url`` is an http(s) URL with a hostname.

    Defense in depth before any ``urlopen`` call: blocks ``file://``, ``ftp://``,
    ``data:`` and other schemes so the fetcher can never read local files or
    reach non-web resources, regardless of how the caller validated the URL.
    """
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Refusing non-HTTP(S) URL: {url!r}")


class InternetSearchService:
    """
    Service for performing forensic research on the internet.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Performs a search on DuckDuckGo and returns structured results.
        """
        if not BeautifulSoup:
            return {
                "success": False, 
                "error": "BeautifulSoup4 is not installed. Please run: pip install beautifulsoup4"
            }
            
        try:
            self.logger.info(f"Initiating web search: {query}")
            
            # Use the Lite version of DuckDuckGo for better stability in scripts
            encoded_query = urllib.parse.quote(query)
            url = f"https://lite.duckduckgo.com/lite/?q={encoded_query}"
            _require_http_url(url)  # defense in depth (fixed https endpoint)

            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://lite.duckduckgo.com/',
                'Upgrade-Insecure-Requests': '1'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read()
                
            soup = BeautifulSoup(html, 'html.parser')
            results = []
            
            # DuckDuckGo Lite HTML structure parsing
            for result in soup.find_all('table', class_='result-links')[:max_results]:
                title_elem = result.find('a', class_='result-link')
                snippet_elem = result.find_next_sibling('table').find('td', class_='result-snippet') if result.find_next_sibling('table') else None
                
                if title_elem:
                    results.append({
                        "title": title_elem.get_text().strip(),
                        "snippet": snippet_elem.get_text().strip() if snippet_elem else "No snippet available.",
                        "source_url": title_elem.get('href')
                    })
            
            if not results:
                return {
                    "success": True,
                    "message": "Search completed, but no direct matches were found. Try a broader query.",
                    "results": []
                }
                
            return {
                "success": True,
                "message": f"Successfully retrieved {len(results)} forensic research results.",
                "results": results
            }
            
        except Exception as e:
            self.logger.error(f"Web search failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Network Error: Unable to reach search engine. Details: {str(e)}"
            }

    def fetch_page_content(self, url: str) -> Dict[str, Any]:
        """
        Downloads a web page and extracts its main text content.
        
        Args:
            url: The URL of the page to fetch.
            
        Returns:
            Dictionary containing success status, title, and cleaned content.
        """
        if not BeautifulSoup:
            return {
                "success": False, 
                "error": "BeautifulSoup4 is not installed. Technical extraction requires this library."
            }

        try:
            # Hard scheme guard: never let urlopen handle file://, ftp://, etc.
            _require_http_url(url)

            self.logger.info(f"Fetching technical content from: {url}")

            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read()
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove noise
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                element.decompose()
                
            title = soup.title.string.strip() if soup.title else "Technical Page"
            
            # Extract content from main body or article
            content_body = soup.find('main') or soup.find('article') or soup.find('body')
            
            if not content_body:
                return {"success": False, "error": "No readable content found on the page."}
                
            text_content = content_body.get_text(separator='\n', strip=True)
            
            # Clean up consecutive newlines
            import re
            text_content = re.sub(r'\n{3,}', '\n\n', text_content)
            
            if len(text_content) > 15000:
                text_content = text_content[:15000] + "\n\n... [CONTENT TRUNCATED FOR CONTEXT EFFICIENCY] ..."
            
            return {
                "success": True,
                "title": title,
                "content": text_content,
                "url": url
            }
            
        except Exception as e:
            self.logger.error(f"Failed to fetch page content: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Technical Retrieval Error: {str(e)}"
            }
