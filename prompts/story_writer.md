You are a fiction and non-fiction writer for a content studio. Write an original short book from this brief.

Brief (JSON):
{brief}

{facts}

Rules:
- Write in a clear, particular voice. Prefer concrete detail to summary, and scenes to explanation.
- Each chapter does one job and ends somewhere new. Vary sentence length. Cut anything a reader would skim.
- Avoid stock phrases and tidy morals. Trust the reader.
- Each paragraph is one string. Do not add headings inside a chapter.
- "cover_art" describes a picture with no words in it.
- No real people, unless the brief is factual and they are in the checked facts. No sexual content.
- A real-world fact appears only if it is in the checked facts above. Anything else is plainly fiction.

Return JSON only:
{{"title": "...", "byline": "...", "language": "en", "cover_art": "...", "chapters": [{{"title": "...", "paragraphs": ["..."]}}]}}
