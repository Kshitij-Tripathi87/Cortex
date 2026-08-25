with open('tests/test_propagation.py') as f:
    content = f.read()

old = '''def make_node_dto(node_id: str, entity_type: str, entity_id: str) -> NodeDTO:
    return NodeDTO(
        node_id=node_id,
        entity_type=entity_type,
        entity_id=entity_id,
        attributes={},
        first_seen_version=1,
        last_modified_version=1,
    )


def make_edge_dto(source: str, target: str, rel_type: str) -> EdgeDTO:
    return EdgeDTO(
        edge_id=f"{source}->{target}:{rel_type}",
        source_node_id=source,
        target_node_id=target,
        relationship_type=rel_type,
        attributes={},
        first_seen_version=1,
    )'''

new = '''def make_node_dto(node_id: str, entity_type: str, entity_id: str) -> NodeDTO:
    now = datetime.now(timezone.utc)
    return NodeDTO(
        node_id=node_id,
        workspace_id="ws-test",
        entity_type=entity_type,
        entity_id=entity_id,
        attributes={},
        first_seen_version=1,
        last_modified_version=1,
        valid_from=now,
        valid_to=None,
    )


def make_edge_dto(source: str, target: str, rel_type: str) -> EdgeDTO:
    now = datetime.now(timezone.utc)
    return EdgeDTO(
        edge_id=f"{source}->{target}:{rel_type}",
        workspace_id="ws-test",
        source_node_id=source,
        target_node_id=target,
        relationship_type=rel_type,
        attributes={},
        first_seen_version=1,
        last_modified_version=1,
        valid_from=now,
        valid_to=None,
    )'''

if old in content:
    content = content.replace(old, new)
    with open('tests/test_propagation.py', 'w') as f:
        f.write(content)
    print('Replaced successfully')
else:
    print('Pattern not found')
    # Debug: find the actual content
    idx = content.find('def make_node_dto')
    print(content[idx:idx+300])
