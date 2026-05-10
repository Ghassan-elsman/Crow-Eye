import os
import sys
import logging
from pathlib import Path
import importlib.util

class SystemDiagnostics:
    """
    Performs system integrity checks for the EYE AI Assistant.
    """
    
    def __init__(self, config_manager=None, credential_manager=None):
        self.config_manager = config_manager
        self.credential_manager = credential_manager
        self.logger = logging.getLogger(__name__)
        
    def run_full_check(self):
        """Run all diagnostic checks and return a summary."""
        results = {
            "ui": self.check_ui_artifacts(),
            "sdks": self.check_backend_sdks(),
            "environment": self.check_environment(),
            "config": self.check_config_integrity()
        }
        return results
        
    def check_ui_artifacts(self):
        """Verify React frontend build artifacts exist."""
        # Check standard dist path
        ui_path = Path(__file__).parent.parent / "ui" / "react" / "dist" / "index.html"
        
        # Also check relative to workspace if running in dev
        alt_ui_path = Path("eye/ui/react/dist/index.html")
        
        exists = ui_path.exists() or alt_ui_path.exists()
        path_used = ui_path if ui_path.exists() else alt_ui_path
        
        return {
            "name": "UI Interface",
            "status": "PASS" if exists else "FAIL",
            "message": f"React build artifacts found at {path_used}" if exists else "React build artifacts missing! UI will fail to load.",
            "path": str(path_used.absolute()) if exists else "None"
        }
        
    def check_backend_sdks(self):
        """Verify required AI SDKs are installed."""
        sdks = [
            ("google.genai", "Google GenAI (Gemini)"),
            ("openai", "OpenAI"),
            ("anthropic", "Anthropic")
        ]
        
        sdk_results = []
        for module_name, display_name in sdks:
            spec = importlib.util.find_spec(module_name)
            installed = spec is not None
            sdk_results.append({
                "name": display_name,
                "status": "PASS" if installed else "INFO",
                "message": f"{display_name} SDK is installed." if installed else f"{display_name} SDK is missing. {display_name} backend will be unavailable."
            })
            
        return sdk_results
        
    def check_environment(self):
        """Check Python environment details."""
        return {
            "python_version": sys.version,
            "platform": sys.platform,
            "cwd": os.getcwd()
        }
        
    def check_config_integrity(self):
        """Check if configuration and credentials are set up."""
        if not self.config_manager:
            return {"status": "SKIPPED", "message": "ConfigManager not provided."}
            
        try:
            config = self.config_manager.load_config()
            has_config = bool(config and config.get("backend"))
            
            backend = config.get("backend") if has_config else "None"
            has_key = False
            if has_config and self.credential_manager:
                key_name = f"{backend}_api_key"
                has_key = bool(self.credential_manager.get_credential(key_name))
                
            return {
                "name": "Configuration",
                "status": "PASS" if has_config else "WARNING",
                "message": f"Configured for {backend}. " + ("API Key found." if has_key else "API Key missing!"),
                "backend": backend
            }
        except Exception as e:
            return {"status": "FAIL", "message": f"Config error: {str(e)}"}
