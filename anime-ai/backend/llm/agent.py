"""
Sakura AI — Agentic Tool Loop

Wraps the LLM in an agentic loop that can call tools (RAG search, memory lookup, 
code analysis, web search, image generation, deep research, multi-modal analysis,
visualization, and code workspace) autonomously across multiple iterations before
producing a final response.
"""

import json
import asyncio
import os
import re
import uuid
from typing import List, Dict, Any, Optional, AsyncGenerator
from sqlalchemy.orm import Session
from llm.router import LLMRouter
from rag.retrieval import HybridRetriever
from rag.embeddings.manager import EmbeddingManager
from memory.manager import MemoryManager
from database.models import Document, DocumentChunk


# ─── Tool Definitions (OpenAI function-calling format) ────────────────────────

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the live web for current events, news, or general real-time information. Use this when the user asks about live or recent facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up on the web."
                }
            },
            "required": ["query"]
        }
    }
}

CREATE_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "create_image",
        "description": "Generate an image, artwork, illustration, anime scene, photo, logo, wallpaper, or UI mockup based on a descriptive text prompt. Use this whenever the user asks to draw, generate, paint, design, or create any visual artwork or image.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The detailed visual prompt of the image to generate."
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "3:2", "2:3"],
                    "description": "Optional aspect ratio (e.g. 16:9 for desktop wallpaper, 9:16 for phone, 1:1 for square/avatar/logo)."
                }
            },
            "required": ["prompt"]
        }
    }
}

EDIT_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_image",
        "description": "Edit or modify a previously generated image in the conversation. Use this when the user asks to change, add, remove, recolor, or modify elements of an existing image in chat (e.g., 'Change the background to Tokyo', 'Make the jacket black', 'Add cherry blossoms', 'Make it darker').",
        "parameters": {
            "type": "object",
            "properties": {
                "edit_instruction": {
                    "type": "string",
                    "description": "The specific modification instruction to apply to the existing image."
                },
                "image_id": {
                    "type": "string",
                    "description": "Optional ID of the parent image to edit if available from context."
                }
            },
            "required": ["edit_instruction"]
        }
    }
}

DEEP_RESEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "deep_research",
        "description": "Perform an in-depth multi-source research investigation on a complex topic, comparing sources, facts, and compiling structured findings.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The core topic or question for deep research."
                },
                "aspects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sub-topics or specific dimensions to investigate."
                }
            },
            "required": ["topic"]
        }
    }
}

ANALYZE_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_content",
        "description": "Perform deep technical, statistical, semantic, or structural analysis on documents, code, datasets, spreadsheets, or images.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "The content, dataset, or document snippet to analyze."
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["data_summary", "code_review", "document_audit", "sentiment", "statistical"],
                    "description": "Type of analysis to conduct."
                }
            },
            "required": ["target"]
        }
    }
}

VISUALIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "visualize_data",
        "description": "Generate charts, graphs, flowcharts, or mermaid diagrams to visualize data, processes, or relationships.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the chart or visualization."
                },
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "mermaid", "table"],
                    "description": "Type of visual representation."
                },
                "data_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "value": {"type": "number"}
                        }
                    },
                    "description": "Data points for numerical charts."
                },
                "mermaid_code": {
                    "type": "string",
                    "description": "Mermaid diagram code if chart_type is mermaid."
                }
            },
            "required": ["title", "chart_type"]
        }
    }
}

