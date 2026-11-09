# AI Agent Records (AI_Agent_Claw)

## What this artifact is

AI coding and computer-use agents keep their own record of their work in the
user's profile. Each agent writes this record while it works. `AI_Agent_Claw`
parses every agent found on the machine into **ai_agents.db**:

| Agent | Where its record lives (under `%USERPROFILE%`) | `app` |
|---|---|---|
| Claude Code | `.claude\projects\<project>\<session>.jsonl` (sub-agents in `<session>\subagents\`), `file-history\`, `sessions\<pid>.json`, `todos\`, `plans\*.md`, `history.jsonl`, `jobs\*\state.json` + `timeline.jsonl`, `settings*.json`, `.claude.json`; background task output in `AppData\Local\Temp\claude\...\tasks\*.output` | cli, job |
| Claude desktop | `AppData\Roaming\Claude\claude-code-sessions\*.json`, `local-agent-mode-sessions\*\` (a whole `.claude` tree per session, plus generated `outputs\`) | desktop, desktop-agent-mode |
| Codex | `.codex\sessions\YYYY\MM\DD\rollout-*.jsonl(.zst)`, `archived_sessions\`, `state_5.sqlite` (threads: title, git sha and origin, sandbox policy), `thread_history_1.sqlite`, `config.toml`, `computer-use\config.json` | cli, vscode |
| Gemini CLI | `.gemini\tmp\<hash>\chats\session-*.json`, `logs.json` | cli |
| GitHub Copilot CLI | `.copilot\session-store.db` (sessions, turns, files, commands with exit codes), `session-state\*\events.jsonl`, `logs\process-<ms>-<PID>.log` | cli |
| Antigravity | `.gemini\antigravity\conversations\*.pb` (not decoded: one session row per file), `browser_recordings\` (screenshots of pages it drove), `brain\*.md` | desktop |
| Roo Code / Kilo Code / Cline | `AppData\Roaming\Code\User\globalStorage\<extension>\tasks\<id>\` (`ui_messages.json`, `api_conversation_history.json`) | vscode |

The record is the agent's own. A command in it is **proof that the agent ran
it**, not a person at the keyboard. It ran with the account's rights, at the
time written beside it. No other evidence that "an AI agent did this" is as
strong. A process tree or input timing only infers; this record holds what the
agent was asked and what it did.

The parser never opens these credential files: `.claude\.credentials.json`,
`.codex\auth.json`, `.gemini\oauth_creds.json` and `.audit-key`.

## Tables

### `ai_agent_sessions`: one row per session

| Column(s) | Meaning |
|---|---|
| `agent`, `app` | The agent, and where it ran (see the table above). |
| `user_name` | The profile folder. |
| `session_id`, `parent_session_id` | `parent_session_id` is set on a sub-agent and names the session that started it. |
| `title` | The session's title. |
| `project_path` | The folder the agent worked in. |
| `model` | The model used. |
| `agent_version`, `entrypoint` | The agent's version and how it was started. |
| `git_branch`, `git_sha`, `git_origin` | The repository state. |
| `approval_mode` | How freely commands ran. Claude Code's permission mode (e.g. `auto`, `bypassPermissions`); Codex's approval policy (e.g. `never`). |
| `sandbox_policy` | Codex's sandbox. |
| `pid`, `process_start` | The agent process, where its record names it. |
| `first_ts`, `last_ts` | The session's first and last step. |
| `prompts` | Requests the person typed. |
| `commands`, `file_changes`, `tool_calls` | What the agent did. |
| `source_path`, `source_size`, `source_modified`, `parsed_at` | The record file and when it was parsed. |

### `ai_agent_steps`: one row per step

`ts` is when the step was written (UTC). `role` says who took the step:

| role | meaning |
|---|---|
| `user` | The person: a request they typed (`kind = prompt`), or a command they ran themselves with `!` in Claude Code (`kind = command`). |
| `assistant` | The agent. |
| `agent` | The main agent's instruction to a sub-agent (`prompt`, in the sub-agent's transcript: `is_sidechain = 1`), or a message from **another agent session** (`prompt`, `is_sidechain = 0`). These are not the person's words. |
| `tool` | A tool call's output (`result`), with `status` ok / error / interrupted / rejected. |
| `system` | A prompt nobody typed (`kind = prompt`: a scheduled task, a program through `claude -p`, the program resuming on its own), or text the program injected (`notice`). |

**Who sent a prompt (`origin`).** Claude Code records where every turn came
from. A prompt is the person's only when `role = 'user'`; `origin` says more:

| origin | meaning |
|---|---|
| `person (typed)`, `person (queued)`, `person (suggestion accepted)` | The person, at the keyboard. |
| `scheduled task <id>` | A task scheduled earlier (a /loop, a reminder, a routine) fired with no one typing (`role = system`). |
| `another agent session <name> (<id>)` | A message from another Claude session or a background sub-agent's hand-back (`role = agent`). |
| `a program (claude -p / Agent SDK)` | Sent through `claude -p` or the Agent SDK: a script, an application or a person at a terminal. Not known to be the person (`role = system`). |
| `automatic continuation` | The program resumed the agent on its own, e.g. after a usage limit reset (`role = system`). |

Claude Code writes these prompts as hidden (`isMeta`) lines; they are kept
because they are what set the agent working with no person typing. Older
versions do not record origin: `origin` is empty and `role = 'user'`.

`kind`, for the agent's steps:

| kind | what the agent did |
|---|---|
| `answer` | Its answer. |
| `command` | Ran a command line. |
| `file_read`, `file_write`, `file_edit` | Read, wrote or edited a file. |
| `search` | Searched files. |
| `web` | Fetched or searched the web. |
| `browser` | Drove a browser: a claude-in-chrome or other browser MCP tool; the URL is in `target`. |
| `computer` | Computer use: a click, key or screenshot on the desktop. |
| `screenshot` | An Antigravity browser recording. |
| `mcp` | Called another MCP server's tool; the server is in `tool`. |
| `subagent` | Started a sub-agent. |
| `todo` | A todo list entry. |
| `plan` | A plan file. |
| `job` | A background job's step. |
| `tool` | Called any other tool. |

Other columns:

| Column | Meaning |
|---|---|
| `command` | The command line. |
| `program` | The executables the command started, comma-separated (`python, git`), read in the shell the tool ran: in Claude Code's Bash tool (Git Bash) `ls`, `cat`, `rm` are programs (ls.exe ...); in PowerShell (Claude Code's PowerShell tool, Codex, Gemini CLI, Copilot, Cline) they are aliases of cmdlets and start nothing. Shells are counted as well as what they wrap; `Start-Process X` and `start X` name X; a variable set to a path in the same line is followed. `cd`, builtins, cmdlets, here-document bodies, comments and redirections are not programs. |
| `exit_code` | The exit code, where the agent recorded it: Claude Code (a failed call's result opens "Exit code N"; background tasks end `[exited with code N]`), Codex, Gemini CLI ("Exit Code: N" after the output) and Copilot. A successful Claude Code call has no exit code - its `status` is `ok`. |
| `duration_ms` | How long the step took. |
| `output` | The first 1,000 characters of the call's result, on the call's own row: what the command printed, the file it read, the page it fetched. The whole result (up to `ai_agents_result_chars`) is the `result` row with `step_id = <this step_id>:result`. |
| `status` | On a call: `ok`, `error` (a non-zero exit code or a failed tool), `interrupted`, or `rejected` - refused before it ran. |
| `approval` | Who let the call run (Claude Code's `permissionDecision`): `allowed by the person (once)` / `(for the session)`, `allowed by a settings rule`, `allowed by the permission mode`, `allowed by the auto-mode classifier`; or `refused by ...`. Empty when the agent does not record it. |
| `origin` | On a prompt: who sent it (see above). |
| `seq` | The step's place in its session: 1, 2, 3 ... in the order the record holds them. |
| `turn` | Which instruction the step answers: the session's 1st, 2nd ... prompt opens turn 1, 2 ...; every step up to the next prompt is that turn's work. 0 = before any instruction. |
| `instruction` | The opening 300 characters of that instruction - the order behind the command - on the step itself. |
| `ordered_by` | Who gave that instruction: `person (typed)`, `scheduled task <id>`, `another agent session <name>`, `a program (claude -p / Agent SDK)`, `the main agent of session '<name>'` (a sub-agent's order), `person` (an agent that does not record more). |
| `session_name` | The session's name (below), on every step: which session was ordered to do it. |

Every AI table carries **`user_sid`**: the SID of the profile's owner, from this machine's ProfileList (live) or the case's own SOFTWARE hive (offline, and only when the case holds one Users tree). It is empty when nothing names the folder - never guessed - and is not part of a row's identity.

`ai_agent_sessions.name` names every session: the title the agent recorded
(`title`, kept exactly as recorded), or - when it recorded none - `first
request: <its opening words>`. A sub-agent is named `<type>: <what it was
started to do>` from its meta file.
| `target` | The file, URL, query or pattern. |
| `cwd` | The working folder. |
| `text` | The full content. A tool's output is cut at `ai_agents_result_chars` (default 4000); `text_length` keeps its full length. |

**Prompts with no transcript.** Claude Code's `history.jsonl` and Gemini's
`logs.json` keep the prompts typed. When a session's transcript is gone, those
prompts are still written as `prompt` steps. So a deleted session still shows
what was asked.

### `ai_agent_file_versions`: the copy an agent saved before changing a file

Columns: `agent`, `user_name`, `session_id`, `file_path`, `version`,
`saved_at`, `size`, `sha1`, `backup_path` and `in_case_path`. These come from
Claude Code `file-history` and Copilot's session files.

A copy is the file **as it was before the agent's edit**. A version with no
`sha1` means the file was new. `in_case_path` is set once the copy is saved into
the case. That happens through the File Versions tab's "Save selected into the
case", or the `ai_agents_copy_file_versions` setting (off by default).

### `ai_agent_processes`: agent processes

Columns: `pid`, `process_start`, `session_id`, `cwd`, `started_at`, `kind`
(interactive, daemon, cli), `entrypoint` and `version`. The sources are:
- `.claude\sessions\<pid>.json`;
- the daemon attach journal;
- Copilot's `process-<ms>-<PID>.log` file names.

### `ai_agent_settings`: what the agent was allowed and set up to do

Columns: `agent`, `scope` (`user`, `user local`, `project <path>`,
`desktop agent session <id>`, `computer use`), `setting` and `value`. Values are
masked.

Settings recorded:
- `permissions.allow` / `deny`;
- MCP servers (environment variable names only, never their values);
- installed plugins and skills;
- approval and sandbox modes;
- trusted folders;
- computer-use configuration.

**Secrets are masked at parse time.** These all become `[masked: kind]`:
- API keys (Anthropic, OpenAI, GitHub, AWS, Google, Slack);
- JWTs and bearer tokens;
- private keys;
- passwords in URLs;
- `password=` / `api_key:` values.

## What Windows recorded of the same acts

`data/ai_agent_links.py` matches a step to Windows' own records. Every match
names its rule and both rows. There is no score.

| Agent step | Windows record | Window |
|---|---|---|
| `command` (its `program`) | Prefetch run times, BAM, Security 4688 | from 5 s before the step to its end |
| `command` (its `program`) | SRUM app usage | the hour that holds the step |
| `file_write` / `file_edit` (its `target`) | USN journal changes on that path | ±2 min |
| `browser` / `web` (its URL) | Browser history visits | ±1 min |

Prefetch keeps only a program's last eight run times. An older agent run of a
program that has run since will therefore show no Prefetch match.

Some agent steps never get a Prefetch file:
- shell builtins;
- scripts;
- file changes made by the agent process itself (Edit/Write tools).

The MFT and USN journal show those changes instead.

Where this evidence appears:
- **Timeline:** a mark linked to an AI step carries the AI badge and a cyan line to the step. A mark with 3 or more links carries a count badge. The detail panel says "Done by an AI agent".
- **AI Agents dashboard** (Charts on any AI Agents tab): the agents' acts per day, each session's story beside the Windows records matched to it, and each program's runs.
- **Correlation Engine:** the `AIAgentSteps` and `AIAgentFileVersions` feathers.
  - Execution Time Wing: an agent command and the program's execution records.
  - File Change Time Wing: an agent file change and the MFT/USN records; credential stores are flagged.
  - Behaviour Wings: persistence created during a turn, mass file deletion during a turn, a log cleared during a turn.

## How to use it

- **Who did it?** Take a file change or command at time T on this machine. Look for an `ai_agent_steps` row near T whose `target` or `command` holds the same path. If one exists, an agent did it. The request behind it is the nearest earlier `role = 'user' AND kind = 'prompt'` row in the same session.
- **Who ordered this command, and in which session?** Its own row says: `session_name`, `turn`, `instruction`, `ordered_by`. Every step of one order: `WHERE session_id = ? AND turn = ? ORDER BY seq`.
- **What did it run?** Query `kind = 'command' AND role = 'assistant'`. `program` names the executables; `exit_code` and `status` say whether a command failed; `output` is what it printed.
- **Did the person approve it?** `approval`: `allowed by the person` means they were asked and said yes; `allowed by the auto-mode classifier` / `a settings rule` / `the permission mode` means nobody was asked; `status = 'rejected'` means it never ran.
- **Was the person there at all?** A turn opened by a prompt with `role = 'system'` or a non-sidechain `role = 'agent'` was started by a scheduled task, a program or another agent session, not typed - `origin` names which.
- **What did it change?** Query `kind IN ('file_write', 'file_edit')`. `ai_agent_file_versions` holds the earlier content.
- **What did it drive?** Query `kind IN ('browser', 'computer', 'screenshot', 'web')`.
- **How much freedom did it have?** In `approval_mode`, `bypassPermissions`, `auto`, Codex `never` or `danger-full-access` mean commands ran without a prompt per command. Check `ai_agent_settings` for the permissions in force.
- **Sub-agents:** a sub-agent's rows have a `session_id` containing `/`; `parent_session_id` links it to its parent.
- **Repeated steps:** a resumed or forked session can repeat earlier steps (the same `step_id` in two sessions). Count distinct `step_id` per agent.

## In the Activity Story (UBA)

- `ai_agent_session`: "<person> worked with <agent> in <folder> between ...: made N requests, ran N commands, changed files N times".
- `ai_agent_turn`: one per request: "<agent> ran N commands (...) and changed N files (...) in <folder> between ..., after <person> asked: "..."". Who drove it: automation, basis "run by <agent> (recorded in its session record)".

## Caveats

- The record exists only while the user keeps it. An agent can be set to delete old sessions; Claude Code keeps about 30 days by default. `history.jsonl` prompts often outlive the transcripts.
- A command in the record ran with the account's rights. Whether the person approved each command depends on `approval_mode`.
- Antigravity's conversations are protobuf and are not decoded: the session row records the file and its times only.
- Other agents keep records this parser does not read: Cursor, Windsurf, Windows agent workspaces. A missing record for them is not evidence that no agent ran.
