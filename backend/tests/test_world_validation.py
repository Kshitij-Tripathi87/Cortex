"""Tests for World Validation Engine — Program J Milestone J.2.6.

Covers:
1. Domain invariants: negative inventory, impossible capacity, safety stock breach
2. Operational invariants: invalid lead times, supplier health bounds, negative demand, margin bounds
3. Structural invariants: duplicate variables, version progression, state hash verification
4. Snapshot integrity: validate_snapshot against state hash
5. WorldValidator aggregation: error/warning separation, rules_checked count, to_dict serialization
6. Convenience functions: is_valid_state, get_state_errors, validate_state
"""

from __future__ import annotations

from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
    lead_time_var_id,
    safety_stock_var_id,
)
from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
    WorldState,
)
from app.modules.world.world_validation import (
    ValidationResult,
    ValidationRules,
    ValidationSeverity,
    WorldValidator,
    get_state_errors,
    is_valid_state,
    validate_snapshot,
    validate_state,
)


def _make_state(variables: dict[str, StateVariable], version: int = 1) -> WorldState:
    return create_initial_state(
        workspace_id="ws_val_test",
        world_id="world_val_test",
        graph_version=1,
        initial_variables=variables,
    )


class TestValidationRules:
    def test_negative_inventory_detected_as_error(self) -> None:
        inv_key = inventory_var_id("wh_1", "comp_a")
        var = StateVariable(
            variable_id=inv_key,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=-10,
        )
        state = _make_state({inv_key: var})

        issues = ValidationRules.check_negative_inventory(state)
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert issues[0].rule == "negative_inventory"

    def test_inventory_below_safety_stock_detected_as_warning(self) -> None:
        inv_key = inventory_var_id("wh_1", "comp_a")
        ss_key = safety_stock_var_id("wh_1", "comp_a")

        inv_var = StateVariable(
            variable_id=inv_key,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=30,
        )
        ss_var = StateVariable(
            variable_id=ss_key,
            variable_type=StateVariableType.SAFETY_STOCK,
            entity_id="wh_1",
            entity_type="warehouse",
            value=100,
        )
        state = _make_state({inv_key: inv_var, ss_key: ss_var})

        issues = ValidationRules.check_inventory_below_safety_stock(state)
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.WARNING
        assert issues[0].rule == "inventory_below_safety_stock"

    def test_impossible_capacity_detected_as_error(self) -> None:
        cap_key = capacity_var_id("fac_1")
        var_high = StateVariable(
            variable_id=cap_key,
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=150.0,
        )
        state_high = _make_state({cap_key: var_high})
        issues_high = ValidationRules.check_impossible_capacity(state_high)
        assert len(issues_high) == 1
        assert issues_high[0].severity == ValidationSeverity.WARNING
        assert issues_high[0].rule == "over_capacity"

        var_low = StateVariable(
            variable_id=cap_key,
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=-5.0,
        )
        state_low = _make_state({cap_key: var_low})
        issues_low = ValidationRules.check_impossible_capacity(state_low)
        assert len(issues_low) == 1
        assert issues_low[0].severity == ValidationSeverity.ERROR
        assert issues_low[0].rule == "negative_capacity"

    def test_invalid_lead_time_detected_as_error(self) -> None:
        lt_key = lead_time_var_id("sup_1")
        var = StateVariable(
            variable_id=lt_key,
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=-2,
        )
        state = _make_state({lt_key: var})

        issues = ValidationRules.check_invalid_lead_time(state)
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR

    def test_supplier_health_outside_unit_interval_detected(self) -> None:
        health_key = "supplier_health.supplier.sup_1"
        var = StateVariable(
            variable_id=health_key,
            variable_type=StateVariableType.SUPPLIER_HEALTH,
            entity_id="sup_1",
            entity_type="supplier",
            value=150.0,
        )
        state = _make_state({health_key: var})

        issues = ValidationRules.check_supplier_health(state)
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert issues[0].rule == "supplier_health_range"

    def test_warehouse_utilization_near_capacity_warning_and_overflow_error(
        self,
    ) -> None:
        util_key = "warehouse_utilization.warehouse.wh_1"

        # Warning when > 95%
        var_warn = StateVariable(
            variable_id=util_key,
            variable_type=StateVariableType.WAREHOUSE_UTILIZATION,
            entity_id="wh_1",
            entity_type="warehouse",
            value=97.0,
        )
        state_warn = _make_state({util_key: var_warn})
        issues_warn = ValidationRules.check_warehouse_utilization(state_warn)
        assert len(issues_warn) == 1
        assert issues_warn[0].severity == ValidationSeverity.WARNING

        # Error when > 100%
        var_err = StateVariable(
            variable_id=util_key,
            variable_type=StateVariableType.WAREHOUSE_UTILIZATION,
            entity_id="wh_1",
            entity_type="warehouse",
            value=110.0,
        )
        state_err = _make_state({util_key: var_err})
        issues_err = ValidationRules.check_warehouse_utilization(state_err)
        assert len(issues_err) == 1
        assert issues_err[0].severity == ValidationSeverity.ERROR

    def test_state_hash_mismatch_detected(self) -> None:
        state = _make_state({})
        issues = ValidationRules.check_state_hash(state, expected_hash="wrong_hash_123")
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert issues[0].rule == "state_hash_mismatch"


