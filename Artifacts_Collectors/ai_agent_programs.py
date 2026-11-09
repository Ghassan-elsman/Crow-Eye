"""Which programs an AI agent's command line started.

An agent's shell tool (Claude Code's Bash/PowerShell, Codex exec_command,
Gemini run_shell_command, Copilot, Cline) records the command line it ran,
not the executables. This turns the line into the programs Windows started,
named the way Prefetch, AmCache, SRUM and process-creation events name them -
the executable's file name without `.exe`, lower case - so the AI's step can be
put beside the system's own record that the program ran.

Not counted as a program:
  - the shell the tool itself runs in (bash, pwsh): it starts for every command
    and says nothing about what was run;
  - shell builtins and keywords (cd, echo, export, for, if ...) and PowerShell
    cmdlets (Verb-Noun), which run inside the shell;
  - the body of a here-document (`python - <<'EOF' ... EOF`): that is input to
    the program, not commands.

Wrappers are looked through: `cmd /c X`, `pwsh -Command "X"`, `powershell -c X`,
`bash -c "X"`, `sudo/env/nohup/time/timeout ... X`, the PowerShell call
operator `& "C:\\path\\x.exe"`, and `Start-Process X` / `start X`. Launchers that
are programs themselves (`npx`, `uv`, `python -m`) are kept as what they are:
npx is node, uv is uv.

Which words are programs depends on the shell, so the caller says which one
ran the line when it knows (`shell=`):
  - bash (Claude Code's Bash tool is Git Bash on Windows): only bash's own
    builtins run inside it - `ls`, `cat`, `rm`, `sort`, `mkdir` are
    executables of their own (Git's usr\\bin\\ls.exe ...), with a Prefetch file;
  - powershell (Claude Code's PowerShell tool; Codex, Gemini CLI, Copilot and
    Cline run their shell commands in PowerShell on Windows): `ls`, `cat`,
    `rm`, `sort`, `curl` are aliases of cmdlets and start nothing;
  - cmd: its internal commands (dir, copy, del ...) start nothing;
  - unknown: any word that is a builtin or alias in one of the three is left
    out, so a name is never counted as a program that might not have been one.
A variable set to a path in the same line (`$py = "C:\\...\\python.exe"; & $py`,
`PY=/c/.../python.exe; "$PY" x.py`) is read as that path. A script is named by
what runs it: `.bat`/`.cmd` start cmd, `.sh` bash, `.py` python, `.vbs` wscript;
a `.ps1` runs inside the PowerShell that called it.
"""

import os
import re

# bash's builtins and keywords: they run inside bash. Everything else is a file.
_BASH_BUILTINS = {
    "cd", "echo", "export", "set", "unset", "source", ".", "exit", "return", "true",
    "false", "test", "[", "[[", "]]", "printf", "read", "pwd", "pushd", "popd", "dirs",
    "alias", "unalias", "local", "declare", "typeset", "readonly", "shift", "trap", "wait",
    "eval", "exec", "type", "command", "builtin", "let", "ulimit", "umask", "hash",
    "history", "jobs", "fg", "bg", "kill", "disown", "getopts", "mapfile", "readarray",
    "shopt", "enable", "help", "logout", "caller", "compgen", "complete", "times",
    "if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case",
    "esac", "function", "in", "select", "break", "continue", "{", "}", "!", ":",
}
# cmd.exe's internal commands.
_CMD_INTERNAL = {
    "assoc", "call", "cd", "chdir", "cls", "color", "copy", "date", "del", "dir", "echo",
    "endlocal", "erase", "exit", "for", "ftype", "goto", "if", "md", "mkdir", "mklink",
    "move", "path", "pause", "popd", "prompt", "pushd", "rd", "rem", "ren", "rename",
    "rmdir", "set", "setlocal", "shift", "start", "time", "title", "type", "ver", "verify",
    "vol", "@echo",
}
# PowerShell's keywords and its built-in aliases (Windows PowerShell 5.1): each
# names a cmdlet that runs inside PowerShell.
_PS_WORDS = {
    "if", "elseif", "else", "foreach", "for", "while", "do", "until", "switch", "function",
    "filter", "param", "begin", "process", "end", "try", "catch", "finally", "throw", "trap",
    "return", "break", "continue", "exit", "class", "enum", "using", "data",
    "%", "?", "ac", "cat", "cd", "chdir", "clc", "clear", "clhy", "cli", "clp", "cls", "clv",
    "compare", "copy", "cp", "cpi", "cpp", "curl", "cvpa", "dbp", "del", "diff", "dir",
    "ebp", "echo", "epal", "epcsv", "erase", "fc", "fhx", "fl", "ft", "fw", "gal", "gbp",
    "gc", "gcb", "gci", "gcm", "gcs", "gdr", "ghy", "gi", "gjb", "gl", "gm", "gmo", "gp",
    "gps", "gpv", "group", "gsv", "gu", "gv", "gwmi", "h", "history", "icm", "iex", "ihy",
    "ii", "ipal", "ipcsv", "ipmo", "irm", "iwmi", "iwr", "kill", "lp", "ls", "man", "md",
    "measure", "mi", "mkdir", "mount", "move", "mp", "mv", "nal", "ndr", "ni", "nmo", "nv",
    "ogv", "oh", "popd", "ps", "pushd", "pwd", "r", "rbp", "rd", "rdr", "ren", "ri", "rjb",
    "rm", "rmdir", "rmo", "rni", "rnp", "rp", "rv", "rvpa", "rwmi", "sajb", "sal", "sasv",
    "sbp", "sc", "scb", "select", "set", "shcm", "si", "sl", "sleep", "sls", "sort", "sp",
    "spjb", "spps", "spsv", "stz", "sv", "swmi", "tee", "trcm", "type", "wget", "where",
    "wjb", "write", "help", "prompt", "write-host",
}
# A shell the caller did not name: a word that is not a program in any of them.
_BUILTINS = _BASH_BUILTINS | _CMD_INTERNAL | _PS_WORDS
_WORDS_OF = {"bash": _BASH_BUILTINS, "sh": _BASH_BUILTINS, "cmd": _CMD_INTERNAL,
             "powershell": _PS_WORDS, "pwsh": _PS_WORDS}
