import re
from collections import defaultdict

class SentimentAnalyzer:
    """Lexicon-based sentiment analyzer tuned for customer support/general chat."""

    POSITIVE_LEXICON = {
        "thank", "thanks", "great", "awesome", "excellent", "perfect", "love",
        "good", "nice", "helpful", "resolved", "fixed", "solved", "happy", "appreciate"
    }
    NEGATIVE_LEXICON = {
        "broken", "crash", "error", "fail", "failed", "issue", "problem",
        "wrong", "bad", "terrible", "awful", "horrible", "useless", "frustrated", "angry"
    }

    def analyze(self, text: str) -> dict:
        tokens = re.findall(r"\b\w+\b", text.lower())
        pos_score = sum(1 for t in tokens if t in self.POSITIVE_LEXICON)
        neg_score = sum(1 for t in tokens if t in self.NEGATIVE_LEXICON)

        total = pos_score + neg_score + 0.001
        if pos_score > neg_score:
            label = "positive"
            score = pos_score / total
        elif neg_score > pos_score:
            label = "negative"
            score = neg_score / total
        else:
            label = "neutral"
            score = 0.5

        return {"label": label, "score": round(score, 2)}


class IntentClassifier:
    """Keyword and pattern intent classifier mapping user statements to functional domains."""

    INTENT_PATTERNS = {
        "repository_coding": [
            "repository", "repo", "codebase", "workspace", "multi-file", "refactor repository",
            "git status", "git diff", "checkout branch", "pull request", "build project"
        ],
        "debugging": [
            "debug", "bug", "crash", "error", "stack trace", "traceback", "exception",
            "fix error", "failing test", "assertionerror", "typeerror", "referenceerror", "syntaxerror"
        ],
        "architecture": [
            "architecture", "system design", "microservice", "database schema", "scalability",
            "domain model", "event-driven", "distributed system", "api contract"
        ],
        "code_generation": [
            "code", "program", "function", "script", "algorithm", "python", "javascript",
            "typescript", "react", "html", "css", "sql", "compile", "refactor", "api",
            "endpoint", "class", "method", "loop", "array", "database", "backend", "frontend",
            "test", "unit test", "write", "develop", "implement", "component", "library"
        ],
        "image_generation": [
            "draw", "paint", "generate image", "create image", "render", "illustration",
            "wallpaper", "artwork", "portrait", "anime art", "sketch", "visualize picture"
        ],
        "image_editing": [
            "change the image", "edit image", "make the background", "change color",
            "make it darker", "add to image", "remove from image"
        ],
        "research": [
            "research", "investigate", "market study", "comparative analysis", "deep dive",
            "literature review", "whitepaper", "state of the art"
        ],
        "document_analysis": [
            "pdf", "document", "spreadsheet", "csv", "audit document", "analyze file",
            "extract data", "summarize report"
        ],
        "reasoning": [
            "why", "how does", "compare and contrast", "trade-off", "tradeoff", "evaluate",
            "mathematical proof", "logic puzzle", "step-by-step explanation"
        ],
        "local_private": [
            "local", "offline", "private", "on-prem", "ollama", "no cloud", "confidential"
        ]
    }

    def classify(self, text: str) -> str:
        text_lower = text.lower()
        scores = defaultdict(int)

        for intent, keywords in self.INTENT_PATTERNS.items():
            for kw in keywords:
                if kw in text_lower:
                    scores[intent] += 1

        if not scores:
            return "general_chat"

        return max(scores, key=scores.__getitem__)

