import os
import re
from typing import List, Dict, Any
import pdfplumber

class DocumentParser:
    """
    Parses PDF, Markdown, and TXT files, performs cleanup,
    and chunks text with an overlapping window.
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 150):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse_file(self, filepath: str, mime_type: str) -> str:
        """Extracts plain text content from target file based on mime type."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        text = ""
        if "pdf" in mime_type.lower() or filepath.endswith(".pdf"):
            with pdfplumber.open(filepath) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"\n--- Page {i+1} ---\n{page_text}"
        else:
            # Fallback to UTF-8 text parsing (Markdown/TXT/HTML)
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        return self.normalize_text(text)

    def normalize_text(self, text: str) -> str:
        """Cleans whitespaces and normalizes formatting."""
        # Replace multiple spaces/tabs with single space
        text = re.sub(r"[ \t]+", " ", text)
        # Normalize newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def get_chunks(self, text: str) -> List[Dict[str, Any]]:
        """Splits normalized text into chunks using character-level sliding window."""
        chunks = []
        text_len = len(text)
        start = 0
        chunk_index = 0

        import re

        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            
            # Adjust end to avoid splitting a word in half if possible
            if end < text_len:
                # Find last whitespace in the last 50 chars of the chunk
                sub = text[end-50:end]
                space_match = list(re.finditer(r"\s", sub))
                if space_match:
                    end = (end - 50) + space_match[-1].end()

            chunk_text = text[start:end].strip()
            if len(chunk_text) > 50:  # Skip trivial chunks
                # Extract page metadata if present
                page_match = re.search(r"--- Page (\d+) ---", chunk_text)
                page_num = int(page_match.group(1)) if page_match else None
                
                chunks.append({
                    "chunk_index": chunk_index,
                    "content": chunk_text,
                    "metadata": {
                        "page_number": page_num,
                        "char_count": len(chunk_text)
                    }
                })
                chunk_index += 1

            start += self.chunk_size - self.chunk_overlap
            
            # Avoid infinite loop on edge cases
            if self.chunk_size - self.chunk_overlap <= 0:
                start += 100

        return chunks