# Words that start the program named after them (Start-Process, cmd's start).
_STARTERS = {"start-process", "saps", "start"}
# How a script given as the program is run.
_SCRIPT_RUNNER = {".bat": "cmd", ".cmd": "cmd", ".sh": "bash", ".py": "python", ".pyw": "pythonw",
                  ".vbs": "wscript", ".ps1": "", ".psm1": ""}
_VAR_PS = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\"[^\"\n]*\"|'[^'\n]*')")
_VAR_SH = re.compile(r"(?:^|[\s;&|(])([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"\n]*\"|'[^'\n]*'|[^\s;&|\"']+)")
_VAR_USE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
# Prefixes that run the next word as the program.
_PREFIX_RUNNERS = {"sudo", "env", "nohup", "time", "timeout", "nice", "stdbuf", "xargs", "exec",
                   "then", "do", "else", "!"}
# Shells typed in a command line: a process of their own, plus whatever they
# were told to run (-c / /c / -Command).
_SHELLS = {"bash", "sh", "zsh", "cmd", "pwsh", "powershell"}
_SHELL_CMD_FLAGS = {"-c", "/c", "/k", "-command", "-commandwithargs", "-encodedcommand", "-e"}
_HEREDOC = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
_REDIRECT = re.compile(r"\d*>&\d*|&>>?|\d*>>?\s*[^\s|;&]+|<\s*[^\s|;&<]+")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_CMDLET = re.compile(r"^[A-Za-z]+-[A-Za-z]+$")


def _strip_heredocs(command: str) -> str:
    """The command with every here-document body removed: bash's `<<EOF ... EOF`
    and PowerShell's here-strings `@' ... '@` / `@" ... "@`."""
    lines = command.split("\n")
    out, terminator = [], None
    for line in lines:
        if terminator is not None:
            if line.strip() == terminator or (terminator in ("'@", '"@') and line.startswith(terminator)):
                terminator = None
            continue
        stripped = line.rstrip()
        if stripped.endswith(("@'", '@"')):
            # Kept without its opening @' - a lone quote would swallow the rest.
            out.append(stripped[:-2])
            terminator = stripped[-1] + "@"
            continue
        out.append(line)
        m = _HEREDOC.search(line)
        if m:
            terminator = m.group(1)
    return "\n".join(out)


# Words that open a line of program source, not a command: an agent sometimes
# hands its shell tool Python (or JavaScript) as it would write it in a file.
_CODE_WORDS = {"import", "from", "def", "class", "return", "raise", "pass", "with", "except",
               "elif", "lambda", "yield", "assert", "global", "nonlocal", "async", "await", "const",
               "let", "var", "print"}


