"""How the Ask box reads a question, and where the built-in assistant sends it.

`parse_question` works on the words alone. The classifier then routes a
question about the workspace's own records to a read-only tool, while keeping
every pinned behaviour for operational intents and for text it cannot read.
"""

from __future__ import annotations

import pytest

from app.modules.nexus_spine.p0_migration.question_focus import (
    TOPIC_CHANGES,
    TOPIC_DELAYS,
    TOPIC_ENTITIES,
    TOPIC_EXPOSURE,
    TOPIC_INTAKE,
    TOPIC_OVERVIEW,
    TOPIC_SHORTAGES,
    parse_question,
)
from app.modules.nexus_spine.p0_migration.vanessa_pipeline import (
    INTENT_TO_TOOL,
    DeterministicLLMAdapter,
    IntentType,
)


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("What changed?", TOPIC_CHANGES),
        ("What's new since the last upload", TOPIC_CHANGES),
        ("Which orders are exposed?", TOPIC_EXPOSURE),
        ("What is at risk if S-101 slips again?", TOPIC_EXPOSURE),
        ("Which purchase orders are delayed?", TOPIC_DELAYS),
        ("Which supplier is late?", TOPIC_DELAYS),
        ("What is below safety stock?", TOPIC_SHORTAGES),
        ("Are we running low on anything", TOPIC_SHORTAGES),
        ("Is my data ready?", TOPIC_INTAKE),
        ("Which files have I uploaded?", TOPIC_INTAKE),
        ("Give me a summary", TOPIC_OVERVIEW),
        ("What is in my graph?", TOPIC_OVERVIEW),
        ("Which suppliers do I have?", TOPIC_ENTITIES),
        ("Tell me about supplier S-101", TOPIC_ENTITIES),
        ("What are we short on?", TOPIC_SHORTAGES),
        ("Do we have enough C-2000?", TOPIC_SHORTAGES),
        # Open questions about how things stand ask for the overview.
        ("What needs my attention?", TOPIC_OVERVIEW),
        ("Anything I should worry about?", TOPIC_OVERVIEW),
        ("Any problems?", TOPIC_OVERVIEW),
        ("How are we doing?", TOPIC_OVERVIEW),
        # A specific topic in the same question wins over the open one.
        ("Any problems with late orders?", TOPIC_DELAYS),
        ("Any issues with my upload?", TOPIC_INTAKE),
    ],
)
def test_topic_is_read_from_the_question(question: str, topic: str) -> None:
    assert parse_question(question).topic == topic


def test_record_kinds_and_identifiers_are_extracted() -> None:
    focus = parse_question("What is the status of PO-5001 and WH-PUNE as of 2026-11-05?")
    # The date is not an identifier, and "PO-5001" is not a mention of a record kind.
    assert focus.identifier_candidates == ("PO-5001", "WH-PUNE")
    assert focus.entity_types == ()

    focus = parse_question("Which purchase orders are from supplier S-101?")
    assert focus.entity_types == ("PurchaseOrder", "Supplier")
    assert focus.identifier_candidates == ("S-101",)

    # "purchase order" is consumed before the generic "order".
    assert "SalesOrder" not in parse_question("list purchase orders").entity_types
    assert parse_question("list orders").entity_types == ("PurchaseOrder", "SalesOrder")


def test_a_question_about_a_kind_of_record_is_not_an_overview() -> None:
    focus = parse_question("How many suppliers are in my workspace?")
    assert focus.topic == TOPIC_ENTITIES
    assert focus.entity_types == ("Supplier",)
    assert focus.wants_count is True


def test_everyday_phrases_do_not_name_records() -> None:
    assert parse_question("thanks a lot").entity_types == ()
    assert parse_question("that is part of the plan, in order to finish").entity_types == ()
    # An apostrophe inside a word is not a quotation.
    assert parse_question("What is S-101's impact on Acme's orders?").quoted_phrases == ()
    assert parse_question("Why is 'Bharat Castings' late?").quoted_phrases == ("Bharat Castings",)


