# Browser Forensics (Browser_Claw)

## What this artifact is

`Browser_Claw` parses web-browser and Electron-app artifacts into a single case
database, **browser_analysis.db**. It covers three families:

- **Chromium** — Chrome, Edge, Brave, Chromium, Opera, Vivaldi, Yandex, and any
  other Chromium build (the parser also finds unlisted vendors such as CEF,
  Copilot and EdgeWebView by looking for a `User Data\<profile>\History` layout).
- **Gecko** — Mozilla Firefox (`places.sqlite`, `cookies.sqlite`,
  `formhistory.sqlite`, `logins.json` + `key4.db`, `sessionstore.jsonlz4`).
- **Electron** — desktop apps that embed Chromium storage (Slack, Discord, Teams,
  Signal): their Local Storage and IndexedDB.

Discovery is adaptive: it enumerates **every user profile** on the machine and
**every browser profile** (`Default`, `Profile 1`, `System Profile`, Guest), so
a multi-user or multi-profile box is fully covered.

## Provenance — how to tell rows apart

Every table begins with the same provenance columns:
`browser, vendor, user_name, sid, profile, source_path, parsed_at`.
Two users' `Default\History` do not collide because each row records which
browser, user and profile it came from. `parsed_at` is when the parser ran — it
is **never** an event time.

### Offline folders and forensic images

The same 37 tables are produced from a collected folder (Offline Importer) or a
forensic image as from the live machine. The collectors keep each profile's
folder tree intact, at
`live_acquisition/Browser/<source>/Users/<name>/AppData/...`, where `<source>`
is `vol_<N>_<id>` for partition N of an image, `src_<folder>_<id>` for each
imported source (the folder that held its `Users` folder) and `live` for a
Crow-Claw collection. The `<id>` is a short hash of the image or folder path,
so two images, two drive roots or two hosts in one export never merge. On
these cases:

- `user_name` is the `Users\<name>` folder the profile sits in — nothing else.
- `sid` comes from the **evidence's own** SOFTWARE hive (ProfileList), matched on
  that folder name (`<SID>.bak` counts as `<SID>`). It is empty when no SOFTWARE
  hive was collected, when two hives name the folder with different SIDs, or when
  the case holds browser trees from **more than one source** - hives are stored
  flat and cannot be tied to the source they came from, so a SID is withheld
  rather than guessed (the parse records a warning). It is never looked up on
  the analyst's machine.
- A tree with no user folder at all is filed under a pseudo-user
  `_unattributed_<folder>_<id>`, one per folder it was found in.
- `source_path` is the **copied** file under `live_acquisition/Browser/...`; the
  part after `Users\` is the original location on the evidence drive.
- A Firefox `profiles.ini` path that points outside the collected `Users` tree
  is ignored rather than read from the analyst's disk.
- "Include browser cache" (on by default) controls whether the HTTP cache,
  Service Worker CacheStorage and Firefox `cache2` are collected. When it is off,
  `browser_cache` and `browser_service_worker` (which reads CacheStorage) are
  empty **by choice**, not because the evidence lacks them.
- Older Chrome (roughly 2016-2019 images) used other names — `secure` /
  `httponly` cookie columns, a `thumbnails` table for top sites, and
  `Current Session` / `Last Session` files in the profile folder. All are read.
  A file that is present but unreadable (for example damaged clusters in an
  image) is reported as a warning for that profile, not silently skipped.

## Timestamps

- Chromium times are **WebKit** microseconds since 1601-01-01. Firefox times are
  **PRTime** microseconds since 1970-01-01. Both are normalised to UTC
  `YYYY-MM-DD HH:MM:SS` strings by the parser via `utils/time_utils`.
- History has two: `visit_time` (a single visit) and `last_visit_time` (the
  URL's most recent visit). The timeline plots `visit_time`.

## Secrets are preserved, never decrypted

Cookie values and saved passwords are stored as **base64 of the raw encrypted
blob** with an `encryption_version`:

- `v10` / `v11` — AES-GCM, key wrapped with DPAPI (older Chromium).
- `v20` — **App-Bound Encryption**; cannot be decrypted without SYSTEM and the
  browser's elevation service. Modern Chrome/Edge/Brave use this.
- `dpapi` — a bare DPAPI blob. `plaintext` — no encryption prefix.

The browser's DPAPI-wrapped master key from `Local State` is kept in
**`browser_metadata.os_crypt_key_b64`** (with `key_scheme`), so a later, audited
step can decrypt the blobs. The parser itself puts **no plaintext credential**
into the case database. Firefox usernames/passwords are stored as their
`logins.json` base64 (NSS/`key4.db` encrypted).

## Full extraction

HTTP cache bodies (external `f_*` files) and IndexedDB blobs are copied into
`browser_extracted/<browser>/<user>/<profile>/…`, each with a **`browser_files`**
inventory row (path, size, sha1, mtime). Cache URLs are read from the Simple
Cache entry headers, or scavenged from the Blockfile `data_#` block files when
that older format is in use (`browser_cache.cache_format` says which).

