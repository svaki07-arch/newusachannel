# FrameScout

A locally hosted image research tool for video production. FastAPI serves a dark, responsive HTML/CSS/JavaScript UI styled with Tailwind (CDN, with local CSS fallback). Search with SerpApi, Google Custom Search, or DuckDuckGo; evaluate images with OpenAI vision; download a curated ZIP.

## Folder structure

```text
newusachannel/
├── app/
│   ├── __init__.py
│   ├── main.py             # API, settings, search, vision and archive pipeline
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
├── tests/test_app.py
├── requirements.txt
├── .gitignore
└── README.md
```

Runtime files are created in ignored `.local/`: `settings.json` and one directory per workflow containing approved JPEGs and `curated.zip`. Images are normalized to JPEG at up to 2048 pixels on the longest edge; these are research/production reference assets rather than original-resolution downloads. Each ZIP includes a source/score/reason manifest.

## Run locally

1. Install Python 3.11 or newer and clone this repository.
2. From the repository directory, create a virtual environment:
   ```sh
   python -m venv .venv
   ```
3. Activate it:
   - macOS/Linux: `source .venv/bin/activate`
   - Windows PowerShell: `.venv\Scripts\Activate.ps1`
4. Install dependencies:
   ```sh
   python -m pip install -r requirements.txt
   ```
5. Start the server:
   ```sh
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
6. Open `http://127.0.0.1:8000` on your local machine.
7. Save your OpenAI API key and select a search provider. Enter its key for SerpApi or Google. Google also requires a Programmable Search engine ID (`cx`) with image search enabled. DuckDuckGo needs no search key but can be throttled or return fewer results.
8. Enter a query, image count, and score threshold, then select **Start Workflow**. Approved frames appear during processing; download the ZIP once processing finishes.

Keys are stored as plaintext on your local disk with restrictive permissions on Unix, never returned through the API, and excluded from Git. Use **Delete saved keys** to remove settings. Restrict access to your OS account and disk; Windows users should check their directory ACLs. Do not expose this app publicly or bind it to a public interface: it has no multiuser authentication. It accepts localhost hostnames and rejects cross-origin state changes.

## Pipeline and errors

- Search yields deduplicated direct URLs. Google permits only the first 100 results per query; SerpApi pages results, and all providers may return fewer than requested.
- Images are downloaded into bounded memory, decoded, and re-encoded to reject invalid formats and strip metadata. Private-network URLs and redirects are rejected. DNS prechecks are a local-tool safeguard, not a hardened DNS-rebinding defense; use an egress firewall if you need that protection.
- `gpt-4o-mini` receives the requested documentary-editor system prompt, the query, and the exact fetched pixels as a base64 image. Sending pixels avoids scoring a remote asset different from the one saved. JSON scores must be integers from 0 to 10.
- Requests are sequential with a 0.6-second delay; OpenAI SDK retries transient/rate-limit failures up to three times. Search HTTP 429 responses use exponential backoff. Failed image requests/evaluations are logged and skipped without aborting the remaining images.
- Downloads time out after 25 seconds of network inactivity and have a 15 MB limit. Decode size is capped. Zero approved images produces no ZIP. Logs include safe error categories instead of request URLs or secret-bearing SDK errors.
- Only one job runs at a time. Progress is polled every 1.2 seconds and reconnects on page refresh while the job remains active. In-memory job records reset on server restart; archives remain on disk. Stop the server before manually deleting old job directories to reclaim disk. No database or other service is required.

AI judgment is subjective. Review the gallery before production use, and verify licenses/permissions separately. Evaluation incurs OpenAI charges, including for rejected images. This tool does not claim image usage rights.

## Validation

```sh
python -m pytest -q
```

Tests cover settings/key redaction, cross-origin protection, private destination rejection, image decoding, pagination, and a mocked complete pipeline with approval, rejection, failed download, and ZIP contents. Live provider calls require your keys and quota; these tests do not validate live API credentials.

## Image count and duplicate removal

The default search limit is 100 candidate links (adjustable from 10 to 200). Search providers may return fewer results. Before each OpenAI call, the application checks the decoded image content against earlier images in the current workflow: SHA-256 for exact copies and a conservative visual fingerprint for resized/recompressed copies. Aspect ratio and small RGB comparisons reduce false matches. Duplicate skips appear in the log and do not consume OpenAI evaluation requests. Different crops, large overlays, and other heavy edits can evade detection; visually similar images may occasionally be grouped. The approved ZIP can contain fewer than 100 images because of duplicates, failed downloads, or the AI score threshold. This is not a target of 100 approved images and does not automatically refill rejected candidates. No deduplication state is shared across workflows.

## Storyboard sections

Enter the overall topic, optional place and date/period, then one requested scene per line. For example: storm onset, meteorological forecasts/maps, flooding, destruction, rescue work. The example button fills the scene list without starting or charging a workflow. The candidate slider applies **per section** (100 by default). The form displays the total potential evaluation budget; at most 20 sections and 1000 candidates are permitted. An empty list preserves single-query behavior.

Each section gets its own search combining topic, place, date, and scene. Searches that fail are logged without stopping other sections. URL and visual duplicates are removed across the entire workflow; the first occurrence owns a repeated frame. Vision must return both a passing score and a positive scene-match judgment. Forecast charts and document scans can match a requested section, but neither place/date nor document authenticity is verified from pixels. The current low-detail vision mode is for scene selection, not reliable OCR of forecasts. Source URLs remain in the manifest for manual checks.

The gallery groups approved frames by section. ZIPs use numbered section folders, plus `manifest.json` and `sections.json` describing queries, counts, and search failures. Individual jobs still store image files flat on disk. Limits describe searched candidates, not guaranteed approved frames; empty sections are visible in the gallery/section manifest.