def test_names_are_noticed_without_a_record_kind() -> None:
    assert parse_question("Tell me about Bharat Castings").proper_nouns == ("Bharat", "Castings")
    assert parse_question("Bharat Castings").names_data is True
    # A capital at the start of a sentence is not a name.
    assert parse_question("Thanks").names_data is False
    assert parse_question("Hello there").names_data is False
    assert parse_question("asdf qwerty zxcv").names_data is False
    # A hyphenated everyday word is not an identifier.
    assert parse_question("any follow-up on that").names_data is False


def test_two_letter_codes_count_only_when_written_in_capitals() -> None:
    assert parse_question("Which suppliers are in DE?").short_codes == ("DE",)
    assert parse_question("Suppliers in IN or US").short_codes == ("IN", "US")
    # The same letters as ordinary words are not codes.
    assert parse_question("which suppliers are in india, tell us").short_codes == ()
    # A question typed in capitals throughout says nothing about its short words.
    assert parse_question("WHICH SUPPLIERS ARE IN GERMANY").short_codes == ()
    # Vocabulary such as PO or DC names a kind of record, not a value.
    assert parse_question("Which PO goes to the DC?").short_codes == ()
    # A code alone does not make a message a question about the data.
    assert parse_question("OK").names_data is False


def test_residual_drops_topic_and_kind_words_so_values_can_be_matched() -> None:
    focus = parse_question("Which tier_1 suppliers are not active?")
    assert focus.residual == "which tier 1 are not active"


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        # Questions about the workspace's records go to the tool that reads them.
        ("What changed?", IntentType.GRAPH_QUERY),
        ("Which suppliers do I have?", IntentType.GRAPH_QUERY),
        ("Which purchase orders are delayed?", IntentType.GRAPH_QUERY),
        ("Tell me about supplier S-101", IntentType.GRAPH_QUERY),
        ("tell me about bharat castings", IntentType.GRAPH_QUERY),
        ("Is my data ready?", IntentType.GRAPH_QUERY),
        ("Show me my inventory", IntentType.GRAPH_QUERY),
        ("hi, which orders are late?", IntentType.GRAPH_QUERY),
        ("why did PO-5001 slip?", IntentType.GRAPH_QUERY),
        ("PO-5001", IntentType.GRAPH_QUERY),
        ("Which orders are exposed?", IntentType.RISK_QUERY),
        ("Give me a summary", IntentType.STATE_OVERVIEW),
        ("What should I do about the delay from supplier S-101?", IntentType.RECOMMEND),
        # Other capabilities keep their own intent, even when they name a record.
        ("what is the forecast for SKU-42?", IntentType.FORECAST_QUERY),
        ("what if S-101 fails?", IntentType.WHATIF),
        ("show the audit trace for TRC-abc123", IntentType.TRACE_QUERY),
        ("approve D-42", IntentType.APPROVE),
        ("execute the decision now", IntentType.EXECUTE),
        ("compare scenario A vs B", IntentType.COMPARE),
        # Questions about the product itself are explained, not looked up.
        ("how does publishing work?", IntentType.EXPLAIN),
        ("what are you?", IntentType.EXPLAIN),
        # Small talk and unreadable text stay as they were.
        ("help", IntentType.HELP),
        ("what can you do", IntentType.HELP),
        ("hello there", IntentType.GREETING),
        ("thanks a lot", IntentType.UNKNOWN),
        ("asdf qwerty zxcv", IntentType.UNKNOWN),
        # The registers are asked for by their plain names.
        ("show me decisions", IntentType.DECISION_QUERY),
        ("decisions", IntentType.DECISION_QUERY),
        ("what is waiting for approval?", IntentType.DECISION_QUERY),
        ("show scenarios", IntentType.SCENARIO_QUERY),
        ("list my saved scenarios", IntentType.SCENARIO_QUERY),
        ("list risks", IntentType.RISK_QUERY),
        # A scenario to run is still a what-if.
        ("run a scenario where S-101 fails", IntentType.WHATIF),
        # Two named records side by side is a reading of the data.
        ("Compare S-100 and S-101", IntentType.GRAPH_QUERY),
        ("Compare Acme Metals and Bharat Castings", IntentType.GRAPH_QUERY),
        ("S-100 vs S-105", IntentType.GRAPH_QUERY),
        ("compare the options for PO-5001", IntentType.COMPARE),
        # A kind of record named by what it does.
        ("Who supplies ball bearings?", IntentType.GRAPH_QUERY),
        ("who do we buy the housings from?", IntentType.GRAPH_QUERY),
        ("total quantity on order", IntentType.GRAPH_QUERY),
    ],
)
async def test_built_in_classifier_routes_questions(question: str, intent: IntentType) -> None:
    classified = await DeterministicLLMAdapter().classify_intent(question)
    assert classified.intent == intent, question


