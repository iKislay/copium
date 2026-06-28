"""Transform modules for Copium SDK."""

from __future__ import annotations

import importlib.util
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Expose concrete types to static analysis while keeping runtime imports lazy.
    from copium.transforms.anchor_selector import (  # noqa: F401
        AnchorSelector,
        AnchorStrategy,
        AnchorWeights,
        DataPattern,
        calculate_information_score,
        compute_item_hash,
    )
    from copium.transforms.base import Transform  # noqa: F401
    from copium.transforms.cache_aligner import CacheAligner  # noqa: F401
    from copium.transforms.code_compressor import (  # noqa: F401
        CodeAwareCompressor,
        CodeCompressionResult,
        CodeCompressorConfig,
        CodeLanguage,
        DocstringMode,
        detect_language,
        is_tree_sitter_available,
    )
    from copium.transforms.content_detector import (  # noqa: F401
        ContentType,
        DetectionResult,
        detect_content_type,
    )
    from copium.transforms.content_router import (  # noqa: F401
        CompressionStrategy,
        ContentRouter,
        ContentRouterConfig,
        RouterCompressionResult,
    )
    from copium.transforms.diff_compressor import (  # noqa: F401
        DiffCompressionResult,
        DiffCompressor,
        DiffCompressorConfig,
    )
    from copium.transforms.differential_response import (  # noqa: F401
        DifferentialResponse,
        DifferentialResponseConfig,
    )
    from copium.transforms.html_extractor import (  # noqa: F401
        HTMLExtractionResult,
        HTMLExtractor,
        HTMLExtractorConfig,
        is_html_content,
    )
    from copium.transforms.log_compressor import (  # noqa: F401
        LogCompressionResult,
        LogCompressor,
        LogCompressorConfig,
    )
    from copium.transforms.output_compressor import (  # noqa: F401
        OutputCompressor,
        OutputCompressorConfig,
    )
    from copium.transforms.model_router import (  # noqa: F401
        ModelRouter,
        ModelRouterConfig,
    )
    from copium.transforms.auto_batch import (  # noqa: F401
        AutoBatcher,
        AutoBatchConfig,
    )
    from copium.transforms.chain_of_draft import (  # noqa: F401
        ChainOfDraftOutput,
    )
    from copium.transforms.provider_cache import (  # noqa: F401
        ProviderCacheComposition,
        ProviderCacheConfig,
    )
    from copium.transforms.pipeline import TransformPipeline  # noqa: F401
    from copium.transforms.ansi_remover import (  # noqa: F401
        ANSIRemover,
        ANSIRemoverConfig,
        strip_ansi,
        strip_spinners,
    )
    from copium.transforms.schema_compressor import (  # noqa: F401
        SchemaCompressionConfig,
        compress_tool_schemas,
        compress_tools_in_body,
    )
    from copium.transforms.search_compressor import (  # noqa: F401
        SearchCompressionResult,
        SearchCompressor,
        SearchCompressorConfig,
    )
    from copium.transforms.smart_crusher import SmartCrusher, SmartCrusherConfig  # noqa: F401
    from copium.transforms.tabular_ingest import (  # noqa: F401
        TabularCompressionResult,
        TabularCompressor,
        TabularCompressorConfig,
    )
    from copium.transforms.toon_encoder import (  # noqa: F401
        TOONEncoder,
        TOONConfig,
    )
    from copium.transforms.session_dedup import (  # noqa: F401
        SessionDedup,
        SessionDedupConfig,
    )
    from copium.transforms.error_compressor import (  # noqa: F401
        ErrorCompressor,
        ErrorCompressorConfig,
    )
    from copium.transforms.kv_cache_aware import (  # noqa: F401
        KVCacheAwareTransform,
    )
    from copium.transforms.paging_transform import (  # noqa: F401
        PagingTransform,
    )
    from copium.transforms.quality_gate import (  # noqa: F401
        QualityGate,
        QualityGateResult,
    )
    from copium.transforms.file_read_compressor import (  # noqa: F401
        FileReadCompressor,
        FileReadCompressorConfig,
        FileReadCompressionResult,
    )

_HTML_EXTRACTOR_AVAILABLE = importlib.util.find_spec("trafilatura") is not None

