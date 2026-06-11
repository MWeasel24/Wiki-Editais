import re
import unicodedata


def clean_text(text: str) -> str:
    """Basic cleaning without destroying legal/editorial information."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n", text)
    text = re.sub(r"(?m)^\s*Página\s+\d+\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()
