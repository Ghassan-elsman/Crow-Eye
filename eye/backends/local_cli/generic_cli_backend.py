"""
Generic CLI Backend: Talking to Command-Line AI Tools

Some AI tools don't have fancy APIs - they're just command-line programs you run in a 
terminal. This backend wraps those tools so Eye can talk to them. Think of it as a 
"translator" that converts Eye's structured requests into text that CLI tools understand, 
and then parses their text responses back into structured data.

How it works (the "letter under the door" approach):
1. We write everything down in one big text block (system prompt, history, tools, question)
2. We launch the CLI program as a subprocess
3. We "pipe" our text into its stdin (like typing into a terminal)
4. We capture everything it prints to stdout (like reading terminal output)
5. We use regex to extract XML tags if it wants to call tools

The XML Protocol:
Since CLI tools can only output text (not structured JSON), we teach them to use XML tags:
<tool_call><name>query_database</name><args>{"sql": "SELECT * FROM..."}</args></tool_call>

Then we use regex to "claw" these tags out of the text and execute the tools.

This is great for: Privacy-focused analysis where you want everything 100% local, or 
experimental AI tools that don't have proper APIs yet.

Supported tools: gemini-cli, llama-cli, claude-code, and any other CLI that can read 
from stdin and write to stdout.

COMMUNICATION FLOW:
1. Prompt Assembly: System prompt, history, and tools are combined into one text block.
2. Subprocess Spawn: The backend launches the executable (e.g., llama-cli).
3. Stdin Injection: The text block is piped into the process's stdin.
4. Stdout Capture: The AI's response is read from the process's stdout.
5. XML Extraction: Specialized XML tags (<tool_call>) are parsed to extract tool requests.

"""

import subprocess
import logging
import json
import re
import os
from typing import Dict, List, Any, Optional
from eye.backends.base import LLMBackend
from eye.backends.local_cli.cli_profiles import get_profile