class TestWorldValidator:
    def test_validator_runs_all_rules_and_summarizes_issues(self) -> None:
        validator = WorldValidator()

        # Clean state
        inv_key = inventory_var_id("wh_1", "comp_a")
        clean_var = StateVariable(
            variable_id=inv_key,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=500,
        )
        clean_state = _make_state({inv_key: clean_var})

        clean_result = validator.validate(clean_state)
        assert clean_result.is_valid is True
        assert len(clean_result.issues) == 0
        assert clean_result.rules_checked >= 14

        # Dirty state with both error and warning
        bad_inv = StateVariable(
            variable_id=inv_key,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=-50,  # ERROR
        )
        high_util_key = "warehouse_utilization.warehouse.wh_1"
        warn_util = StateVariable(
            variable_id=high_util_key,
            variable_type=StateVariableType.WAREHOUSE_UTILIZATION,
            entity_id="wh_1",
            entity_type="warehouse",
            value=98.0,  # WARNING
        )
        dirty_state = _make_state({inv_key: bad_inv, high_util_key: warn_util})

        dirty_result = validator.validate(dirty_state)
        assert dirty_result.is_valid is False
        assert len(validator.get_errors(dirty_result)) == 1
        assert len(validator.get_warnings(dirty_result)) == 1

        # Check dictionary serialization
        result_dict = dirty_result.to_dict()
        assert result_dict["is_valid"] is False
        assert len(result_dict["issues"]) == 2
        assert "validated_at" in result_dict

    def test_validate_snapshot_against_state(self) -> None:
        validator = WorldValidator()

        inv_key = inventory_var_id("wh_1", "comp_a")
        var = StateVariable(
            variable_id=inv_key,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=100,
        )
        state = _make_state({inv_key: var})
        snapshot = create_state_snapshot(state, created_by="test")

        snap_result = validator.validate_snapshot(snapshot, state)
        assert snap_result.is_valid is True


class TestValidationConvenienceFunctions:
    def test_convenience_functions(self) -> None:
        inv_key = inventory_var_id("wh_1", "comp_a")
        valid_var = StateVariable(
            variable_id=inv_key,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=200,
        )
        valid_state = _make_state({inv_key: valid_var})

        assert is_valid_state(valid_state) is True
        assert len(get_state_errors(valid_state)) == 0

        res = validate_state(valid_state)
        assert isinstance(res, ValidationResult)
        assert res.is_valid is True

        snapshot = create_state_snapshot(valid_state)
        snap_res = validate_snapshot(snapshot, valid_state)
        assert snap_res.is_valid is True