CODE_WORKSPACE_TOOL = {
    "type": "function",
    "function": {
        "name": "code_workspace",
        "description": "Write, analyze, debug, refactor, review, or execute source code in an isolated workspace. Use 'review' for structured code review (Critical/High/Medium/Low) and 'security_review' for security-focused analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "Programming language (e.g., python, javascript, typescript, rust, go, sql)."
                },
                "code": {
                    "type": "string",
                    "description": "The complete source code to test or inspect."
                },
                "action": {
                    "type": "string",
                    "enum": ["execute", "debug", "refactor", "explain", "unit_test", "review", "security_review", "test"],
                    "description": "Action to perform in the code workspace."
                }
            },
            "required": ["language", "code", "action"]
        }
    }
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search the user's uploaded documents and knowledge base using semantic + keyword retrieval (RAG). Use this when the user asks about their files, uploaded documents, or when you need to find specific information from their knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant document chunks."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search the user's long-term memory for stored preferences, facts, and context from previous conversations. Use this to recall what the user previously told you.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant memories."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_code",
            "description": "Analyze a code snippet — explain what it does, find bugs, suggest improvements, or convert between languages. Use this when the user provides code and asks for help understanding or fixing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The code snippet to analyze."
                    },
                    "task": {
                        "type": "string",
                        "description": "What to do with the code: 'explain', 'debug', 'optimize', 'review', or 'convert'.",
                        "enum": ["explain", "debug", "optimize", "review", "convert"]
                    }
                },
                "required": ["code", "task"]
            }
        }
    }
]


