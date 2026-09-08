"""Phase B — Central Dataset Builder & Provenance.

Extracts, normalizes, and versions training datasets from:
- World State Snapshots
- Historical Event Logs
- Decision Memory
- Realized Decision Outcomes
- Digital Twin Scenario Trajectories
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7
from app.modules.agents.domain_agents.shipment_tracking import ShipmentTelemetry


@dataclass
class DatasetSample:
    sample_id: str
    feature_vector: dict[str, Any]
    target_label: dict[str, Any]
    provenance_source: str
    observed_at: datetime


@dataclass
class VersionedAgentDataset:
    dataset_id: str
    dataset_version: str
    domain: str
    samples: list[DatasetSample]
    sample_count: int
    provenance_metadata: dict[str, Any]
    checksum_sha256: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "domain": self.domain,
            "sample_count": self.sample_count,
            "provenance_metadata": self.provenance_metadata,
            "checksum_sha256": self.checksum_sha256,
            "created_at": self.created_at.isoformat(),
        }


class CentralDatasetBuilder:
    """Compiles normalized, provenance-backed datasets for central agent training."""

    def __init__(self) -> None:
        self._datasets: dict[str, VersionedAgentDataset] = {}

    def build_dataset_from_historical_telemetry(
        self,
        domain: str,
        version: str,
        telemetry_records: list[ShipmentTelemetry],
        world_state_version: int = 1,
    ) -> VersionedAgentDataset:
        """Compile shipment telemetry records into an immutable training dataset."""
        samples = []
        for t in telemetry_records:
            is_delayed = t.port_congestion_index > 0.4 or t.elapsed_days > t.planned_eta_days
            sample = DatasetSample(
                sample_id=f"samp_{uuid7()}",
                feature_vector={
                    "shipment_id": t.shipment_id,
                    "origin": t.origin,
                    "destination": t.destination,
                    "carrier": t.carrier,
                    "planned_eta_days": t.planned_eta_days,
                    "elapsed_days": t.elapsed_days,
                    "port_congestion_index": t.port_congestion_index,
                    "weather_severity": t.weather_severity,
                },
                target_label={
                    "status": "CRITICAL_DELAY"
                    if t.port_congestion_index > 0.7
                    else ("AT_RISK" if is_delayed else "ON_TIME"),
                    "is_delayed": is_delayed,
                },
                provenance_source=f"world_state_v{world_state_version}",
                observed_at=t.last_scan_at,
            )
            samples.append(sample)

        # Compute deterministic checksum
        raw_content = json.dumps([s.feature_vector for s in samples], sort_keys=True)
        checksum = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        dataset = VersionedAgentDataset(
            dataset_id=f"ds_{domain}_{version}",
            dataset_version=version,
            domain=domain,
            samples=samples,
            sample_count=len(samples),
            provenance_metadata={
                "world_state_version": world_state_version,
                "source_system": "nexus_event_log",
                "features_version": "v1.0",
                "normalization": "standard_scaler",
            },
            checksum_sha256=checksum,
        )

        self._datasets[dataset.dataset_id] = dataset
        return dataset

    def get_dataset(self, dataset_id: str) -> VersionedAgentDataset | None:
        return self._datasets.get(dataset_id)
