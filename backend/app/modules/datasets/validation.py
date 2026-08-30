"""Dataset Validation — Validation rules for dataset integrity."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.modules.datasets.models import SchemaVersion


class ValidationIssue(BaseModel):
    """A single validation issue."""

    severity: str  # "error", "warning", "info"
    code: str
    message: str
    file: str | None = None
    row: int | None = None
    column: str | None = None
    details: dict = {}

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


class ValidationResult(BaseModel):
    """Result of dataset validation."""

    valid: bool
    issues: list[ValidationIssue] = []
    file_checks: dict[str, bool] = {}
    total_rows: dict[str, int] = {}
    checksum_verified: bool = False
    schema_version: SchemaVersion
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.is_error]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


class DatasetValidator:
    """Validates dataset integrity and completeness."""

    # Required files per schema version
    REQUIRED_FILES = {
        SchemaVersion.V1: [
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
        ],
        SchemaVersion.V2: [
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
        ],
    }

    # Expected columns per file
    EXPECTED_COLUMNS = {
        "suppliers.csv": [
            "name",
            "country",
            "tier",
            "lead_time_days",
            "status",
            "risk_score",
        ],
        "components.csv": ["sku", "name", "category", "unit_of_measure"],
        "warehouses.csv": ["code", "name", "location", "capacity_units"],
        "factories.csv": ["code", "name", "location", "throughput_per_day"],
        "products.csv": [
            "sku",
            "name",
            "factory_code",
            "unit_price",
            "lead_time_days",
        ],
        "customers.csv": ["name", "country", "tier", "contract_value_annual"],
        "edges.csv": ["from_type", "from_ref", "to_type", "to_ref", "edge_type", "weight"],
        "inventory.csv": [
            "warehouse_code",
            "component_sku",
            "quantity",
            "safety_stock",
        ],
        "bom.csv": ["product_sku", "component_sku", "quantity_per_unit"],
        "orders.csv": [
            "customer_name",
            "product_sku",
            "quantity",
            "status",
            "order_date",
            "requested_delivery_date",
            "actual_delivery_date",
        ],
        "ground_truth.json": [],  # JSON structure validated separately
    }

    # Valid enum values
    VALID_TIERS = {"tier_1", "tier_2", "tier_3"}
    VALID_STATUSES = {"active", "disrupted", "disabled"}
    VALID_EDGE_TYPES = {
        "supplies",
        "stored_in",
        "consumes",
        "makes",
        "orders",
    }
    VALID_ORDER_STATUSES = {
        "pending",
        "confirmed",
        "in_production",
        "shipped",
        "delivered",
        "delayed",
    }
    VALID_SCENARIO_TYPES = {
        "supplier_failure",
        "supplier_delay",
        "demand_spike",
        "factory_outage",
        "logistics_disruption",
        "quality_issue",
    }

    def __init__(self, dataset_path: Path, schema_version: SchemaVersion = SchemaVersion.V2):
        self.dataset_path = Path(dataset_path)
        self.schema_version = schema_version
        self.result = ValidationResult(
            valid=True, schema_version=schema_version
        )

    def validate(self) -> ValidationResult:
        """Run all validation checks."""
        self._check_files_exist()
        self._check_file_structure()
        self._check_data_integrity()
        self._check_referential_integrity()
        self._check_ground_truth()

        self.result.valid = len(self.result.errors) == 0
        return self.result

    def _check_files_exist(self):
        """Check that all required files exist."""
        required = self.REQUIRED_FILES.get(self.schema_version, [])
        for filename in required:
            filepath = self.dataset_path / filename
            exists = filepath.exists()
            self.result.file_checks[filename] = exists
            if not exists:
                self.result.issues.append(
                    ValidationIssue(
                        severity="error",
                        code="FILE_MISSING",
                        message=f"Required file {filename} not found",
                        file=filename,
                    )
                )
            else:
                # Count rows
                try:
                    if filename.endswith(".csv"):
                        with open(self.dataset_path / filename) as f:
                            reader = csv.reader(f)
                            next(reader, None)
                            row_count = sum(1 for _ in reader)
                            self.result.total_rows[filename] = row_count
                    elif filename.endswith(".json"):
                        self.result.total_rows[filename] = 1
                except Exception as e:
                    self.result.issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="ROW_COUNT_FAILED",
                            message=f"Could not count rows in {filename}: {e}",
                            file=filename,
                        )
                    )

    def _check_file_structure(self):
        """Validate CSV structure and columns."""
        for filename, expected_cols in self.EXPECTED_COLUMNS.items():
            if filename == "ground_truth.json":
                continue
            filepath = self.dataset_path / filename
            if not filepath.exists():
                continue

            try:
                with open(filepath, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames is None:
                        self.result.issues.append(
                            ValidationIssue(
                                severity="error",
                                code="EMPTY_FILE",
                                message=f"File {filename} has no header",
                                file=filename,
                            )
                        )
                        continue

                    actual_cols = set(reader.fieldnames)
                    expected_set = set(expected_cols)
                    missing = expected_set - actual_cols
                    extra = actual_cols - expected_set

                    if missing:
                        self.result.issues.append(
                            ValidationIssue(
                                severity="error",
                                code="MISSING_COLUMNS",
                                message=f"Missing columns in {filename}: {missing}",
                                file=filename,
                            )
                        )
                    if extra:
                        self.result.issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="EXTRA_COLUMNS",
                                message=f"Extra columns in {filename}: {extra}",
                                file=filename,
                            )
                        )
            except Exception as e:
                self.result.issues.append(
                    ValidationIssue(
                        severity="error",
                        code="STRUCTURE_CHECK_FAILED",
                        message=f"Failed to validate structure of {filename}: {e}",
                        file=filename,
                    )
                )

    def _check_data_integrity(self):
        """Validate data values and constraints."""
        # Validate suppliers
        self._validate_suppliers()

        # Validate components
        self._validate_components()

        # Validate edges
        self._validate_edges()

        # Validate inventory
        self._validate_inventory()

        # Validate BOM
        self._validate_bom()

        # Validate orders
        self._validate_orders()

    def _validate_suppliers(self):
        filepath = self.dataset_path / "suppliers.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                if row.get("tier") not in self.VALID_TIERS:
                    self._add_issue(
                        "INVALID_TIER",
                        f"Invalid tier '{row.get('tier')}'",
                        "suppliers.csv",
                        i,
                        "tier",
                    )
                if row.get("status") not in self.VALID_STATUSES:
                    self._add_issue(
                        "INVALID_STATUS",
                        f"Invalid status '{row.get('status')}'",
                        "suppliers.csv",
                        i,
                        "status",
                    )
                try:
                    lead = int(row.get("lead_time_days", 0))
                    if lead < 0:
                        self._add_issue(
                            "INVALID_LEAD_TIME",
                            f"Negative lead_time_days: {lead}",
                            "suppliers.csv",
                            i,
                            "lead_time_days",
                        )
                except ValueError:
                    self._add_issue(
                        "INVALID_LEAD_TIME",
                        f"Non-integer lead_time_days: {row.get('lead_time_days')}",
                        "suppliers.csv",
                        i,
                        "lead_time_days",
                    )

    def _validate_components(self):
        filepath = self.dataset_path / "components.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                if not row.get("sku"):
                    self._add_issue(
                        "MISSING_SKU",
                        "Missing component SKU",
                        "components.csv",
                        i,
                        "sku",
                    )

    def _validate_edges(self):
        filepath = self.dataset_path / "edges.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                if row.get("edge_type") not in self.VALID_EDGE_TYPES:
                    self._add_issue(
                        "INVALID_EDGE_TYPE",
                        f"Invalid edge_type '{row.get('edge_type')}'",
                        "edges.csv",
                        i,
                        "edge_type",
                    )
                try:
                    weight = float(row.get("weight", 1.0))
                    if weight < 0:
                        self._add_issue(
                            "NEGATIVE_WEIGHT",
                            f"Negative edge weight: {weight}",
                            "edges.csv",
                            i,
                            "weight",
                        )
                except ValueError:
                    self._add_issue(
                        "INVALID_WEIGHT",
                        f"Non-numeric weight: {row.get('weight')}",
                        "edges.csv",
                        i,
                        "weight",
                    )

    def _validate_inventory(self):
        filepath = self.dataset_path / "inventory.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                for field in ["quantity", "safety_stock"]:
                    try:
                        val = int(row.get(field, 0))
                        if val < 0:
                            self._add_issue(
                                "NEGATIVE_INVENTORY",
                                f"Negative {field}: {val}",
                                "inventory.csv",
                                i,
                                field,
                            )
                    except ValueError:
                        self._add_issue(
                            "INVALID_INVENTORY",
                            f"Non-integer {field}: {row.get(field)}",
                            "inventory.csv",
                            i,
                            field,
                        )

    def _validate_bom(self):
        filepath = self.dataset_path / "bom.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                try:
                    qty = float(row.get("quantity_per_unit", 0))
                    if qty <= 0:
                        self._add_issue(
                            "INVALID_BOM_QTY",
                            f"Non-positive quantity_per_unit: {qty}",
                            "bom.csv",
                            i,
                            "quantity_per_unit",
                        )
                except ValueError:
                    self._add_issue(
                        "INVALID_BOM_QTY",
                        f"Non-numeric quantity_per_unit: {row.get('quantity_per_unit')}",
                        "bom.csv",
                        i,
                        "quantity_per_unit",
                    )

    def _validate_orders(self):
        filepath = self.dataset_path / "orders.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                if row.get("status") not in self.VALID_ORDER_STATUSES:
                    self._add_issue(
                        "INVALID_ORDER_STATUS",
                        f"Invalid order status '{row.get('status')}'",
                        "orders.csv",
                        i,
                        "status",
                    )
                try:
                    qty = int(row.get("quantity", 0))
                    if qty <= 0:
                        self._add_issue(
                            "INVALID_ORDER_QTY",
                            f"Non-positive order quantity: {row.get('quantity')}",
                            "orders.csv",
                            i,
                            "quantity",
                        )
                except ValueError:
                    self._add_issue(
                        "INVALID_ORDER_QTY",
                        f"Non-integer order quantity: {row.get('quantity')}",
                        "orders.csv",
                        i,
                        "quantity",
                    )

    def _check_referential_integrity(self):
        """Check that foreign key references are valid."""
        # Build lookup sets
        supplier_names = set()
        component_skus = set()
        warehouse_codes = set()
        factory_codes = set()
        product_skus = set()
        customer_names = set()

        # Load reference data
        for filename, key_col in [
            ("suppliers.csv", "name"),
            ("components.csv", "sku"),
            ("warehouses.csv", "code"),
            ("factories.csv", "code"),
            ("products.csv", "sku"),
            ("customers.csv", "name"),
        ]:
            filepath = self.dataset_path / filename
            if not filepath.exists():
                continue
            with open(filepath, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get(key_col):
                        if filename == "suppliers.csv":
                            supplier_names.add(row[key_col])
                        elif filename == "components.csv":
                            component_skus.add(row[key_col])
                        elif filename == "warehouses.csv":
                            warehouse_codes.add(row[key_col])
                        elif filename == "factories.csv":
                            factory_codes.add(row[key_col])
                        elif filename == "products.csv":
                            product_skus.add(row[key_col])
                        elif filename == "customers.csv":
                            customer_names.add(row[key_col])

        # Validate edges
        self._validate_edge_refs(
            supplier_names,
            component_skus,
            warehouse_codes,
            factory_codes,
            product_skus,
            customer_names,
        )

        # Validate inventory references
        self._validate_inventory_refs(warehouse_codes, component_skus)

        # Validate BOM references
        self._validate_bom_refs(product_skus, component_skus)

        # Validate orders references
        self._validate_order_refs(customer_names, product_skus)

        # Validate products references
        self._validate_product_refs(factory_codes)

    def _validate_edge_refs(self, suppliers, components, warehouses, factories, products, customers):
        filepath = self.dataset_path / "edges.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                from_type = row.get("from_type")
                from_ref = row.get("from_ref")
                to_type = row.get("to_type")
                to_ref = row.get("to_ref")

                if from_type == "supplier" and from_ref not in suppliers:
                    self._add_issue(
                        "INVALID_EDGE_REF",
                        f"Edge references unknown supplier: {from_ref}",
                        "edges.csv",
                        i,
                        "from_ref",
                    )
                elif from_type == "component" and from_ref not in components:
                    self._add_issue(
                        "INVALID_EDGE_REF",
                        f"Edge references unknown component: {from_ref}",
                        "edges.csv",
                        i,
                        "from_ref",
                    )
                elif from_type == "warehouse" and from_ref not in warehouses:
                    self._add_issue(
                        "INVALID_EDGE_REF",
                        f"Edge references unknown warehouse: {from_ref}",
                        "edges.csv",
                        i,
                        "from_ref",
                    )
                elif from_type == "factory" and from_ref not in factories:
                    self._add_issue(
                        "INVALID_EDGE_REF",
                        f"Edge references unknown factory: {from_ref}",
                        "edges.csv",
                        i,
                        "from_ref",
                    )
                elif from_type == "customer" and from_ref not in customers:
                    self._add_issue(
                        "INVALID_EDGE_REF",
                        f"Edge references unknown customer: {from_ref}",
                        "edges.csv",
                        i,
                        "from_ref",
                    )

                if to_type == "component" and to_ref not in components:
                    self._add_issue(
                        "INVALID_EDGE_REF",
                        f"Edge references unknown component: {to_ref}",
                        "edges.csv",
                        i,
                        "to_ref",
                    )
                elif to_type == "warehouse" and to_ref not in warehouses:
                    self._add_issue(
                        "INVALID_EDGE_REF",
                        f"Edge references unknown warehouse: {to_ref}",
                        "edges.csv",
                        i,
                        "to_ref",
                    )
                elif to_type == "product" and to_ref not in products:
                    self._add_issue(
                        "INVALID_EDGE_REF",
                        f"Edge references unknown product: {to_ref}",
                        "edges.csv",
                        i,
                        "to_ref",
                    )

    def _validate_inventory_refs(self, warehouses, components):
        filepath = self.dataset_path / "inventory.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                if row.get("warehouse_code") not in warehouses:
                    self._add_issue(
                        "INVALID_INV_REF",
                        f"Inventory references unknown warehouse: {row.get('warehouse_code')}",
                        "inventory.csv",
                        i,
                        "warehouse_code",
                    )
                if row.get("component_sku") not in components:
                    self._add_issue(
                        "INVALID_INV_REF",
                        f"Inventory references unknown component: {row.get('component_sku')}",
                        "inventory.csv",
                        i,
                        "component_sku",
                    )

    def _validate_bom_refs(self, products, components):
        filepath = self.dataset_path / "bom.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                if row.get("product_sku") not in products:
                    self._add_issue(
                        "INVALID_BOM_REF",
                        f"BOM references unknown product: {row.get('product_sku')}",
                        "bom.csv",
                        i,
                        "product_sku",
                    )
                if row.get("component_sku") not in components:
                    self._add_issue(
                        "INVALID_BOM_REF",
                        f"BOM references unknown component: {row.get('component_sku')}",
                        "bom.csv",
                        i,
                        "component_sku",
                    )

    def _validate_order_refs(self, customers, products):
        filepath = self.dataset_path / "orders.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                if row.get("customer_name") not in customers:
                    self._add_issue(
                        "INVALID_ORDER_REF",
                        f"Order references unknown customer: {row.get('customer_name')}",
                        "orders.csv",
                        i,
                        "customer_name",
                    )
                if row.get("product_sku") not in products:
                    self._add_issue(
                        "INVALID_ORDER_REF",
                        f"Order references unknown product: {row.get('product_sku')}",
                        "orders.csv",
                        i,
                        "product_sku",
                    )

    def _validate_product_refs(self, factories):
        filepath = self.dataset_path / "products.csv"
        if not filepath.exists():
            return

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                factory_code = row.get("factory_code")
                if factory_code and factory_code not in factories:
                    self._add_issue(
                        "INVALID_PRODUCT_REF",
                        f"Product references unknown factory: {factory_code}",
                        "products.csv",
                        i,
                        "factory_code",
                    )

    def _check_ground_truth(self):
        """Validate ground_truth.json structure."""
        if self.schema_version == SchemaVersion.V1:
            return

        filepath = self.dataset_path / "ground_truth.json"
        if not filepath.exists():
            self.result.issues.append(
                ValidationIssue(
                    severity="error",
                    code="MISSING_GROUND_TRUTH",
                    message="ground_truth.json required for schema v2",
                    file="ground_truth.json",
                )
            )
            return

        try:
            with open(filepath) as f:
                gt = json.load(f)

            # Check required fields
            required_fields = [
                "workspace_id",
                "size",
                "seed",
                "generated_at",
                "suppliers",
                "components",
                "warehouses",
                "factories",
                "products",
                "customers",
                "disruptions",
            ]
            for field in required_fields:
                if field not in gt:
                    self._add_issue(
                        "GT_MISSING_FIELD",
                        f"Ground truth missing required field: {field}",
                        "ground_truth.json",
                    )

            # Validate disruptions
            disruptions = gt.get("disruptions", [])
            for i, d in enumerate(disruptions):
                required_disruption = [
                    "scenario_id",
                    "supplier_name",
                    "disruption_type",
                    "severity",
                    "affected_components",
                    "affected_products",
                    "affected_warehouses",
                    "affected_orders",
                    "stockout_events",
                    "stockout_deadline_hours",
                    "revenue_risk_usd",
                    "confidence_overall",
                ]
                for field in required_disruption:
                    if field not in d:
                        self._add_issue(
                            "GT_DISRUPTION_MISSING_FIELD",
                            f"Disruption {i} missing field: {field}",
                            "ground_truth.json",
                        )

        except json.JSONDecodeError as e:
            self.result.issues.append(
                ValidationIssue(
                    severity="error",
                    code="GT_INVALID_JSON",
                    message=f"Invalid JSON in ground_truth.json: {e}",
                    file="ground_truth.json",
                )
            )

    def _add_issue(
        self,
        code: str,
        message: str,
        file: str | None = None,
        row: int | None = None,
        column: str | None = None,
        severity: str = "error",
    ):
        self.result.issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                file=file,
                row=row,
                column=column,
            )
        )


def validate_dataset(
    dataset_path: Path,
    schema_version: SchemaVersion = SchemaVersion.V2,
) -> ValidationResult:
    """Convenience function to validate a dataset."""
    validator = DatasetValidator(dataset_path, schema_version)
    return validator.validate()


def compute_checksums(dataset_path: Path) -> dict[str, str]:
    """Compute SHA256 checksums for all files in dataset."""
    checksums = {}
    for filepath in sorted(dataset_path.glob("*")):
        if filepath.is_file():
            hasher = hashlib.sha256()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            checksums[filepath.name] = hasher.hexdigest()
    return checksums


def compute_combined_checksum(checksums: dict[str, str]) -> str:
    """Compute combined checksum from individual file checksums."""
    combined = hashlib.sha256()
    for filename in sorted(checksums.keys()):
        combined.update(checksums[filename].encode())
    return combined.hexdigest()


__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "DatasetValidator",
    "validate_dataset",
    "compute_checksums",
    "compute_combined_checksum",
]