class Agent:
    """
    Agentic wrapper around the LLM. Runs a tool-calling loop:
    1. Send user message + tools to LLM
    2. If LLM calls a tool → execute it → feed result back
    3. Repeat until LLM produces a final text response (max iterations)
    4. Stream the final response to the user
    """

    def __init__(
        self,
        db: Session,
        user_id: Any,
        llm_router: LLMRouter,
        system_prompt: str,
        history: List[Dict[str, str]],
        conversation_id: Optional[Any] = None,
        intensity: str = "medium",
        enabled_tools: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ):
        self.db = db
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.llm_router = llm_router
        self.system_prompt = system_prompt
        self.history = history
        self.intensity = intensity.lower() if intensity else "medium"
        self.enabled_tools = enabled_tools or []
        self.attachments = attachments or []
        self.tool_results: List[Dict[str, Any]] = []
        self.pending_image_markdowns: List[str] = []

    # ─── Tool Executors ─────────────────────────────────────────────

    async def _execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Dispatches tool calls to the appropriate handler."""
        try:
            if name == "search_documents":
                return await self._tool_search_documents(arguments["query"])
            elif name == "search_memory":
                return self._tool_search_memory(arguments["query"])
            elif name == "analyze_code":
                return self._tool_analyze_code(arguments["code"], arguments.get("task", "explain"))
            elif name == "web_search":
                return await self._tool_web_search(arguments["query"])
            elif name == "create_image":
                return await self._tool_create_image(arguments.get("prompt", ""), arguments.get("aspect_ratio"))
            elif name == "edit_image":
                return await self._tool_edit_image(arguments.get("edit_instruction", ""), arguments.get("image_id"))
            elif name == "deep_research":
                return await self._tool_deep_research(arguments.get("topic", ""), arguments.get("aspects", []))
            elif name == "analyze_content":
                return self._tool_analyze_content(arguments.get("target", ""), arguments.get("analysis_type", "data_summary"))
            elif name == "visualize_data":
                return self._tool_visualize_data(arguments)
            elif name == "code_workspace":
                return await self._tool_code_workspace(arguments.get("language", "python"), arguments.get("code", ""), arguments.get("action", "execute"))
            else:
                return f"Unknown tool: {name}"
        except Exception as e:
            return f"Tool execution error: {str(e)}"

    async def _tool_web_search(self, query: str) -> str:
        """Performs live search on the web using Tavily Search API (priority) or DuckDuckGo fallback."""
        import json
        import urllib.request
        import urllib.parse
        import re

        tavily_key = os.getenv("TAVILY_API_KEY")
        if tavily_key:
            try:
                def run_tavily():
                    req_data = json.dumps({
                        "api_key": tavily_key,
                        "query": query,
                        "search_depth": "basic",
                        "max_results": 5,
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
                if data.get("answer"):
                    results.append(f"Summary: {data['answer']}\n")
                for i, r in enumerate(data.get("results", [])[:5]):
                    title = r.get("title", "Result")
                    content = r.get("content", "")
                    url = r.get("url", "")
                    results.append(f"[{i+1}] {title}\n{content}\nSource: {url}")
                if results:
                    return "\n\n".join(results)
            except Exception as e:
                print(f"Tavily search error: {e}, falling back to DuckDuckGo")

        try:
            url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            def run_request():
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.read().decode('utf-8', errors='ignore')
            
            loop = asyncio.get_event_loop()
            html = await loop.run_in_executor(None, run_request)
            
            snippets = re.findall(r'<a class="result-snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            urls = re.findall(r'<a class="result__url"[^>]*href="([^"]*)"', html, re.DOTALL)
            
            if not snippets:
                snippets = re.findall(r'<td class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)
                
            if snippets:
                results = []
                for i, snip in enumerate(snippets[:4]):
                    clean_snip = re.sub(r'<[^>]+>', '', snip).strip()
                    source_url = urls[i].strip() if i < len(urls) else "https://duckduckgo.com"
                    results.append(f"[{i+1}] {clean_snip}\nSource: {source_url}")
                return "\n\n".join(results)
            else:
                descs = re.findall(r'<div class="result__snippet"[^>]*>(.*?)</div>', html, re.DOTALL)
                if descs:
                    results = []
                    for i, snip in enumerate(descs[:4]):
                        clean_snip = re.sub(r'<[^>]+>', '', snip).strip()
                        source_url = urls[i].strip() if i < len(urls) else "https://duckduckgo.com"
                        results.append(f"[{i+1}] {clean_snip}\nSource: {source_url}")
                    return "\n\n".join(results)
                return f"Web search could not find live results for '{query}'."
        except Exception as e:
            return f"Web search error: {str(e)}"

    async def _tool_create_image(self, prompt: str, aspect_ratio: Optional[str] = None) -> str:
        """Generates an image via ImageGenerationEngine and embeds interactive metadata."""
        from media.image_engine import ImageGenerationEngine
        from database.models import GeneratedImage
        import uuid as _uuid
        engine = ImageGenerationEngine(self.db, self.user_id)

        # Check if the prompt is an edit instruction for an existing image in this conversation
        p_lower = prompt.lower()
        is_edit_intent = any(p_lower.startswith(k) or f" {k}" in p_lower for k in [
            "make the ", "make it ", "change the ", "change only ", "turn the ",
            "replace the ", "add a ", "remove the ", "keep everything else", "make this "
        ])

        if is_edit_intent:
            latest_img = None
            if self.conversation_id:
                latest_img = self.db.query(GeneratedImage).filter(
                    GeneratedImage.conversation_id == self.conversation_id,
                    GeneratedImage.user_id == self.user_id
                ).order_by(GeneratedImage.created_at.desc()).first()
            if not latest_img:
                latest_img = self.db.query(GeneratedImage).filter(
                    GeneratedImage.user_id == self.user_id
                ).order_by(GeneratedImage.created_at.desc()).first()
            
            if latest_img:
                return await self._tool_edit_image(prompt, image_id=str(latest_img.id))

        try:
            res = await engine.generate_image(
                prompt=prompt,
                conversation_id=self.conversation_id,
                aspect_ratio=aspect_ratio,
                intensity=self.intensity,
                workflow="TEXT_TO_IMAGE"
            )
            meta_json = json.dumps(res)
            img_snippet = f"![{res['filename']}]({res['url']})\n\n<!-- SAKURA_IMAGE_DATA:{meta_json} -->\n\n*Prompt:* \"{res['prompt']}\" | *Aspect Ratio:* {res['aspect_ratio']} | *Resolution:* {res['width']}×{res['height']}"
            self.pending_image_markdowns.append(img_snippet)
            return (
                f"Generated artwork successfully.\n\n"
                f"{img_snippet}\n\n"
                f"CRITICAL SYSTEM DIRECTIVE: You MUST display the generated image by including the exact markdown image tag and SAKURA_IMAGE_DATA comment block in your response to the user."
            )
        except Exception as e:
            err_json = json.dumps({
                "error": "timeout" if "timed out" in str(e).lower() or "timeout" in str(e).lower() else "transient_error",
                "message": "The generation service took too long to respond.",
                "prompt": prompt,
                "aspect_ratio": aspect_ratio or "1:1",
                "intensity": self.intensity,
                "retryable": True
            })
            return (
                f"Couldn't create the image.\n\n"
                f"The generation service took too long to respond.\n\n"
                f"<!-- SAKURA_IMAGE_ERROR:{err_json} -->\n"
                f"*CRITICAL: This is a temporary tool failure, NOT a capability failure. Do NOT recommend Midjourney, DALL-E, Stable Diffusion, SVG or Python code. Output only the concise failure notice with Retry.*"
            )

    async def _tool_edit_image(self, edit_instruction: str, image_id: Optional[str] = None) -> str:
        """Edits an existing image preserving prior context and establishing edit lineage."""
        from media.image_engine import ImageGenerationEngine
        from database.models import GeneratedImage
        import uuid as _uuid
        engine = ImageGenerationEngine(self.db, self.user_id)

        parent_uuid = None
        if image_id:
            try:
                parent_uuid = _uuid.UUID(image_id)
            except Exception:
                pass

        if not parent_uuid and self.conversation_id:
            conv_img = self.db.query(GeneratedImage).filter(
                GeneratedImage.conversation_id == self.conversation_id,
                GeneratedImage.user_id == self.user_id
            ).order_by(GeneratedImage.created_at.desc()).first()
            if conv_img:
                parent_uuid = conv_img.id

        if not parent_uuid:
            latest_img = self.db.query(GeneratedImage).filter(
                GeneratedImage.user_id == self.user_id
            ).order_by(GeneratedImage.created_at.desc()).first()
            if latest_img:
                parent_uuid = latest_img.id

        try:
            if parent_uuid:
                res = await engine.edit_image(
                    parent_image_id=parent_uuid,
                    edit_instruction=edit_instruction,
                    conversation_id=self.conversation_id,
                    intensity=self.intensity
                )
            else:
                res = await engine.generate_image(
                    prompt=edit_instruction,
                    conversation_id=self.conversation_id,
                    intensity=self.intensity,
                    workflow="EDIT_IMAGE"
                )
            meta_json = json.dumps(res)
            img_snippet = f"![{res['filename']}]({res['url']})\n\n<!-- SAKURA_IMAGE_DATA:{meta_json} -->\n\n*Instruction:* \"{edit_instruction}\" | *Lineage:* Version {res['lineage_depth'] + 1}"
            self.pending_image_markdowns.append(img_snippet)
            return (
                f"Updated image with requested changes.\n\n"
                f"{img_snippet}\n\n"
                f"CRITICAL SYSTEM DIRECTIVE: You MUST display the generated image by including the exact markdown image tag and SAKURA_IMAGE_DATA comment block in your response to the user."
            )
        except Exception as e:
            err_json = json.dumps({
                "error": "timeout" if "timed out" in str(e).lower() or "timeout" in str(e).lower() else "transient_error",
                "message": "The generation service took too long to respond.",
                "prompt": edit_instruction,
                "aspect_ratio": "1:1",
                "intensity": self.intensity,
                "retryable": True
            })
            return (
                f"Couldn't create the image.\n\n"
                f"The generation service took too long to respond.\n\n"
                f"<!-- SAKURA_IMAGE_ERROR:{err_json} -->\n"
                f"*CRITICAL: This is a temporary tool failure, NOT a capability failure. Do NOT recommend Midjourney, DALL-E, Stable Diffusion, SVG or Python code. Output only the concise failure notice with Retry.*"
            )

    async def _tool_deep_research(self, topic: str, aspects: List[str]) -> str:
        """Executes a deep research synthesis over multiple aspects."""
        aspect_text = "\n".join([f"- {a}" for a in aspects]) if aspects else "- Primary factors\n- Historical and empirical context\n- Key conclusions & trade-offs"
        web_res = await self._tool_web_search(topic)
        return (
            f"=== DEEP RESEARCH REPORT: {topic.upper()} ===\n\n"
            f"Key Dimensions Investigated:\n{aspect_text}\n\n"
            f"Primary Web Evidence:\n{web_res}\n\n"
            f"Synthesize this into a structured, authoritative report with clear sections, executive summary, and key takeaways."
        )

    def _tool_analyze_content(self, target: str, analysis_type: str) -> str:
        """Performs content, code, document, or dataset analysis."""
        lines = target.strip().split("\n")
        line_count = len(lines)
        char_count = len(target)
        return (
            f"Analysis Type: {analysis_type}\n"
            f"Metrics: {line_count} lines, {char_count} characters.\n"
            f"Target Sample:\n{target[:1500]}\n\n"
            f"Please conduct an in-depth {analysis_type} assessment with clear findings and actionable recommendations."
        )

    def _tool_visualize_data(self, args: Dict[str, Any]) -> str:
        """Produces structured visualization markdown or mermaid charts."""
        title = args.get("title", "Visualization")
        chart_type = args.get("chart_type", "table")
        points = args.get("data_points", [])
        mermaid_code = args.get("mermaid_code", "")

        if chart_type == "mermaid" and mermaid_code:
            return f"### {title}\n\n```mermaid\n{mermaid_code}\n```"

        if points:
            rows = [f"| {p.get('label', 'Item')} | {p.get('value', 0)} |" for p in points]
            table = "| Metric / Label | Value |\n| :--- | :--- |\n" + "\n".join(rows)
            return f"### {title} ({chart_type.upper()})\n\n{table}"

        return f"### {title}\nVisualization spec prepared for {chart_type} rendering."

    async def _tool_code_workspace(self, language: str, code: str, action: str) -> str:
        """Executes, reviews, or analyzes code in the isolated workspace."""
        if action == "execute":
            import tempfile
            from coding.executor import SandboxExecutor
            with tempfile.TemporaryDirectory(prefix="sakura_exec_") as temp_dir:
                ext = ".py" if language.lower() in ["python", "py"] else (".js" if language.lower() in ["javascript", "js"] else ".txt")
                script_path = os.path.join(temp_dir, f"snippet{ext}")
                with open(script_path, "w", encoding="utf-8") as sf:
                    sf.write(code)
                executor = SandboxExecutor(temp_dir)
                if ext == ".py":
                    res = await executor.run_command(f"python snippet{ext}", timeout_seconds=15)
                elif ext == ".js":
                    res = await executor.run_command(f"node snippet{ext}", timeout_seconds=15)
                else:
                    return f"Execution not supported for language '{language}'. Supported: python, javascript."
                
                output = res.get("stdout") or res.get("stderr") or "[Executed successfully with no output]"
                return f"Code Workspace ({language}) - Action: execute\n\nExit Code: {res['exit_code']}\nOutput:\n```\n{output}\n```"

        if action == "review":
            return (
                f"Code Workspace ({language}) - Structured Code Review\n"
                f"```{language}\n{code}\n```\n\n"
                f"Conduct a structured review with the following priority levels:\n"
                f"CRITICAL: Security vulnerabilities, data corruption, auth bypass, concurrency errors\n"
                f"HIGH: Logic bugs, broken edge cases, incorrect APIs, resource leaks, performance problems\n"
                f"MEDIUM: Maintainability, fragile architecture, missing validation\n"
                f"LOW: Style issues\n"
                f"Focus on substantive issues. Do not overwhelm with trivial nitpicks."
            )

        if action == "security_review":
            return (
                f"Code Workspace ({language}) - Security Review\n"
                f"```{language}\n{code}\n```\n\n"
                f"Analyze for: authentication/authorization flaws, input validation gaps, "
                f"SQL injection, XSS, CSRF, SSRF, command injection, path traversal, "
                f"secret exposure, unsafe deserialization, dependency vulnerabilities, "
                f"race conditions, and insecure error handling.\n"
                f"Classify each finding by severity (Critical/High/Medium/Low) with remediation."
            )

        if action == "test":
            return (
                f"Code Workspace ({language}) - Test Generation\n"
                f"```{language}\n{code}\n```\n\n"
                f"Generate comprehensive tests covering: happy path, boundary cases, error cases, "
                f"and edge cases. Use the project's existing test framework conventions if apparent."
            )

        return f"Code Workspace ({language}) - Action: {action}\n```\n{code}\n```\nPlease provide a full {action} evaluation with clean code and tests."

    async def _tool_search_documents(self, query: str) -> str:
        """RAG retrieval from uploaded documents."""
        from database.models import User as DBUser
        sys_user = self.db.query(DBUser).filter_by(username="operator_zero").first()
        sys_user_id = sys_user.id if sys_user else None

        has_docs = self.db.query(Document).filter(
            (Document.user_id == self.user_id) | (Document.user_id == sys_user_id)
        ).first()

        if not has_docs:
            return "No documents found in the knowledge base. The user has not uploaded any files yet."

        retriever = HybridRetriever(self.db)
        results = await retriever.retrieve(self.user_id, query, limit=5)

        if not results:
            return "No relevant content found in the uploaded documents for this query."

        formatted = []
        for r in results:
            source = r.get("source", "Unknown")
            page = r.get("page", "N/A")
            content = r.get("content", "")
            score = r.get("score", 0)
            formatted.append(f"[Source: {source}, Page: {page}, Relevance: {score}]\n{content}")

        return "\n\n---\n\n".join(formatted)

    def _tool_search_memory(self, query: str) -> str:
        """Search long-term user memories."""
        mem_mgr = MemoryManager(self.db)
        memories = mem_mgr.get_relevant_memories(self.user_id, query, limit=5)

        if not memories:
            return "No relevant memories found for this user."

        formatted = []
        for m in memories:
            formatted.append(f"[{m['memory_type']}, confidence: {m['confidence']}] {m['content']}")

        return "\n".join(formatted)

    def _tool_analyze_code(self, code: str, task: str) -> str:
        """Returns the code back with the task instruction for the LLM to process."""
        return f"Code analysis requested.\nTask: {task}\nCode:\n```\n{code}\n```\nPlease provide your {task} of the above code."

    # ─── Agentic Loop ───────────────────────────────────────────────

    async def run_stream(self, user_message: str) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main agentic loop with streaming. Runs tool calls iteratively,
        then streams the final LLM response.
        """
        from ml_pipeline import IntentClassifier
        intent = IntentClassifier().classify(user_message)
        provider_name, provider = self.llm_router.get_provider(intent)

        # Map intensity settings to internal request parameters & system instructions
        if self.intensity == "low":
            max_iterations = 1
            temperature = 0.2
            max_final_tokens = 1500
            intensity_prompt = (
                "\n\n[RESPONSE INTENSITY: LOW — Quick Mode]\n"
                "Prioritize speed and directness. Give concise answers without excessive preamble. "
                "For code: generate the solution directly. Skip exhaustive verification unless the user asks."
            )
        elif self.intensity == "high":
            max_iterations = 10
            temperature = 0.2
            max_final_tokens = 4096
            intensity_prompt = (
                "\n\n[RESPONSE INTENSITY: HIGH — Frontier Engineering Mode]\n"
                "Apply full engineering rigor. For coding tasks:\n"
                "- Explore deeper context: inspect related files, dependencies, tests\n"
                "- Plan before implementing: identify affected components and order of changes\n"
                "- Verify your work: run tests, check types, review the diff\n"
                "- Consider security, edge cases, error handling, and performance\n"
                "- Provide structured output: what was implemented, verified, and any caveats\n"
                "For non-coding tasks: deep reasoning, multi-source investigation, step-by-step verification."
            )
        else: # medium
            max_iterations = 5
            temperature = 0.2
            max_final_tokens = 2500
            intensity_prompt = (
                "\n\n[RESPONSE INTENSITY: MEDIUM — Standard Mode]\n"
                "Balanced quality and speed. Write clean, correct code with appropriate error handling. "
                "Use tools when they add value. Verify when practical."
            )

        # Process attachments if present
        attachment_context = ""
        if self.attachments:
            attachment_snippets = []
            for att in self.attachments:
                fname = att.get("filename", "file")
                ftype = att.get("mime_type", "unknown")
                fcontent = att.get("content", "")
                if fcontent:
                    attachment_snippets.append(f"=== ATTACHED FILE: {fname} ({ftype}) ===\n{fcontent[:4000]}")
                elif "id" in att:
                    # Check database for document content (strictly enforcing user ownership)
                    try:
                        att_uuid = uuid.UUID(str(att["id"]))
                    except ValueError:
                        continue
                    doc = self.db.query(Document).filter(
                        Document.id == att_uuid,
                        Document.user_id == self.user_id
                    ).first()
                    if doc and os.path.exists(doc.storage_path):
                        try:
                            with open(doc.storage_path, "r", encoding="utf-8", errors="ignore") as f:
                                preview = f.read(4000)
                                attachment_snippets.append(f"=== ATTACHED FILE: {doc.filename} ===\n{preview}")
                        except Exception:
                            attachment_snippets.append(f"=== ATTACHED FILE: {doc.filename} (Available in Knowledge Base) ===")
            if attachment_snippets:
                attachment_context = "\n\nUser Attached Documents for this query:\n" + "\n\n".join(attachment_snippets)

        # Build initial messages
        messages = []
        full_system_prompt = (self.system_prompt or "") + intensity_prompt + attachment_context
        if full_system_prompt:
            messages.append({"role": "system", "content": full_system_prompt})
        
        # Add conversation history
        for h in self.history:
            messages.append({"role": h["role"], "content": h["content"]})
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})

        # Check if user has documents
        from database.models import User as DBUser
        sys_user = self.db.query(DBUser).filter_by(username="operator_zero").first()
        sys_user_id = sys_user.id if sys_user else None
        has_docs = self.db.query(Document).filter(
            (Document.user_id == self.user_id) | (Document.user_id == sys_user_id)
        ).first()

        # Build active tools based on what's available and selected in the composer
        available_tools = []
        
        # Core default tools
        available_tools.append([t for t in TOOLS if t["type"] == "function" and t["function"]["name"] == "search_memory"][0])
        available_tools.append([t for t in TOOLS if t["type"] == "function" and t["function"]["name"] == "analyze_code"][0])
        available_tools.append(CODE_WORKSPACE_TOOL)
        available_tools.append(CREATE_IMAGE_TOOL)
        available_tools.append(EDIT_IMAGE_TOOL)
        
        if has_docs:
            available_tools.append([t for t in TOOLS if t["type"] == "function" and t["function"]["name"] == "search_documents"][0])
            
        # Optional plus menu tools
        if "web_search" in self.enabled_tools:
            available_tools.append(WEB_SEARCH_TOOL)
        if "deep_research" in self.enabled_tools:
            available_tools.append(DEEP_RESEARCH_TOOL)
        if "analyze" in self.enabled_tools:
            available_tools.append(ANALYZE_TOOL)
        if "visualize" in self.enabled_tools:
            available_tools.append(VISUALIZE_TOOL)

        # ─── Tool iteration loop ───
        if available_tools:
            for iteration in range(max_iterations):
                try:
                    # Call provider-neutral tool turn
                    turn_result = await provider.tool_turn(
                        messages=messages,
                        tools=available_tools,
                        temperature=temperature,
                        max_tokens=600,
                    )

                    tool_calls = turn_result.get("tool_calls", [])
                    content = turn_result.get("content")

                    # If the model wants to call a tool
                    if tool_calls:
                        formatted_tool_calls = []
                        for tc in tool_calls:
                            tc_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                            fn_name = tc.get("name", "")
                            fn_args = tc.get("arguments", {})
                            args_str = json.dumps(fn_args) if isinstance(fn_args, dict) else str(fn_args)
                            formatted_tool_calls.append({
                                "id": tc_id,
                                "type": "function",
                                "function": {
                                    "name": fn_name,
                                    "arguments": args_str
                                }
                            })

                        messages.append({
                            "role": "assistant",
                            "content": content or "",
                            "tool_calls": formatted_tool_calls
                        })

                        # Execute each tool call
                        for idx, tool_call in enumerate(tool_calls):
                            fn_name = tool_call.get("name")
                            fn_args = tool_call.get("arguments", {})
                            if isinstance(fn_args, str):
                                try:
                                    fn_args = json.loads(fn_args)
                                except Exception:
                                    fn_args = {}
                            
                            # Yield status update
                            yield {"token": "", "provider": provider_name, "tool_call": fn_name, "status": "executing"}

                            result = await self._execute_tool(fn_name, fn_args)
                            self.tool_results.append({
                                "tool": fn_name,
                                "args": fn_args,
                                "result": result
                            })

                            # Add tool result to messages matching tool_call_id
                            tc_id = formatted_tool_calls[idx]["id"]
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": str(result)
                            })

                        # Continue loop — LLM will process tool results
                        continue

                    # No tool calls — model wants to give a final response
                    break

                except Exception as e:
                    err_str = str(e)
                    print(f"Agent tool loop error (iteration {iteration}): {err_str}")
                    # If 413 occurs during tool loop, prune messages and break to direct stream
                    if "413" in err_str or "rate_limit_exceeded" in err_str or "Request too large" in err_str:
                        if len(messages) > 2:
                            messages = [messages[0], messages[-1]]
                    break

        # ─── Final streaming response ───
        accumulated_response = ""
        try:
            async for content in provider.stream_messages(
                messages=messages,
                temperature=temperature,
                max_tokens=max_final_tokens,
            ):
                if content:
                    accumulated_response += content
                    yield {"token": content, "provider": provider_name}

            # If any image tool was executed, ensure the image markdown is guaranteed in the output
            for img_md in self.pending_image_markdowns:
                url_match = re.search(r"\((/api/v1/library/files/[^)]+)\)", img_md)
                if not url_match or url_match.group(1) not in accumulated_response:
                    append_chunk = f"\n\n{img_md}\n\n"
                    accumulated_response += append_chunk
                    yield {"token": append_chunk, "provider": provider_name}

        except Exception as e:
            err_str = str(e)
            print(f"Agent streaming error: {err_str}")
            # Automatic self-healing for 413 token quota overflow:
            # Aggressively prune messages to system prompt + user question and retry with minimal max_tokens
            if "413" in err_str or "rate_limit_exceeded" in err_str or "Request too large" in err_str:
                try:
                    print("Agent: 413 rate limit encountered. Auto-pruning context and retrying...")
                    pruned_messages = [messages[0]]
                    if len(messages) > 1:
                        pruned_messages.append(messages[-1])
                    
                    async for content in provider.stream_messages(
                        messages=pruned_messages,
                        temperature=temperature,
                        max_tokens=1024,
                    ):
                        if content:
                            accumulated_response += content
                            yield {"token": content, "provider": provider_name}

                    for img_md in self.pending_image_markdowns:
                        url_match = re.search(r"\((/api/v1/library/files/[^)]+)\)", img_md)
                        if not url_match or url_match.group(1) not in accumulated_response:
                            append_chunk = f"\n\n{img_md}\n\n"
                            yield {"token": append_chunk, "provider": provider_name}
                    return
                except Exception as retry_err:
                    print(f"Agent retry after 413 failed: {retry_err}")

            error_msg = f"I apologize, but I encountered an error generating a response: {str(e)}"
            for word in error_msg.split(" "):
                yield {"token": word + " ", "provider": "error"}
                await asyncio.sleep(0.02)

    def get_tool_results(self) -> List[Dict[str, Any]]:
        """Returns tool execution results for metadata storage."""
        return self.tool_results