def _not_a_program_name(name: str) -> bool:
    """Numbers, dates, hex, `_private` names and `obj.attr` - what a line of code
    or a here-string body leaves where a program name would be."""
    if re.match(r"^[\d\-:.]+$", name) or re.match(r"^0x[0-9a-f]+$", name) or name.startswith("_"):
        return True
    # A dot is a version (python3.12) or nothing: `self._lock`, `report.json`.
    return "." in name and not re.match(r"^[a-z][a-z0-9_+\-]*\d(\.\d+)+$", name)


def _tokens(segment: str):
    """Words split on whitespace outside quotes, the quotes kept. A quote may
    open mid-word - `CSS="/c/Crow Eye Site/a.css"` is one word - which
    shlex's non-POSIX mode splits at the spaces inside it."""
    out, cur, quote = [], [], None
    for ch in segment:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch.isspace():
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def _unquote(tok: str) -> str:
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        tok = tok[1:-1]
    return tok


def program_name(token: str, shell=None) -> str:
    """'C:\\Program Files\\Python312\\python.exe' -> 'python'; '' when not a program
    (in `shell`, when the caller knows which shell ran it)."""
    t = _unquote(token).strip().rstrip(")")
    if not t or t[0] in "-<>(`@{" or t.startswith(("./-", "%")):
        return ""
    if t[0] == "$":
        # An unresolved variable: a program only if the rest is a path to one
        # ("$env:ProgramFiles\Git\bin\git.exe").
        if not re.search(r"[\\/][^\\/]+\.exe$", t, re.I):
            return ""
    name = re.split(r"[\\/]", t)[-1].lower()
    if name.endswith((".exe", ".com")):
        # Named with its extension: a file, whatever an alias of that name does.
        name = name[:-4]
        return name if re.match(r"^[a-z0-9_][a-z0-9_.+\-]*$", name) else ""
    else:
        ext = os.path.splitext(name)[1]
        if ext in _SCRIPT_RUNNER:
            return _SCRIPT_RUNNER[ext]
    words = _WORDS_OF.get(shell, _BUILTINS)
    if not name or name in words or name in _CODE_WORDS or _CMDLET.match(name) or "=" in name:
        return ""
    if not re.match(r"^[a-z0-9_][a-z0-9_.+\-]*$", name) or _not_a_program_name(name):
        return ""
    return name


def _resolve(tok: str, env: dict) -> str:
    """The token with a variable set earlier in the line replaced by its value."""
    if "$" not in tok or not env:
        return tok
    return _VAR_USE.sub(lambda m: env.get(m.group(1), m.group(0)), tok)


def _starter_target(toks, shell):
    """The program `Start-Process X` / `start "" X` names, or ''."""
    i = 0
    while i < len(toks):
        tok = _unquote(toks[i])
        low = tok.lower()
        if low in ("-filepath", "-file"):
            return toks[i + 1] if i + 1 < len(toks) else ""
        if tok == "" or low.startswith(("-", "/")) and len(low) > 1 and not re.match(r"^/[a-z]:", low):
            i += 1
            continue
        return toks[i]
    return ""


def _segment_programs(segment: str, depth: int, shell=None, env=None):
    raw = _tokens(segment.strip())
    if raw and re.match(r"^\$[A-Za-z_][A-Za-z0-9_]*\s*\+?=", raw[0]):
        return []                                        # $c="C:\..."  - an assignment
    toks = [_resolve(t, env or {}) for t in raw]
    i = 0
    while i < len(toks):
        tok = _unquote(toks[i])
        low = tok.lower()
        if not tok or _ENV_ASSIGN.match(tok) or low in _PREFIX_RUNNERS:
            i += 1
            if low == "timeout" and i < len(toks) and re.match(r"^\d", toks[i]):
                i += 1                                   # timeout 30 python ...
            continue
        if low == "&" or (low == "." and shell in ("powershell", "pwsh")):
            i += 1                                       # PowerShell call / dot-source
            continue
        if tok.startswith("&") and len(tok) > 1:         # &"C:\x.exe"
            tok = tok[1:]
        if low in _STARTERS and shell != "bash":
            # Start-Process notepad / start "" "C:\x.exe": the program started.
            rest = toks[i + 1:]
            if low == "start" and rest and _unquote(rest[0]) == "" and len(rest) > 1:
                rest = rest[1:]                          # cmd's empty window title
            target = program_name(_starter_target(rest, shell), None)
            return [target] if target else []
        nxt = _unquote(toks[i + 1]) if i + 1 < len(toks) else ""
        if nxt.startswith(("=", "+=", "-=")) or tok.endswith(("(", ":")):
            return []                                    # `x = 5`, `def f():` - code, not a command
        name = program_name(tok, shell)
        if not name:
            return []
        if name in _SHELLS:
            # A shell typed in the command line is a process of its own
            # (powershell -Command "Get-Process" starts powershell.exe), and
            # so is whatever it was told to run.
            inner_shell = {"sh": "bash", "zsh": "bash"}.get(name, name)
            rest = toks[i + 1:]
            for k, flag in enumerate(rest):
                if _unquote(flag).lower() in _SHELL_CMD_FLAGS and k + 1 < len(rest):
                    inner = " ".join(_unquote(x) for x in rest[k + 1:])
                    return [name] + (programs_of(inner, depth + 1, inner_shell) if depth < 3 else [])
            return [name]
        return [name]
    return []


