import sys
import re
import os

base_dir = r"C:\Users\Ghass\Crow-eye DEV\Crow-Eye\correlation_engine"

def process_wing_model():
    path = os.path.join(base_dir, "wings", "core", "wing_model.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add imports
    if "CentralizedScoreConfig" not in content:
        content = re.sub(r'(from typing import .*?\n)', r'\1import logging\nfrom correlation_engine.config.centralized_score_config import CentralizedScoreConfig\n\nlogger = logging.getLogger(__name__)\n\n', content, count=1)

    # Replace print statements
    content = re.sub(r'print\((f?["\'][^"\']*?["\'])\)', r'logger.debug(\1)', content)

    # Replace dictionaries
    pattern1 = r"scoring: Dict\[str, Any\] = field\(default_factory=lambda: \{[^}]*?'score_interpretation': \{.*?\}\s*\}\)"
    replacement1 = r"""scoring: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'score_interpretation': CentralizedScoreConfig.get_default().thresholds
    })"""
    content = re.sub(pattern1, replacement1, content, flags=re.DOTALL)

    pattern2 = r"scoring = data\.get\('scoring', \{[^}]*?'score_interpretation': \{.*?\}\s*\}\)"
    replacement2 = r"""scoring = data.get('scoring', {
            'enabled': True,
            'score_interpretation': CentralizedScoreConfig.get_default().thresholds
        })"""
    content = re.sub(pattern2, replacement2, content, flags=re.DOTALL)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

process_wing_model()
logger.info("wing_model.py updated.")