## Forensic value (what questions each table answers)

- **browser_history / browser_gecko_history** — what sites were visited, when,
  how often, via typed vs. clicked (`transition`), and the referrer chain
  (`from_visit_url`). Typed navigation is intent.
- **browser_shortcuts / browser_network_predictor** — text typed into the
  address bar, including omnibox entries the user *never pressed Enter* on
  (the predictor speculatively pre-renders). Strong "state of mind" evidence.
- **browser_downloads** — source URL, referrer, local target path, bytes, and
  start/finish times.
- **browser_cookies / browser_credentials** — session and login artifacts
  (metadata + encrypted blob; see above).
- **browser_local_storage / browser_indexeddb** — web-app state (WhatsApp Web,
  Slack, crypto wallets). Deleted LevelDB log records are recovered too.
- **browser_sessions** — open tabs, tab order, and per-tab navigation, from the
  SNSS session files. `window_index` and `tab_index` come from the
  `SetTabWindow` and `SetTabIndexInWindow` commands, NOT from the navigation
  record — whose own index counts page loads within a tab. Streams with no
  placement command (often `Tabs_*` and `Apps_*`) leave both NULL.
- **browser_service_worker** — CacheStorage entries. `http_status`,
  `content_type`, `content_encoding`, `request_method` and `server_headers` are
  decoded from a protobuf stored AFTER the body stream in each Simple Cache
  entry file; there is no `HTTP/` literal to search for the way there is in the
  blockfile cache.
- **browser_cache** — `cache_format` says what a row is. `blockfile` and
  `firefox_cache2` rows are real entries walked from the index and carry a
  status; `blockfile_scan` rows are URL strings recovered from block data the
  index did not account for, so they have none. Fetch times differ by engine:
  Chromium fills BOTH `request_time` and `response_time` from the entry's
  HttpResponseInfo; Firefox cache2 fills only `response_time` (its `lastFetched`),
  because cache2 records no request time.
- **browser_favicons** — retains visited-domain traces even after History rows
  are deleted.
- **browser_preferences** — settings, extension permissions, last file-picker
  directory, and anti-forensics tells (clear-browsing-data history, last exit
  type).
- **browser_extensions** — installed extensions and permissions (crypto wallets,
  proxies, password managers).
- **browser_metadata** — one row per browser/profile: the DPAPI-wrapped master
  key and its scheme, for later decryption. `version` is the build that last
  wrote the profile, from `User Data\Last Version` (Chromium) or
  `compatibility.ini` (Gecko) — not the build that created it. Firefox rows point at the extracted
  `key4.db` (NSS) for decrypting `browser_gecko_credentials`.
- **browser_addresses / browser_payments** — saved autofill addresses (field
  values from Web Data's `address_type_tokens`) and payment methods (card / bank
  / IBAN metadata + the encrypted PAN blob; the plaintext number is never stored).
- **browser_search_engines** — configured search providers (`keywords`), with the
  default flagged from Preferences. `date_created` is when the profile added the
  engine (UTC); it is empty for the browser's built-in engines, which store no
  creation time - an empty date is not a parse failure.
- **browser_extension_storage** — the LevelDB stores behind extensions
  (`Local/Sync Extension Settings`, `Extension State`): where crypto-wallet vaults,
  password-manager blobs and extension OAuth tokens live. Values are preserved
  verbatim.
- **browser_network_state** — alternative-service / QUIC servers, HSTS
  (`TransportSecurity`) hosts and expiries, and Reporting/NEL endpoints.
- **browser_dips** — bounce-tracking (DIPS): per-site first/last user-interaction
  and storage times — useful for tracker-contact chronology.
- **browser_media_history / browser_top_sites** — media playback / watch time, and
  the most-visited tiles.
- **browser_reading_list** — Chromium reading-list entries.
- **browser_gecko_localstorage** — Firefox HTML5 storage (`webappsstore.sqlite` +
  modern `storage/default/<origin>/ls`).

`Visited Links` is intentionally skipped: it is a one-way hashed salt file with no
recoverable URLs.

## Related

Parser mapping and database name are in `parser_mappings.json` (key `browser`).
Column-level schema is in `Global_schema_database_Reference.md`.