def _split_segments(text: str, shell=None):
    r"""The command split on ; && || | & and newlines - outside quotes only.
    A newline inside `python -c "..."` is the program's own code. In bash a
    backslash escapes the next character, so `grep -E "\"(a|b)"` stays one
    command; PowerShell and cmd take the backslash literally (`"C:\dir\"`)."""
    escapes = shell in ("bash", "sh")
    out, cur, quote, i = [], [], None, 0
    while i < len(text):
        ch = text[i]
        if escapes and ch == "\\" and quote != "'" and i + 1 < len(text):
            cur.append(text[i:i + 2])
            i += 2
            continue
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == "#" and shell != "cmd" and (i == 0 or text[i - 1] in " \t\n;"):
            # A comment runs to the end of the line - and an apostrophe in it
            # ("don't") is not a quote.
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
            i += 1
            continue
        two = text[i:i + 2]
        if two in ("&&", "||"):
            out.append("".join(cur)); cur = []; i += 2
            continue
        if ch == "&" and (text[i - 1:i] == ">" or text[i + 1:i + 2] == ">"):
            cur.append(ch)                       # 2>&1, &>, >&2: a redirection
            i += 1
            continue
        if ch in ";|&\n":
            out.append("".join(cur)); cur = []; i += 1
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _strip_redirects(segment: str) -> str:
    """The segment with its redirections (`> f`, `2>&1`, `< in`) removed -
    outside quotes only: `grep -E '<h[23][^>]*>'` keeps its pattern."""
    out, cur, quote = [], [], None
    for ch in segment:
        if quote:
            cur.append(ch)
            if ch == quote:
                out.append("".join(cur))
                cur, quote = [], None
            continue
        if ch in "\"'":
            out.append(_REDIRECT.sub(" ", "".join(cur)))
            cur, quote = [ch], ch
            continue
        cur.append(ch)
    out.append("".join(cur) if quote else _REDIRECT.sub(" ", "".join(cur)))
    return "".join(out)


def _variables(text: str, shell=None) -> dict:
    """Variables the line sets to a literal: PowerShell `$x = "..."`, sh `X=...`."""
    env = {}
    if shell in (None, "powershell", "pwsh"):
        for name, val in _VAR_PS.findall(text):
            env[name] = _unquote(val)
    if shell in (None, "bash", "sh"):
        for name, val in _VAR_SH.findall(text):
            env.setdefault(name, _unquote(val))
    return env


def programs_of(command: str, depth: int = 0, shell=None):
    """Every program the command line started, in order, each once."""
    if not command:
        return []
    text = _strip_heredocs(str(command))
    env = _variables(text, shell)
    # $( ... ) and backticks start programs too, but their output feeds the
    # outer command; they are read as commands of their own.
    inner = re.findall(r"\$\(([^()]*)\)", text)
    text = re.sub(r"\$\([^()]*\)", " ", text)
    out = []
    # Redirections are taken off each segment, outside its quotes: `2>&1`,
    # `&>`, `>&2` hold an `&` the splitter keeps (it once made "1" a program).
    for part in _split_segments(text, shell) + inner:
        for name in _segment_programs(_strip_redirects(part), depth, shell, env):
            if name and name not in out:
                out.append(name)
    return out


# The shell each agent's command tool runs its line in, on Windows.
_TOOL_SHELL = {"bash": "bash", "powershell": "powershell", "run_shell_command": "powershell",
               "exec_command": "powershell", "shell": "powershell", "local_shell": "powershell",
               "shell_command": "powershell", "execute_command": "powershell",
               "commandexecution": "powershell"}


def shell_of_tool(tool: str):
    """'bash' / 'powershell' for a known command tool, None when unknown."""
    return _TOOL_SHELL.get(str(tool or "").strip().lower())


def program_of(command: str, shell=None) -> str:
    """The programs a command started, comma-separated ('' for none)."""
    return ", ".join(programs_of(command, 0, shell))
