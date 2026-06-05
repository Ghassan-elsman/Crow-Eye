# Eye-Describe Anatomy Pages — Master Index

> **For the EYE Agent**: When a user asks how a Windows forensic artifact is structured at the **byte / binary level** — offsets, field widths, signature bytes, on-disk layout, header format, attribute streams — the authoritative reference is the **interactive anatomy pages on https://crow-eye.com/eye-describe**.
>
> The other `*_knowledge.md` files in this directory explain the **semantic / forensic** side of each artifact (what it proves, what fields mean, how Crow-Eye parses it). The anatomy pages explain the **physical** side (what the bytes are, in order). Use both: knowledge files for "what does this mean?", anatomy pages for "what does this look like on disk?".
>
> **When in doubt, send the user to the anatomy page** — it is the most accessible, accurate, and analyst-friendly explanation of the binary structure, with byte-cell rendering and step-by-step walkthroughs.

---

## Landing Page

- **https://crow-eye.com/eye-describe/** — Eye-Describe overview. Lists every anatomy module + the binary primer modules (boot process, disk layout). Start here when the user wants a tour.

## Anatomy Pages — by Artifact

| Artifact | Anatomy URL | What it explains at the byte level |
|---|---|---|
| **Prefetch (.pf)** | https://crow-eye.com/eye-describe/prefetch_anatomy.html | SCCA header, file version (Win 8/10/11 differences), executable name UTF-16 block, file metrics array, trace chains, volume info block with `run_times` array, directory strings |
| **MFT record** | https://crow-eye.com/eye-describe/mft_anatomy.html | `FILE0`/`FILE*` signature, fixup array, sequence number, hard-link count, attribute list (`$STANDARD_INFORMATION`, `$FILE_NAME`, `$DATA`), MACB timestamps in `$SIA` vs `$FNA` streams, resident vs non-resident attributes, data runs |
| **USN journal record** | https://crow-eye.com/eye-describe/usn_anatomy.html | Record length, major/minor version, file reference number, parent reference number, USN sequence, timestamp, reason flags (`FILE_CREATE` / `FILE_DELETE` / `RENAME` bitmask), source info, security ID, file attributes, file-name length + UTF-16 name |
| **LNK shortcut** | https://crow-eye.com/eye-describe/lnk_anatomy.html | `ShellLinkHeader`, `LinkTargetIDList`, `LinkInfo`, `StringData` (Name / RelativePath / WorkingDir / Arguments / IconLocation), extra data blocks (Tracker, Console, EnvironmentVariableDataBlock, KnownFolderDataBlock, …) |
| **Automatic Jump List** (`*.automaticDestinations-ms`) | https://crow-eye.com/eye-describe/automatic_jumplist.html | OLE compound document (MS-CFB) container: `DestList` stream + per-entry numbered LNK substreams. Each LNK substream is itself a full LNK shortcut (see LNK Anatomy). |
| **Custom Jump List** (`*.customDestinations-ms`) | https://crow-eye.com/eye-describe/custom_jumplist.html | Custom header + sequence of entry blocks, each containing a full LNK shortcut. No OLE container; simpler than automatic jumplists. |

## Binary Primer Modules — Foundational

When the user needs the platform context to make sense of an artifact (e.g., "where does the MFT live on disk?"):

- **https://crow-eye.com/eye-describe/windows_boot_disk_explorer.html** — Windows boot process + disk layout. Explains MBR / GPT, boot manager, BCD store, where NTFS metadata lives, $MFT entry zero, $LogFile, $UsnJrnl.

## When to use anatomy pages vs knowledge files

| User question | Resource |
|---|---|
| "What is a prefetch file? What does it prove?" | `prefetch_knowledge.md` (semantic / forensic) |
| "How does Crow-Eye parse prefetch?" | `prefetch_knowledge.md` + `parser_mappings.json` |
| "What are the bytes of a .pf file?" | `prefetch_anatomy.html` |
| "Where is `executable_name` stored in the .pf binary?" | `prefetch_anatomy.html` |
| "Why are there 8 timestamps in a prefetch file?" | `prefetch_anatomy.html` (run_times array) + `prefetch_knowledge.md` |
| "What's the difference between $SIA and $FNA timestamps?" | `mft_anatomy.html` (visual) + `mft_knowledge.md` (forensic significance) |
| "How does the USN journal flag a delete?" | `usn_anatomy.html` (reason-flags bitmask) |
| "How is an automatic jumplist stored on disk?" | `automatic_jumplist.html` |

## Citing the anatomy pages

When the agent surfaces an anatomy page to a user, cite the full URL and indicate it's an interactive byte-by-byte walkthrough:

> For the binary layout, see the interactive anatomy page: https://crow-eye.com/eye-describe/prefetch_anatomy.html — it walks every byte of a real prefetch file with annotations.

## Pages not yet published

These artifacts have `*_knowledge.md` files but no published anatomy page yet. When the user asks for byte-level detail on these, the agent should say so explicitly and offer the semantic explanation from the knowledge file instead:

- AmCache (`amcache_knowledge.md`)
- ShimCache (`shimcache_knowledge.md`)
- Registry (`registry_knowledge.md`) — though `windows_boot_disk_explorer.html` covers some hive context
- Recycle Bin (`recyclebin_knowledge.md`)
- SRUM (`srum_knowledge.md`)
- Event Log / EVTX (`eventlog_knowledge.md`)

The Eye-Describe site is actively growing — re-check the landing page (https://crow-eye.com/eye-describe/) for new modules.
