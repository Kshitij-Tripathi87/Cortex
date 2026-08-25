"""Program T2 — Evidence-Backed Answer Synthesis Builder.

Constructs rich, structured, and auditable operational answers:
- Executive Summary Finding
- Grounded Evidence Citations (Graph paths, telemetry, signals)
- Quantitative Metrics & Confidence Level
- Recommended Action & Link to Counterfactual Simulation
- Cryptographic SHA-256 Audit Seal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class EvidenceCitation:
    citation_id: str
    source_type: str  # "GRAPH_PATH" | "SIGNAL" | "METRIC" | "RECORD"
    label: str
    value: str
    deep_link: str  # e.g. "/workspace#graph?node=seller_01a00b8e99"


@dataclass
class EvidenceBackedAnswer:
    answer_id: str
    query_text: str
    summary_finding: str
    key_reasons: list[str]
    citations: list[EvidenceCitation]
    impacted_entities: list[str]
    confidence_score: float
    recommended_action: dict[str, Any]
    checksum_sha256: str
    answered_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer_id": self.answer_id,
            "query_text": self.query_text,
            "summary_finding": self.summary_finding,
            "key_reasons": self.key_reasons,
            "citations": [
                {
                    "citation_id": c.citation_id,
                    "source_type": c.source_type,
                    "label": c.label,
                    "value": c.value,
                    "deep_link": c.deep_link,
                }
                for c in self.citations
            ],
            "impacted_entities": self.impacted_entities,
            "confidence_score": round(self.confidence_score, 2),
            "recommended_action": self.recommended_action,
            "checksum_sha256": self.checksum_sha256,
            "answered_at": self.answered_at.isoformat(),
        }


class NexusAnswerBuilder:
    """Builds evidence-backed answers from graph and analytical scan results."""

    def build_answer(
        self,
        query: str,
        finding: str,
        reasons: list[str],
        citations: list[EvidenceCitation],
        impacted_entities: list[str],
        recommended_action: dict[str, Any],
        confidence: float = 0.94,
    ) -> EvidenceBackedAnswer:
        raw_payload = {
            "query": query,
            "finding": finding,
            "reasons": reasons,
            "impacted_entities": impacted_entities,
            "recommended_action": recommended_action,
        }
        checksum = hashlib.sha256(json.dumps(raw_payload, sort_keys=True).encode("utf-8")).hexdigest()

        return EvidenceBackedAnswer(
            answer_id=f"ans_{checksum[:8]}",
            query_text=query,
            summary_finding=finding,
            key_reasons=reasons,
            citations=citations,
            impacted_entities=impacted_entities,
            confidence_score=confidence,
            recommended_action=recommended_action,
            checksum_sha256=checksum,
        )