__all__ = [
    # Base
    "Transform",
    "TransformPipeline",
    # Anchor selection
    "AnchorSelector",
    "AnchorStrategy",
    "AnchorWeights",
    "DataPattern",
    "calculate_information_score",
    "compute_item_hash",
    # JSON compression
    "SmartCrusher",
    "SmartCrusherConfig",
    # Text compression (coding tasks)
    "ContentType",
    "DetectionResult",
    "detect_content_type",
    "SearchCompressor",
    "SearchCompressorConfig",
    "SearchCompressionResult",
    "LogCompressor",
    "LogCompressorConfig",
    "LogCompressionResult",
    "TabularCompressor",
    "TabularCompressorConfig",
    "TabularCompressionResult",
    "DiffCompressor",
    "DiffCompressorConfig",
    "DiffCompressionResult",
    "DifferentialResponse",
    "DifferentialResponseConfig",
    # Code-aware compression (AST-based)
    "CodeAwareCompressor",
    "CodeCompressorConfig",
    "CodeCompressionResult",
    "CodeLanguage",
    "DocstringMode",
    "detect_language",
    "is_tree_sitter_available",
    # Content routing
    "ContentRouter",
    "ContentRouterConfig",
    "RouterCompressionResult",
    "CompressionStrategy",
    "SchemaCompressionConfig",
    "compress_tool_schemas",
    "compress_tools_in_body",
    # Other transforms
    "CacheAligner",
    "OutputCompressor",
    "OutputCompressorConfig",
    # Session deduplication
    "SessionDedup",
    "SessionDedupConfig",
    # Error-driven compression
    "ErrorCompressor",
    "ErrorCompressorConfig",
    # KV cache-aware compression
    "KVCacheAwareTransform",
    # Cold/hot context paging
    "PagingTransform",
    # Quality gate
    "QualityGate",
    "QualityGateResult",
    # File read compression
    "FileReadCompressor",
    "FileReadCompressorConfig",
    "FileReadCompressionResult",
    # Model routing
    "ModelRouter",
    "ModelRouterConfig",
    # Auto-batching
    "AutoBatcher",
    "AutoBatchConfig",
    # Chain-of-draft output control
    "ChainOfDraftOutput",
    # Provider-cache composition
    "ProviderCacheComposition",
    "ProviderCacheConfig",
    # HTML extraction (optional)
    "_HTML_EXTRACTOR_AVAILABLE",
]

