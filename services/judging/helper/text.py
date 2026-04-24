
def chunk_lines(lines: list[str], limit: int = 900) -> str:
    if not lines:
        return "(なし)"

    text = "\n".join(lines)
    if len(text) <= limit:
        return text

    return text[:limit] + "\n...(省略)"