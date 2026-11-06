# How to edit your own footage

The editing arm turns your clips and photos into a finished cut. Strategy is `owned-derivative` (your footage) or `client` (someone else's, with their license).

```bash
uv run kalainova new trip --strategy owned-derivative --identity <your-owned-label> --subject "<what it is>" --media video,audio
uv run kalainova ingest jobs/trip ~/Footage/trip/          # split into shots and score every one
uv run kalainova shots jobs/trip                           # see the scores and shot ids
uv run kalainova edit jobs/trip "30s reel, warm, cinematic, title: <title>. end card: <line>"
uv run kalainova revise jobs/trip "faster cuts, cooler, drop <shot id or file name>, open with <name>"
```

Notes accumulate in `direction.json`; later notes win. The vocabulary:

| Say | Does |
|---|---|
| `30s`, `1 min` | target length (the edit never pads with repeats; it tells you when footage runs short) |
| `reel` / `square` / `landscape` / `long form` | 9:16, 1:1, 16:9, or a long edit that keeps the speech |
| `fast` / `medium` / `cinematic` | 2, 4, or 8 music beats per shot; cinematic dissolves |
| `warm` `cool` `teal and orange` `film` `black and white` `vivid` `natural` | grade (plus automatic exposure matching per shot) |
| `chronological`, `best first` | order (default: strongest moving shot first, calm wide to close) |
| `start with X`, `end with X`, `drop X` | X is a shot id (`s003.0`) or part of a file name |
| `title: ...`, `end card: ...` | studio headlines, with a feathered scrim over footage |
| `slow motion` | 0.6x on high-motion shots |
| `keep original audio`, `no music`, `music: <mood>` | sound |
| `keep pauses` | long form: do not cut silences |

What the director does on its own: rejects shaky, soft, and badly exposed takes outright; picks the steadiest, sharpest window inside each shot; never repeats a take back to back; lands cuts on the music's beat; reframes 16:9 to 9:16 around the subject; hides long-form jump cuts with alternating punch-ins; fades out at the end.

Then the shared gate: `approve` (a human), `publish`, `measure`.

## Free stock footage instead of your own

```bash
export PEXELS_API_KEY=...    # free: https://www.pexels.com/api/
export PIXABAY_API_KEY=...   # free: https://pixabay.com/api/docs/   (either one is enough)
uv run kalainova reel <id> "<place or topic>" "20s reel, cinematic, warm, title: <title>"
```

`reel` opens a job (`owned-derivative`, rights `licensed`) and builds a shot list from the subject (wide, aerial, skyline, sunset, coast, street…). It takes the best free-license clips, at least 720p and 4–40 s long, picking for coverage across the shot list, then downloads them and records author, page, and license in `stock.json`. After that it ingests and edits. Credits go into the publish description. Paid libraries are never touched.
