---
name: measure-a-page-the-way-it-will-print
description: A book's layout measured words with ligatures while its PDF set them without, closing word gaps; every test passed and only looking at a page found it
metadata:
  type: feedback
---
Pillow with text shaping joins "Th" and "fi". A PDF drawn by reportlab sets separate letters. In the book face at 11 pt, "The" measured 80.4 px joined and 87.6 px apart, and a word space is 9.2 px. So a justified line laid out with one measure and printed with the other closed up its gaps. Text extraction, embedded fonts, page count, and byte stability all passed. A rendered crop of one page showed it at once.

**Why:** a test can only check what someone thought to check. Two drawing paths that share a layout still need one measure, or they drift apart in the one thing a reader sees.

**How to apply:** Give layout, page images, and print one width function (`bookpdf.width`). When a new output format appears, render a crop and look at it before trusting its tests. No poppler here? `sips -s format png` renders a PDF's first page on a Mac. See [[a-zero-exit-is-not-a-picture]].
