You write the sound of a song whose words are already written: the brief a song model reads with them. The words, the tempo, the key and the sections stay exactly as they are. Write only what the rules below ask for. The sound it had is shown with it ("sound it had", and each section's "style"): keep what serves the song, and write the rest again to the rules.

The song (JSON):
{song}

{genre}

Rules:
{sound}
- Never name a real artist, song, or band.

Return JSON only. "sections" holds one section style per section, in the song's order: {count} of them.
{{"style": "...", "avoid": "sounds to keep out", "pronounce": {{}}, "sections": ["a few words: what changes in the first section", "..."]}}
