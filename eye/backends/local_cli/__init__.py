"""
Local CLI Backend Package - The "Letter Under the Door" Approach

Welcome to the Local CLI backend system! This package handles AI tools that run as 
command-line programs rather than fancy web APIs. Think of it as the "old school" 
approach - we write everything down in text, slide it under the door (pipe to stdin), 
and read what comes back (capture stdout).

WHY USE LOCAL CLI?
==================
- **Maximum Privacy**: Your forensic data never leaves your machine - not even to localhost
- **Air-Gapped Systems**: Works on completely isolated networks with no internet
- **Experimental Tools**: Try cutting-edge AI tools that don't have proper APIs yet
- **Simple Setup**: Just download an executable and point Eye at it

HOW IT WORKS (The "Letter Under the Door" Method)
==================================================
1. **Write Everything Down**: We combine the system prompt, chat history, available tools,
   and your question into one big text block
   
2. **Launch the Program**: We start the CLI tool as a subprocess (like opening a terminal)

3. **Pipe the Text In**: We send our text block to the program's stdin (like typing into
   a terminal and hitting enter)
   
4. **Capture the Output**: We read everything the program prints to stdout (like reading
   terminal output)
   
5. **Extract Tool Calls**: If the AI wants to use forensic tools, it writes special XML
   tags that we extract using regex

THE XML TOOL PROTOCOL
=====================
Since CLI tools can only output text (not structured JSON), we teach them a special 
language using XML tags:

    <tool_call>
        <name>query_database</name>
        <args>{"database_name": "prefetch.db", "sql_query": "SELECT * FROM entries"}</args>
    </tool_call>

When we see these tags in the output, we:
1. Extract the tool name and arguments using regex
2. Execute the forensic tool (query_database, search_artifacts, etc.)
3. Feed the results back to the AI for analysis

This is like teaching someone to write "PLEASE CALL: [name] WITH: [details]" in their 
letters when they need you to do something specific.

SUPPORTED CLI TOOLS
===================
- **gemini-cli**: Google's Gemini via command-line (requires API key but runs locally)
- **llama-cli**: Local LLaMA models via llama.cpp (100% offline)
- **claude-code**: Anthropic's Claude Code CLI
- **ollama CLI**: Ollama's command-line interface (alternative to REST API)
- **Custom CLI**: Any tool that reads from stdin and writes to stdout

COMPONENTS
==========
- **GenericCLIBackend**: The main adapter that wraps CLI tools and handles the XML protocol
- **CLI_PROFILES**: Configuration "phone book" that tells us how to call each CLI tool
- **get_profile()**: Look up configuration for a specific CLI tool
- **list_supported_backends()**: Get a list of all CLI tools we know how to talk to

EXAMPLE USAGE
=============
    from eye.backends.local_cli import GenericCLIBackend, get_profile
    
    # Create a backend for gemini-cli
    backend = GenericCLIBackend(
        executable_path="C:/tools/gemini.cmd",
        backend_type="gemini_cli",
        model_name="gemini-1.5-flash"
    )
    
    # Send a forensic query
    response = backend.generate(
        system_prompt="You are EYE, the forensic assistant...",
        user_message="Show me all prefetch entries",
        tools=[...],  # Eye forensic tools
        history=[...]
    )
    
    # The backend handles:
    # - Assembling the text block with XML tool instructions
    # - Launching gemini.cmd as a subprocess
    # - Piping the text to stdin
    # - Capturing stdout
    # - Extracting any <tool_call> XML tags
    # - Returning structured response with content and tool_calls

COMPARISON TO OTHER APPROACHES
===============================
- **Cloud API** (cloud_api/): Structured JSON over HTTPS to remote servers
  - Pros: Most powerful models, native function calling
  - Cons: Data goes to the cloud, requires internet
  
- **Local Server** (local_server/): Structured JSON over HTTP to local services
  - Pros: Privacy + modern APIs, can run on LAN
  - Cons: Requires persistent service, more complex setup
  
- **Local CLI** (this package): Text streams via subprocess
  - Pros: Maximum privacy, works air-gapped, simple setup
  - Cons: Text-based protocol (XML extraction), process spawn overhead

WHEN TO USE LOCAL CLI
======================
✓ You need 100% air-gapped operation (no network at all)
✓ You're experimenting with new AI tools that don't have APIs yet
✓ You want the simplest possible setup (just an executable)
✓ You're okay with text-based tool calling (XML protocol)

✗ You need the fastest possible performance (use Local Server instead)
✗ You want native function calling (use Cloud API or Local Server)
✗ You need to run the AI on a different machine (use Local Server on LAN)

TECHNICAL NOTES
===============
- **Windows Compatibility**: Automatically handles .bat/.cmd files with shell=True
- **Model Discovery**: Uses adaptive probing to find available models
- **Timeout**: 120 seconds for generation (plenty of time for complex queries)
- **Error Handling**: Captures stderr and provides meaningful error messages
- **Regex Pattern**: `<tool_call>\\s*<name>(.*?)</name>\\s*<args>(.*?)</args>\\s*</tool_call>`

"""

from eye.backends.local_cli.generic_cli_backend import GenericCLIBackend
from eye.backends.local_cli.cli_profiles import (
    CLI_PROFILES,
    get_profile,
    list_supported_backends
)

__all__ = [
    'GenericCLIBackend',
    'CLI_PROFILES',
    'get_profile',
    'list_supported_backends'
]
