"""Dataset Exports — Export datasets in various formats."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

try:
    import pyarrow as pa
    import pyarrow.parquet as pq

    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False

try:
    import pyarrow.feather as feather

    FEATHER_AVAILABLE = True
except ImportError:
    FEATHER_AVAILABLE = False


class DatasetExporter:
    """Exports dataset in various formats."""

    def __init__(self, dataset_path: Path):
        self.dataset_path = Path(dataset_path)

    def export(
        self,
        format: str = "json",
        include_ground_truth: bool = True,
        include_statistics: bool = True,
        output_path: Path | None = None,
    ) -> Path | bytes:
        """Export dataset in specified format."""
        if format == "json":
            return self._export_json(include_ground_truth, include_statistics, output_path)
        elif format == "csv":
            return self._export_csv(output_path)
        elif format == "parquet":
            if not PARQUET_AVAILABLE:
                raise RuntimeError("pyarrow not installed. Install with: pip install pyarrow")
            return self._export_parquet(output_path)
        elif format == "arrow" or format == "feather":
            if not FEATHER_AVAILABLE:
                raise RuntimeError(
                    "pyarrow/feather not installed. Install with: pip install pyarrow"
                )
            return self._export_feather(output_path)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _export_json(
        self,
        include_ground_truth: bool,
        include_statistics: bool,
        output_path: Path | None,
    ) -> Path | bytes:
        """Export as JSON bundle."""
        data = {
            "metadata": {
                "exported_at": datetime.now(UTC).isoformat(),
                "source_path": str(self.dataset_path),
            },
            "datasets": {},
        }

        # Load all CSVs
        csv_files = {
            "suppliers": "suppliers.csv",
            "components": "components.csv",
            "warehouses": "warehouses.csv",
            "factories": "factories.csv",
            "products": "products.csv",
            "customers": "customers.csv",
            "edges": "edges.csv",
            "inventory": "inventory.csv",
            "bom": "bom.csv",
            "orders": "orders.csv",
        }

        for key, filename in csv_files.items():
            filepath = self.dataset_path / filename
            if filepath.exists():
                with open(filepath, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    data[key] = list(reader)
            else:
                data[key] = []

        data["datasets"] = {k: v for k, v in data.items() if k in csv_files}

        if include_ground_truth:
            gt_path = self.dataset_path / "ground_truth.json"
            if gt_path.exists():
                with open(gt_path) as f:
                    data["ground_truth"] = json.load(f)

        if include_statistics:
            from .statistics import compute_statistics

            stats = compute_statistics(self.dataset_path)
            data["statistics"] = stats.model_dump()

        json_bytes = json.dumps(data, indent=2, default=str).encode()

        if output_path:
            output_path = Path(output_path)
            output_path.write_bytes(json_bytes)
            return output_path
        return json_bytes

    def _export_csv(self, output_path: Path | None) -> Path | bytes:
        """Export as ZIP of CSV files."""
        import io
        import zipfile

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            csv_files = [
                "suppliers.csv",
                "components.csv",
                "warehouses.csv",
                "factories.csv",
                "products.csv",
                "customers.csv",
                "edges.csv",
                "inventory.csv",
                "bom.csv",
                "orders.csv",
                "ground_truth.json",
            ]
            for filename in csv_files:
                filepath = self.dataset_path / filename
                if filepath.exists():
                    zf.write(filepath, filename)

        if output_path:
            output_path = Path(output_path)
            output_path.write_bytes(zip_buffer.getvalue())
            return output_path
        return zip_buffer.getvalue()

    def _export_parquet(self, output_path: Path | None) -> Path | bytes:
        """Export as Parquet files."""
        import io

        tables = {}
        csv_files = {
            "suppliers": "suppliers.csv",
            "components": "components.csv",
            "warehouses": "warehouses.csv",
            "factories": "factories.csv",
            "products": "products.csv",
            "customers": "customers.csv",
            "edges": "edges.csv",
            "inventory": "inventory.csv",
            "bom": "bom.csv",
            "orders": "orders.csv",
        }

        for key, filename in csv_files.items():
            filepath = self.dataset_path / filename
            if filepath.exists():
                df = self._csv_to_dataframe(filepath)
                tables[key] = pa.Table.from_pandas(df)

        if output_path:
            output_path = Path(output_path)
            output_path.mkdir(parents=True, exist_ok=True)
            for name, table in tables.items():
                pq.write_table(table, output_path / f"{name}.parquet")
            return output_path
        else:
            # Return as bytes (zip of parquet files)
            import zipfile

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, table in tables.items():
                    buf = io.BytesIO()
                    pq.write_table(table, buf)
                    buf.seek(0)
                    zf.writestr(f"{name}.parquet", buf.read())
            return zip_buffer.getvalue()

    def _export_feather(self, output_path: Path | None) -> Path | bytes:
        """Export as Feather (Arrow) format."""
        import io

        tables = {}
        csv_files = {
            "suppliers": "suppliers.csv",
            "components": "components.csv",
            "warehouses": "warehouses.csv",
            "factories": "factories.csv",
            "products": "products.csv",
            "customers": "customers.csv",
            "edges": "edges.csv",
            "inventory": "inventory.csv",
            "bom": "bom.csv",
            "orders": "orders.csv",
        }

        for key, filename in csv_files.items():
            filepath = self.dataset_path / filename
            if filepath.exists():
                df = self._csv_to_dataframe(filepath)
                tables[key] = pa.Table.from_pandas(df)

        if output_path:
            output_path = Path(output_path)
            output_path.mkdir(parents=True, exist_ok=True)
            for name, table in tables.items():
                feather.write_feather(table, output_path / f"{name}.feather")
            return output_path
        else:
            import zipfile

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, table in tables.items():
                    buf = io.BytesIO()
                    feather.write_feather(table, buf)
                    buf.seek(0)
                    zf.writestr(f"{name}.feather", buf.read())
            return zip_buffer.getvalue()

    def _csv_to_dataframe(self, filepath: Path):
        """Convert CSV to pandas DataFrame with proper types."""
        import pandas as pd

        df = pd.read_csv(filepath, encoding="utf-8-sig")

        # Type conversions
        if "quantity" in df.columns:
            df["quantity"] = (
                pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype("int64")
            )
        if "safety_stock" in df.columns:
            df["safety_stock"] = (
                pd.to_numeric(df["safety_stock"], errors="coerce").fillna(0).astype("int64")
            )
        if "quantity_per_unit" in df.columns:
            df["quantity_per_unit"] = pd.to_numeric(df["quantity_per_unit"], errors="coerce")
        if "unit_price" in df.columns:
            df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
        if "lead_time_days" in df.columns:
            df["lead_time_days"] = (
                pd.to_numeric(df["lead_time_days"], errors="coerce").fillna(0).astype("int64")
            )
        if "throughput_per_day" in df.columns:
            df["throughput_per_day"] = (
                pd.to_numeric(df["throughput_per_day"], errors="coerce").fillna(0).astype("int64")
            )
        if "weight" in df.columns:
            df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
        if "risk_score" in df.columns:
            df["risk_score"] = pd.to_numeric(df["risk_score"], errors="coerce")
        if "contract_value_annual" in df.columns:
            df["contract_value_annual"] = pd.to_numeric(
                df["contract_value_annual"], errors="coerce"
            )

        return df


def export_dataset(
    dataset_path: Path,
    format: str = "json",
    include_ground_truth: bool = True,
    include_statistics: bool = True,
    output_path: Path | None = None,
) -> Path | bytes:
    """Convenience function to export a dataset."""
    exporter = DatasetExporter(dataset_path)
    return exporter.export(format, include_ground_truth, include_statistics, output_path)


__all__ = ["DatasetExporter", "export_dataset"]
