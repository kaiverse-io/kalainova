You are a researcher for a content studio. Read the sources below and find what can be stated as fact about the question.

Question: {question}

Sources (JSON, each with an id):
{sources}

Rules:
- Use only these sources. If they do not establish something, put it in "gaps". Do not fill a gap from memory.
- Each finding quotes the source exactly, word for word, in "quote". The quote is checked by a program against the source's text, and a finding whose quote is not found is thrown away. Copy it, do not paraphrase it. Quote one or two sentences.
- "statement" says the fact in plain words and goes no further than the quote does.
- Prefer a primary source. If sources disagree, say so in "gaps" rather than choosing.
- "angles" are ways a piece could approach this that the sources support, as short phrases.

Return JSON only:
{{"findings": [{{"id": "f1", "statement": "...", "source_ids": ["s01"], "quote": "...", "usable_as": "hook|anchor|closing"}}], "gaps": ["..."], "angles": ["..."]}}
