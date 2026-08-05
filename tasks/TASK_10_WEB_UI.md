# Task 10: Web UI for Multi-Device Access

Create a React web UI for searching from phone, tablet, and browser.

Files to create:
- `public/index.html`: React SPA
- `src/api.js`: Client-side API wrapper

## Requirements for public/index.html (React SPA)

1. **Setup Page**
   - Master passphrase input field
   - TOTP code input field (6 digits)
   - "Setup Device" button
   - Once verified, unlock encryption key locally

2. **Search Interface**
   - Search box (semantic search)
   - Filters: source, device, date range, tags
   - Real-time results as you type
   - Results displayed as cards

3. **Result Cards**
   - Title
   - TLDR (summary)
   - Source + Device
   - Created date
   - Top pattern/learning
   - "View Details" button
   - Relevance score

4. **Session Detail View**
   - Full summary
   - All learnings (bullet list)
   - All patterns (bullet list)
   - Tags
   - Link to raw chat file (if available)

5. **Device Sync Status**
   - Last sync time
   - Device name
   - Manual sync button

6. **Responsive Design**
   - Works on desktop, tablet, phone (iOS Safari)
   - Mobile-first CSS
   - Touch-friendly buttons
   - Vertical layout on mobile

## Requirements for src/api.js (API Client)

1. **Function: `async setup(passphrase, totpCode)`**
   - Send setup request to `/setup` endpoint
   - Return: `{encryption_key, success}`

2. **Function: `async search(query, filters = {})`**
   - Call `/search?q=QUERY&top_k=10`
   - Parse results
   - Return: `[{session_id, title, tldr, ...}]`

3. **Function: `async getSession(sessionId)`**
   - Call `/session/<id>`
   - Return full session details

4. **Function: `async getStats()`**
   - Call `/stats`
   - Return system statistics

5. **Function: `async getDevices()`**
   - Call `/devices`
   - Return list of connected devices

## Tech Stack

- **React** (functional components + hooks)
- **Tailwind CSS** (styling)
- **React Query** (optional, for better caching)
- **Local encryption** (TweetNaCl.js or libsodium.js for client-side)

## Setup Flow (Mobile)

```
1. Browser: https://<host-device-ip>:7654

2. Setup Page
   Input: Master passphrase
   Input: TOTP code (from Google Authenticator)
   Click: "Setup Device"

3. Verification
   ✓ Encryption key unlocked locally
   ✓ No keys sent to server
   ✓ Redirect to search page

4. Search Page
   Search box ready
   Start typing to search
```

## HTML Structure (Key Components)

```html
<div id="root"></div>

<!-- Components to build in React: -->
- SetupPage (auth)
- SearchPage (main interface)
  - SearchBox
  - FilterPanel
  - ResultsList
  - ResultCard
- SessionDetail (modal or page)
- DeviceSync (status bar)
- Header (nav)
```

## CSS Classes (Tailwind)

```
.search-container
.result-card
.result-card:hover
.filter-panel
.search-box
.device-status
.modal
.modal-overlay
```

## API Endpoints Used

```
GET  /search?q=QUERY&top_k=10
GET  /session/<session_id>
GET  /stats
GET  /devices
POST /setup                    # New endpoint (add to server.py)
```

## Mobile Optimization

- Vertical stack layout
- Touch-friendly button sizes (44px+)
- Fast load time (<2s)
- Local caching of results
- Offline-ready (cache results)

## Security Notes

- **Encryption key derivation**: Happens locally in JavaScript
  - Master passphrase + TOTP code → derive key in browser
  - Key never sent to server
- **HTTPS only**: Enforce on production
- **CORS**: Allow only trusted origins

## Testing

- Test on Safari (iOS)
- Test on Chrome (desktop)
- Test on Firefox
- Test responsive design (mobile device or DevTools)
- Test search functionality
- Test detail view

## Output Files

Create:
- `public/index.html`
- `src/api.js`

Also add to `server.py`:
```python
@app.route('/setup', methods=['POST'])
def setup():
    data = request.json
    passphrase = data.get('passphrase')
    totp_code = data.get('totp_code')
    # Verify credentials and return success
```

---

**Final task!** Paste into Claude Code!
