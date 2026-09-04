"""
Sakura AI — Web Search Service
Provides live web search via Tavily Search API (priority) or DuckDuckGo HTML fallback.
Returns structured search results and citations for use in interactive chat and background research tasks.
"""
import os
import json
import urllib.request
import urllib.parse
import re
import asyncio
from typing import Dict, Any, List, Optional


def get_web_search_status() -> Dict[str, Any]:
    """Returns the current operational status of the web search subsystem."""
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key and tavily_key.strip():
        return {
            "status": "AVAILABLE",
            "provider": "tavily",
            "has_api_key": True,
            "description": "Tavily Search API with structured citations"
        }
    return {
        "status": "AVAILABLE",
        "provider": "duckduckgo",
        "has_api_key": False,
        "description": "DuckDuckGo Web Search Fallback"
    }


async def perform_web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Performs live search on the web.
    Returns a dictionary containing structured results, citations, formatted text, and provider metadata.
    """
    query = (query or "").strip()
    if not query:
        return {
            "success": False,
            "provider": None,
            "query": query,
            "results": [],
            "formatted": "Empty search query provided.",
            "error": "Empty query"
        }

    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key and tavily_key.strip():
        try:
            def run_tavily():
                req_data = json.dumps({
                    "api_key": tavily_key.strip(),
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": True
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.tavily.com/search",
                    data=req_data,
                    headers={"Content-Type": "application/json", "User-Agent": "SakuraAI/1.0"}
                )
                with urllib.request.urlopen(req, timeout=12) as response:
                    return json.loads(response.read().decode("utf-8"))

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, run_tavily)
            results = []
            formatted_parts = []
            if data.get("answer"):
                formatted_parts.append(f"Direct Answer: {data['answer']}\n")

            for i, r in enumerate(data.get("results", [])[:max_results]):
                title = r.get("title", f"Result {i+1}").strip()
                snippet = r.get("content", "").strip()
                url = r.get("url", "").strip()
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                    "source_index": i + 1
                })
                formatted_parts.append(f"[{i+1}] {title}\n{snippet}\nSource: {url}")

            if results:
                return {
                    "success": True,
                    "provider": "tavily",
                    "query": query,
                    "results": results,
                    "formatted": "\n\n".join(formatted_parts),
                    "error": None
                }
        except Exception as e:
            # Fall back to DuckDuckGo on error
            pass

    # DuckDuckGo HTML fallback
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )

        def run_ddg():
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('utf-8', errors='ignore')

        loop = asyncio.get_event_loop()
        html = await loop.run_in_executor(None, run_ddg)

        snippets = re.findall(r'<a class="result-snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        urls = re.findall(r'<a class="result__url"[^>]*href="([^"]*)"', html, re.DOTALL)
        if not snippets:
            snippets = re.findall(r'<td class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)
        if not snippets:
            snippets = re.findall(r'<div class="result__snippet"[^>]*>(.*?)</div>', html, re.DOTALL)

        results = []
        formatted_parts = []
        for i, snip in enumerate(snippets[:max_results]):
            clean_snip = re.sub(r'<[^>]+>', '', snip).strip()
            source_url = urls[i].strip() if i < len(urls) else "https://duckduckgo.com"
            results.append({
                "title": f"Web Result {i+1}",
                "snippet": clean_snip,
                "url": source_url,
                "source_index": i + 1
            })
            formatted_parts.append(f"[{i+1}] {clean_snip}\nSource: {source_url}")

        if results:
            return {
                "success": True,
                "provider": "duckduckgo",
                "query": query,
                "results": results,
                "formatted": "\n\n".join(formatted_parts),
                "error": None
            }
        return {
            "success": False,
            "provider": "duckduckgo",
            "query": query,
            "results": [],
            "formatted": f"No web search results found for '{query}'.",
            "error": "No results returned"
        }
    except Exception as e:
        return {
            "success": False,
            "provider": None,
            "query": query,
            "results": [],
            "formatted": f"Web search provider temporarily unavailable: {str(e)}",
            "error": str(e)
        }
