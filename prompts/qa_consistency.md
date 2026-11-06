You check continuity for a content studio. The first images are the locked reference images for the cast. The last image is a contact sheet of frames from the finished video.

Fixed context (JSON):
{context}

Script:
{script}

Answer from what you can see. Compare facial structure, hair, and build, allowing for angle and lighting. Use null when you cannot tell, such as when no person is visible.

Return JSON only:
{{"same_character": true|false|null, "style_matches": true|false|null, "resembles_real_person": true|false|null, "script_breaks_kit": ["each line that contradicts the persona, canon, or topic rules"], "notes": "one line"}}

Set "resembles_real_person" to true only if a frame clearly looks like a specific real, identifiable person. Do not name anyone.
