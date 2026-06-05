import sys
import re
import os

base_dir = r"C:\Users\Ghass\Crow-eye DEV\Crow-Eye\correlation_engine"

def process_config_manager():
    path = os.path.join(base_dir, "config", "config_manager.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add import
    if "CentralizedScoreConfig" not in content:
        content = re.sub(r'(from \.pipeline_config import PipelineConfig\n)', r'\1from correlation_engine.config.centralized_score_config import CentralizedScoreConfig\n', content, count=1)

    # Replace _get_default_weights_from_registry fallback
    pattern_get_weights = r"def _get_default_weights_from_registry.*?return \{(.*?)\}"
    replacement_get_weights = r"""def _get_default_weights_from_registry() -> Dict[str, float]:
    \"\"\"Load default weights from the central ArtifactTypeRegistry.\"\"\"
    from .artifact_type_registry import get_registry
    return get_registry().get_default_weights_dict()"""
    content = re.sub(pattern_get_weights, replacement_get_weights, content, flags=re.DOTALL)

    # Replace score_interpretation in DEFAULT_CONFIGS
    pattern_score_interp = r'"score_interpretation": \{\s*"confirmed": \{[^}]*?\},\s*"probable": \{[^}]*?\},\s*"weak": \{[^}]*?\},\s*"minimal": \{[^}]*?\}\s*\},'
    replacement_score_interp = r'"score_interpretation": CentralizedScoreConfig.get_default().thresholds,'
    content = re.sub(pattern_score_interp, replacement_score_interp, content, flags=re.DOTALL)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

process_config_manager()
print("config_manager.py updated.")
