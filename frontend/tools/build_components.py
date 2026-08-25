import base64, sys
from pathlib import Path

ROOT = Path(r"C:\Users\21330\Documents\Cortex\frontend\src\features\morning-brief")
FILES = {}

CB = chr(125)  # closing brace

FILES["CriticalAlertCard.tsx"] = (
    'import type { DecisionBrief } from "../api/client";\n'
    'import { severityColor, severityFromScore, severityHeader, deadlineLabel, totalAffected } from "../format";\n'
    '\n'
    'interface CriticalAlertCardProps {\n'
    '  brief: DecisionBrief;\n'
    CB + '\n'  # just }, end interface
    '\n'
    'export function CriticalAlertCard({ brief }: CriticalAlertCardProps) {\n'
    '  const severity = severityFromScore(brief.business_impact.overall_score);\n'
    '  const tone = severityColor(severity);\n'
    '  const headline = severityHeader(severity);\n'
    '  const total = totalAffected(brief);\n'
    '\n'
    '  return (\n'
    # ensure curly brace in template literal is safe: use `}` via chr
)

# TEMPLATES for each brace: use a placeholder like __CB__ and replace
# That's the cleanest approach.

# Let me write the full content with __CB__ as placeholder, then replace.
pass