OPENERS = (
    "can you tell me ",
    "could you please tell me ",
    "do you know ",
    "please show me ",
    "i'd like to know ",
    "i need to know ",
    "are you able to tell me ",
    "hi, ",
    "hey cortex, ",
    "vanessa, ",
    "quick question: ",
    "ok so ",
)


@pytest.mark.parametrize(
    "question",
    [
        "which purchase orders are late?",
        "what is below safety stock?",
        "which orders are exposed?",
        "what changed?",
        "which suppliers do i have?",
        "tell me about S-101",
        "is my data ready?",
        "give me a summary",
        "how many suppliers do we have?",
        "is PO-5003 late?",
        "who supplies C-2000?",
    ],
)
async def test_conversational_openers_do_not_change_how_a_question_is_read(question: str) -> None:
    """ "Can you tell me which orders are late?" is the question "which orders are late?"."""
    llm = DeterministicLLMAdapter()
    plain = await llm.classify_intent(question)
    assert plain.intent in {
        IntentType.GRAPH_QUERY,
        IntentType.RISK_QUERY,
        IntentType.STATE_OVERVIEW,
    }
    for opener in OPENERS:
        asked = await llm.classify_intent(opener + question)
        assert asked.intent == plain.intent, opener + question
        assert asked.confidence == 0.9, opener + question
        assert parse_question(opener + question).topic == parse_question(question).topic


@pytest.mark.parametrize(
    "question",
    [
        "what are you?",
        "who are you?",
        "what can you do?",
        "can you explain yourself?",
        "what is cortex?",
        "tell me about nexus",
        "how does the platform work?",
        "how does publishing work?",
        "what does safety stock mean?",
    ],
)
async def test_questions_about_the_assistant_are_not_looked_up_in_the_data(question: str) -> None:
    classified = await DeterministicLLMAdapter().classify_intent(question)
    assert classified.intent not in {
        IntentType.GRAPH_QUERY,
        IntentType.RISK_QUERY,
        IntentType.STATE_OVERVIEW,
    }, question


async def test_data_questions_only_reach_tools_open_to_every_role() -> None:
    """Routing by the words of a question must not widen what a role can do."""
    from app.modules.nexus_spine.p0_migration.authz import TOOL_PERMISSIONS, NexusRole

    llm = DeterministicLLMAdapter()
    for question in (
        "What changed?",
        "Which orders are exposed?",
        "Give me a summary",
        "PO-5001",
        "What needs my attention?",
        "Can you tell me which suppliers are in DE?",
    ):
        tool = INTENT_TO_TOOL[(await llm.classify_intent(question)).intent]
        assert NexusRole.VIEWER in TOOL_PERMISSIONS[tool], (question, tool)


async def test_classifier_confidence_tracks_whether_the_question_was_understood() -> None:
    llm = DeterministicLLMAdapter()
    assert (await llm.classify_intent("Which suppliers do I have?")).confidence == 0.9
    assert (await llm.classify_intent("asdf qwerty zxcv")).confidence == 0.3
    # The SKU entity used by the forecast and demand tools is still extracted.
    assert (await llm.classify_intent("what is the forecast for SKU-42?")).entities == {
        "sku": "SKU-42"
    }