# Conditionally add HTML extractor exports
if _HTML_EXTRACTOR_AVAILABLE:
    __all__.extend(
        [
            "HTMLExtractor",
            "HTMLExtractorConfig",
            "HTMLExtractionResult",
            "is_html_content",
        ]
    )

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Base
    "Transform": ("copium.transforms.base", "Transform"),
    "TransformPipeline": ("copium.transforms.pipeline", "TransformPipeline"),
    # Anchor selection
    "AnchorSelector": ("copium.transforms.anchor_selector", "AnchorSelector"),
    "AnchorStrategy": ("copium.transforms.anchor_selector", "AnchorStrategy"),
    "AnchorWeights": ("copium.transforms.anchor_selector", "AnchorWeights"),
    "DataPattern": ("copium.transforms.anchor_selector", "DataPattern"),
    "calculate_information_score": (
        "copium.transforms.anchor_selector",
        "calculate_information_score",
    ),
    "compute_item_hash": ("copium.transforms.anchor_selector", "compute_item_hash"),
    # JSON compression
    "SmartCrusher": ("copium.transforms.smart_crusher", "SmartCrusher"),
    "SmartCrusherConfig": ("copium.transforms.smart_crusher", "SmartCrusherConfig"),
    # Text compression (coding tasks)
    "ContentType": ("copium.transforms.content_detector", "ContentType"),
    "DetectionResult": ("copium.transforms.content_detector", "DetectionResult"),
    "detect_content_type": ("copium.transforms.content_detector", "detect_content_type"),
    "SearchCompressor": ("copium.transforms.search_compressor", "SearchCompressor"),
    "SearchCompressorConfig": (
        "copium.transforms.search_compressor",
        "SearchCompressorConfig",
    ),
    "SearchCompressionResult": (
        "copium.transforms.search_compressor",
        "SearchCompressionResult",
    ),
    "LogCompressor": ("copium.transforms.log_compressor", "LogCompressor"),
    "LogCompressorConfig": ("copium.transforms.log_compressor", "LogCompressorConfig"),
    "LogCompressionResult": ("copium.transforms.log_compressor", "LogCompressionResult"),
    "TabularCompressor": ("copium.transforms.tabular_ingest", "TabularCompressor"),
    "TabularCompressorConfig": (
        "copium.transforms.tabular_ingest",
        "TabularCompressorConfig",
    ),
    "TabularCompressionResult": (
        "copium.transforms.tabular_ingest",
        "TabularCompressionResult",
    ),
    "TOONEncoder": ("copium.transforms.toon_encoder", "TOONEncoder"),
    "TOONConfig": ("copium.transforms.toon_encoder", "TOONConfig"),
    "DiffCompressor": ("copium.transforms.diff_compressor", "DiffCompressor"),
    "DiffCompressorConfig": ("copium.transforms.diff_compressor", "DiffCompressorConfig"),
    "DiffCompressionResult": (
        "copium.transforms.diff_compressor",
        "DiffCompressionResult",
    ),
    "DifferentialResponse": ("copium.transforms.differential_response", "DifferentialResponse"),
    "DifferentialResponseConfig": (
        "copium.transforms.differential_response",
        "DifferentialResponseConfig",
    ),
    # Code-aware compression (AST-based)
    "CodeAwareCompressor": ("copium.transforms.code_compressor", "CodeAwareCompressor"),
    "CodeCompressorConfig": ("copium.transforms.code_compressor", "CodeCompressorConfig"),
    "CodeCompressionResult": (
        "copium.transforms.code_compressor",
        "CodeCompressionResult",
    ),
    "CodeLanguage": ("copium.transforms.code_compressor", "CodeLanguage"),
    "DocstringMode": ("copium.transforms.code_compressor", "DocstringMode"),
    "detect_language": ("copium.transforms.code_compressor", "detect_language"),
    "is_tree_sitter_available": (
        "copium.transforms.code_compressor",
        "is_tree_sitter_available",
    ),
    # Content routing
    "ContentRouter": ("copium.transforms.content_router", "ContentRouter"),
    "ContentRouterConfig": ("copium.transforms.content_router", "ContentRouterConfig"),
    "RouterCompressionResult": (
        "copium.transforms.content_router",
        "RouterCompressionResult",
    ),
    "CompressionStrategy": ("copium.transforms.content_router", "CompressionStrategy"),
    "SchemaCompressionConfig": ("copium.transforms.schema_compressor", "SchemaCompressionConfig"),
    "compress_tool_schemas": ("copium.transforms.schema_compressor", "compress_tool_schemas"),
    "compress_tools_in_body": ("copium.transforms.schema_compressor", "compress_tools_in_body"),
    # Other transforms
    "CacheAligner": ("copium.transforms.cache_aligner", "CacheAligner"),
    "OutputCompressor": ("copium.transforms.output_compressor", "OutputCompressor"),
    "OutputCompressorConfig": ("copium.transforms.output_compressor", "OutputCompressorConfig"),
    # Session deduplication
    "SessionDedup": ("copium.transforms.session_dedup", "SessionDedup"),
    "SessionDedupConfig": ("copium.transforms.session_dedup", "SessionDedupConfig"),
    # Error-driven compression
    "ErrorCompressor": ("copium.transforms.error_compressor", "ErrorCompressor"),
    "ErrorCompressorConfig": ("copium.transforms.error_compressor", "ErrorCompressorConfig"),
    # KV cache-aware compression
    "KVCacheAwareTransform": ("copium.transforms.kv_cache_aware", "KVCacheAwareTransform"),
    # Cold/hot context paging
    "PagingTransform": ("copium.transforms.paging_transform", "PagingTransform"),
    # Quality gate
    "QualityGate": ("copium.transforms.quality_gate", "QualityGate"),
    "QualityGateResult": ("copium.transforms.quality_gate", "QualityGateResult"),
    "FileReadCompressor": ("copium.transforms.file_read_compressor", "FileReadCompressor"),
    "FileReadCompressorConfig": ("copium.transforms.file_read_compressor", "FileReadCompressorConfig"),
    "FileReadCompressionResult": ("copium.transforms.file_read_compressor", "FileReadCompressionResult"),
    # Model routing
    "ModelRouter": ("copium.transforms.model_router", "ModelRouter"),
    "ModelRouterConfig": ("copium.transforms.model_router", "ModelRouterConfig"),
    # Auto-batching
    "AutoBatcher": ("copium.transforms.auto_batch", "AutoBatcher"),
    "AutoBatchConfig": ("copium.transforms.auto_batch", "AutoBatchConfig"),
    # Chain-of-draft output control
    "ChainOfDraftOutput": ("copium.transforms.chain_of_draft", "ChainOfDraftOutput"),
    # Provider-cache composition
    "ProviderCacheComposition": ("copium.transforms.provider_cache", "ProviderCacheComposition"),
    "ProviderCacheConfig": ("copium.transforms.provider_cache", "ProviderCacheConfig"),
    # HTML extraction (optional dependency - requires trafilatura)
    "HTMLExtractor": ("copium.transforms.html_extractor", "HTMLExtractor"),
    "HTMLExtractorConfig": ("copium.transforms.html_extractor", "HTMLExtractorConfig"),
    "HTMLExtractionResult": ("copium.transforms.html_extractor", "HTMLExtractionResult"),
    "is_html_content": ("copium.transforms.html_extractor", "is_html_content"),
}


def __getattr__(name: str) -> object:
    if name == "__path__":
        raise AttributeError(name)
    if name == "_HTML_EXTRACTOR_AVAILABLE":
        return _HTML_EXTRACTOR_AVAILABLE

    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
