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
    """Keyword intent classifier mapping statements to functional categories."""

    INTENT_PATTERNS = {
        "code_generation": [
            "code", "program", "function", "script", "algorithm", "python", "javascript",
            "typescript", "react", "html", "css", "sql", "bug", "debug", "compile",
            "refactor", "api", "endpoint", "class", "method", "loop", "array", "database",
            "backend", "frontend", "git", "docker", "test", "unit test", "write", "develop",
            "implement", "component", "library", "syntax", "error", "stack trace", "codex", "claude"
        ],
        "billing_issue": ["charge", "payment", "invoice", "refund", "bill", "price", "cost"],
        "login_issue": ["login", "sign in", "password", "forgot", "reset", "access", "account"],
        "app_crash": ["crash", "crashes", "crashing", "frozen", "freeze", "stops"],
        "performance_issue": ["slow", "lag", "lagging", "loading", "takes forever", "timeout"],
        "connectivity": ["connect", "connection", "offline", "internet", "network", "wifi"],
        "installation": ["install", "setup", "download", "update", "upgrade"],
        "documents_issue": ["pdf", "document", "file", "read", "context", "search document", "uploaded"],
        "local_workload": ["local", "offline", "private", "on-prem", "ollama"],
    }

    def classify(self, text: str) -> str:
        text_lower = text.lower()
        scores = defaultdict(int)

        for intent, keywords in self.INTENT_PATTERNS.items():
            for kw in keywords:
                if kw in text_lower:
                    scores[intent] += 1

        if not scores:
            return "general_inquiry"

        return max(scores, key=scores.__getitem__)
