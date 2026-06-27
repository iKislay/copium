"""Code-aware compression pipeline - beats ContextCrumb.

This sub-package provides multi-stage, language-specific code compression
that outperforms ContextCrumb's single-model ONNX approach by using:

1. AST-level parsing (not token-level) via tree-sitter
2. Importance classification (Critical/High/Medium/Low)
3. Language-specific transform strategies
4. CCR integration for reversible compression
5. Hybrid compression modes

Reference: plans/06-beat-contextcrumb.md
"""

from copium.transforms.code_aware.classifier import (
    ImportanceClassifier,
    ImportanceLevel,
    SymbolImportance,
)
from copium.transforms.code_aware.languages import (
    LanguageStrategy,
    PythonStrategy,
    JavaScriptStrategy,
    RustStrategy,
    GenericStrategy,
)
from copium.transforms.code_aware.compressor import CodeAwarePipeline

__all__ = [
    "CodeAwarePipeline",
    "ImportanceClassifier",
    "ImportanceLevel",
    "SymbolImportance",
    "LanguageStrategy",
    "PythonStrategy",
    "JavaScriptStrategy",
    "RustStrategy",
    "GenericStrategy",
]