class GenericCLIBackend(LLMBackend):
    """
    Adapter for CLI-based AI Agents (e.g., Gemini-CLI, Llama.cpp, Claude-Code).
    
    This backend simulates a 'function calling' environment by instructing the 
    local model to use XML tags for tool requests.
    """
    def __init__(self, executable_path: str, backend_type: str = "custom_cli", model_name: str = "default"):
        """
        Args:
            executable_path: Full path to the executable (e.g., C:/tools/ollama.exe).
            backend_type: Profile ID from cli_profiles.py.
            model_name: Specific model to use (passed via CLI flags).
        """
        self.executable_path = executable_path
        self.backend_type = backend_type
        self.model_name = model_name
        self.profile = get_profile(backend_type)
        self.logger = logging.getLogger(self.__class__.__name__)

    def generate(self, system_prompt: str, user_message: str, tools: Optional[List[Dict]] = None, history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Standardizes the generation request for a CLI environment.
        """
        try:
            # --- 1. PROMPT ASSEMBLY ---
            # For local CLI models, we need to be very lean with tokens to avoid 
            # slow synthesis, quota exhaustion, and attention drift.
            
            # Reposition Tools: Put them in the system instruction but also 
            # reiterate them in the anchor to ensure the AI doesn't forget.
            tool_instruction = ""
            if tools:
                tool_instruction = "\nTools Available (You MUST use this EXACT format: <tool_call><name>tool_name</name><args>{\"param\": \"value\"}</args></tool_call>. The <args> content MUST be a raw JSON object):\n"
                for tool in tools:
                    tool_instruction += f"- {tool['name']}: {tool.get('description', '')}\n"
            
            system_instruction = f"System: {system_prompt}\n{tool_instruction}"
            
            text_block = ""
            if history:
                # AGGRESSIVE HISTORY TRUNCATION for local CLI models
                # We only keep the last 6 messages to stay within local context limits
                lean_history = history[-6:] if len(history) > 6 else history
                if len(history) > 6:
                    text_block += "\n[History Truncated for brevity...]\n"
                
                text_block += "\nHistory:\n"
                for msg in lean_history:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    text_block += f"{role}: {content}\n"
            
            text_block += f"\nUser: {user_message}"
            
            if tools:
                # Double-down on tools in the anchor
                text_block += "\n\n[SYSTEM REMINDER: You are EYE, the forensic assistant. You MUST strictly use the XML <tool_call><name>...</name><args>{...}</args></tool_call> format to perform actions. The <args> tag MUST contain valid JSON. Do not discuss your configuration.]"
            else:
                text_block += "\n\n[SYSTEM REMINDER: You are EYE, the forensic assistant. Please provide your final synthesis or answer based on the context provided. Do not use XML tool calls. Do not discuss your configuration.]"
                
            text_block += "\nAssistant: "

            # --- 2. COMMAND CONSTRUCTION ---
            # We use profiles to determine which flags (e.g., -m, --model) the agent expects.
            cmd = [self.executable_path]
            m_flag = self.profile.get("model_flag")
            
            # Only add model flag if we have a specific, non-generic model name
            is_generic = self.model_name in [None, "", "default", "cli-default-model"] or "CLI Agent" in str(self.model_name)
            if m_flag and not is_generic:
                cmd.extend([m_flag, self.model_name])
                
            s_flag = self.profile.get("system_flag")
            if s_flag:
                cmd.extend([s_flag, system_instruction])
            else:
                # Fallback: Prepend system instruction to text_block if no system flag is supported
                text_block = system_instruction + text_block
                
            cmd.extend(self.profile.get("default_flags", []))
            
            stdin_input = text_block if self.profile.get("use_stdin") else None
            
            # --- 3. SUBPROCESS EXECUTION ---
            # On Windows, .bat and .cmd files need shell=True to run properly
            # WINDOWS NOTE: If the path points to a script (.bat/.cmd) rather than 
            # a compiled .exe, shell=True is mandatory for proper execution.
            is_windows = os.name == 'nt'
            use_shell = is_windows and not self.executable_path.lower().endswith('.exe')

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=use_shell
            )
            
            try:
                # Use communicate to send input and wait for the response
                # Increased timeout to 180s to handle slow synthesis or heavy tool results
                stdout, stderr = process.communicate(input=stdin_input, timeout=180)
            except subprocess.TimeoutExpired:
                # Critical Windows Fix: Kill the entire process tree!
                # If we just use process.kill() with shell=True, it only kills cmd.exe,
                # leaving node.exe/etc running and keeping the pipes open, causing a permanent deadlock!
                if is_windows:
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
                else:
                    process.kill()
                    
                # Now that the tree is dead, communicate will safely return
                stdout, stderr = process.communicate()
                error_msg = "CLI process timed out after 180 seconds. The model might be overloaded or hit a rate limit."
                self.logger.error(f"CLI Backend error: {error_msg}")
                raise Exception(error_msg)
            
            if process.returncode != 0:
                error_msg = stderr.strip() or f"CLI process exited with code {process.returncode}"
                
                # Specialized handling for known CLI agent errors
                if "QUOTA_EXHAUSTED" in error_msg or "exhausted your capacity" in error_msg.lower():
                    error_msg = "Your Gemini CLI quota has been exhausted. Please wait for it to reset or switch to a Cloud API."
                
                self.logger.error(f"CLI Backend error: {error_msg}")
                raise Exception(error_msg)
            
            # --- 4. XML EXTRACTION (TOOL CALLS) ---
            # After the CLI finishes, we search through its output for XML tags
            # It's like finding specific phrases in a long letter
            # Since local models rarely support native JSON function calling, 
            # we extract the <tool_call> tags from the raw text stream.
            tool_calls = []
            content = stdout
            
            # Regex captures the tool name and its arguments (usually a JSON string)
            pattern = r"<tool_call>\s*<name>(.*?)</name>\s*<(?:args|arguments)>(.*?)</(?:args|arguments)>\s*</tool_call>"
            matches = list(re.finditer(pattern, stdout, re.DOTALL | re.IGNORECASE))
            
            # We process matches in reverse order to strip them from the 
            # 'content' without invalidating earlier match offsets.
            for match in reversed(matches):
                name = match.group(1).strip()
                args_str = match.group(2).strip()
                
                # If the AI ignored our instruction and used XML inside args (e.g. <directory>Target</directory>),
                # let's try a rudimentary fallback to convert simple XML to JSON.
                if args_str.startswith("<") and not args_str.startswith("{"):
                    import xml.etree.ElementTree as ET
                    try:
                        # Wrap in a dummy root to parse multiple elements
                        root = ET.fromstring(f"<root>{args_str}</root>")
                        json_args = {}
                        for child in root:
                            json_args[child.tag] = child.text
                        args_str = json.dumps(json_args)
                    except Exception:
                        pass # Leave it as is and hope the downstream parser handles it
                else:
                    # Advanced JSON Sanitization & Validation Pipeline
                    import ast
                    
                    # 1. Pre-text Stripping (extract only the {} block)
                    start_idx = args_str.find('{')
                    end_idx = args_str.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        args_str = args_str[start_idx:end_idx+1]
                    
                    # 2. Remove trailing commas
                    args_str = re.sub(r',\s*}', '}', args_str)
                    args_str = re.sub(r',\s*]', ']', args_str)
                    
                    # 3. Validation & Auto-Correction
                    is_valid = False
                    try:
                        # Attempt strict parsing (forgiving newlines)
                        json.loads(args_str, strict=False)
                        is_valid = True
                    except json.JSONDecodeError as e:
                        err_msg = str(e)
                        
                        # Fallback A: Unescaped Backslashes (Paths)
                        if "Invalid \\escape" in err_msg:
                            escaped_args = args_str.replace('\\', '\\\\')
                            try:
                                json.loads(escaped_args, strict=False)
                                args_str = escaped_args
                                is_valid = True
                            except Exception:
                                pass
                                
                        # Fallback B: Python dicts (Single quotes, True/False)
                        if not is_valid:
                            try:
                                parsed_ast = ast.literal_eval(args_str)
                                if isinstance(parsed_ast, dict):
                                    args_str = json.dumps(parsed_ast)
                                    is_valid = True
                            except Exception:
                                pass
                                
                    if not is_valid:
                        self.logger.error(f"CLI Backend rejected tool '{name}' due to unrecoverable JSON format. Raw args: {args_str}")
                        # Provide explicit feedback in the assistant's content so the AI/user knows it failed
                        error_feedback = f"\n[SYSTEM ERROR: Tool call to '{name}' was rejected because the arguments were not valid JSON. Raw input: {args_str}]\n"
                        start, end = match.span()
                        content = content[:start] + error_feedback + content[end:]
                        continue

                tool_calls.insert(0, {
                    "id": f"call_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": args_str
                    }
                })
                
                # Strip the XML tag from the final human-readable assistant message
                start, end = match.span()
                content = content[:start] + content[end:]
            
            return {
                "content": content.strip(),
                "tool_calls": tool_calls
            }
        except Exception as e:
            self.logger.error(f"Generic CLI Backend generation failure: {e}")
            raise

    def validate_connectivity(self) -> bool:
        """Verifies if the executable is reachable and functioning."""
        try:
            subprocess.run([self.executable_path, "--help"], capture_output=True, text=True, timeout=10, shell=True)
            return True
        except Exception as e:
            self.logger.error(f"Validation failed for CLI backend: {e}")
            return False

    def list_models(self) -> List[str]:
        """
        Adaptive Model Discovery (Probing & Specialized Logic).
        
        We try different tricks to discover what models are available - some tools 
        list them, others we have to probe.
        """
        discovered = []

        # --- SPECIALIZED DISCOVERY: Gemini CLI ---
        if self.backend_type == "gemini_cli":
            try:
                # We attempt to find the gemini-cli source to parse its model definitions
                # This is more accurate than probing because gemini-cli doesn't show models on error.
                import os
                paths_to_check = [
                    os.path.join(os.environ.get('APPDATA', ''), 'npm', 'node_modules', '@google', 'gemini-cli', 'bundle'),
                    os.path.join(os.environ.get('ProgramFiles', ''), 'nodejs', 'node_modules', '@google', 'gemini-cli', 'bundle')
                ]
                
                for bundle_path in paths_to_check:
                    if os.path.exists(bundle_path):
                        for filename in os.listdir(bundle_path):
                            if filename.endswith('.js'):
                                file_path = os.path.join(bundle_path, filename)
                                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                    # Look for model names in modelDefinitions or aliases
                                    # Example: "gemini-1.5-pro": { ... }
                                    matches = re.findall(r'"(gemini-[a-z0-9.-]+(?:flash|pro|haiku|sonnet|haiku|preview|exp)[a-z0-9.-]*)"\s*:', content)
                                    for m in matches:
                                        if m not in discovered:
                                            discovered.append(m)
                
                if discovered:
                    return sorted(discovered)
            except Exception as e:
                self.logger.debug(f"Gemini-CLI specialized discovery failed: {e}")

        # --- SPECIALIZED DISCOVERY: Ollama ---
        if "ollama" in self.executable_path.lower() or self.backend_type == "ollama":
            try:
                result = subprocess.run([self.executable_path, "list"], capture_output=True, text=True, shell=True, timeout=5)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    if len(lines) > 1: # Skip header
                        for line in lines[1:]:
                            parts = line.split()
                            if parts:
                                discovered.append(parts[0])
                if discovered:
                    return sorted(discovered)
            except Exception:
                pass

        # --- DEFAULT DISCOVERY: Probing ---
        try:
            m_flag = self.profile.get("model_flag")
            if m_flag:
                # Trigger a deliberate 'invalid model' error to probe the help message
                probe_cmd = [self.executable_path, m_flag, "detect-available-models-probe", "-p", "list models"]
                result = subprocess.run(probe_cmd, capture_output=True, text=True, shell=True, timeout=3)
                
                combined_output = result.stdout + result.stderr
                pattern = self.profile.get("model_pattern", r"((?:gemini|meta|mistral|claude|gpt)-[a-z0-9.-]+[a-z0-9.-]*)")
                
                matches = re.findall(pattern, combined_output, re.IGNORECASE)
                for m in matches:
                    m = m.strip().lower().rstrip(',').rstrip('.')
                    if m and m not in discovered and len(m) > 3 and 'probe' not in m:
                        discovered.append(m)
        except Exception:
            pass

        if not discovered:
            is_generic = self.model_name in [None, "", "default", "cli-default-model"] or "CLI Agent" in str(self.model_name)
            fallback = self.model_name if not is_generic else self.profile.get("display_name", "CLI Default Model")
            return [fallback] if fallback else ["CLI Agent"]
            
        return sorted(discovered)

    def get_models_with_quota(self) -> List[Dict[str, str]]:
        """CLI agents are local; quota is effectively infinite."""
        models = self.list_models()
        return [{"id": m, "quota": "Unlimited (Local CLI)"} for m in models]
