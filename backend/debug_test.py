from app.modules.events.event_projection import inventory_var_id
from app.modules.world.state_projection import (
    apply_transition,
    create_initial_state,
    project_event_to_transition,
)
from app.modules.world.state_validation_helpers import make_event
from app.modules.world.world_models import StateVariable, StateVariableType

initial = create_initial_state(
    workspace_id="ws_1",
    world_id="world_1",
    graph_version=1,
    initial_variables={
        inventory_var_id("wh_001", "comp_042"): StateVariable(
            variable_id=inventory_var_id("wh_001", "comp_042"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="comp_042",
            entity_type="warehouse",
            value=100,
        ),
    },
)

events = [
    make_event(
        event_id=f"evt_{i}",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        event_type="inventory_changed",
        payload={"warehouse_id": "wh_001", "component_id": "comp_042", "quantity_change": 10},
    )
    for i in range(2)
]

state_a = initial
state_b = initial
for i, event in enumerate(events):
    t_a = project_event_to_transition(state_a, event)
    t_b = project_event_to_transition(state_b, event)
    print(f"Iter {i}: t_a.occurred_at={t_a.occurred_at}, t_b.occurred_at={t_b.occurred_at}")
    print(f"         t_a == t_b: {t_a == t_b}")
    state_a = apply_transition(state_a, t_a)
    state_b = apply_transition(state_b, t_b)
    var_key = inventory_var_id("wh_001", "comp_042")
    print(f"         state_a prov: {state_a.variables[var_key].value.provenance.observed_at}")
    print(f"         state_b prov: {state_b.variables[var_key].value.provenance.observed_at}")
