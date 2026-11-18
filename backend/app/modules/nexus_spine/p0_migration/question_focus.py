"""Deterministic reading of a workspace question.

Turns the words of a question into a small, explainable focus: what the
question is about (topic), which kinds of record it names, and which tokens
could be record identifiers. Nothing here touches data or a model: the tools
match the focus against the published workspace, and the answer states how
the question was read, so a wrong reading is visible instead of hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TOPIC_ENTITIES = "entities"
TOPIC_OVERVIEW = "overview"
TOPIC_DELAYS = "delays"
TOPIC_SHORTAGES = "shortages"
TOPIC_EXPOSURE = "exposure"
TOPIC_CHANGES = "changes"
TOPIC_INTAKE = "intake"

# Checked in this order: the first topic with a matching phrase wins, so the
# more specific readings come first.
_TOPIC_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        TOPIC_CHANGES,
        (
            r"\bwhat(?:'s|s| is| has| have)? (?:changed|new)\b",
            r"\bwhat (?:was|were|got) (?:added|updated|changed)\b",
            r"\bwhat did (?:the|my) (?:last|latest) (?:upload|publish|file) (?:change|add)\b",
            r"\b(?:recent|latest|last) (?:change|changes|update|updates)\b",
            r"\bany(?:thing)? (?:new|changed|changes)\b",
            r"\bchanged? since\b",
            r"\bchange ?log\b",
            r"\bdifferences? (?:since|from)\b",
        ),
    ),
    (
        TOPIC_EXPOSURE,
        (
            r"\bexpos(?:ed|ure|ures)\b",
            r"\bat risk\b",
            r"\bimpact(?:ed|s)?\b",
            r"\baffect(?:ed|s)?\b",
            r"\bblast radius\b",
            r"\bdownstream\b",
            r"\bknock[- ]on\b",
            r"\bdepend(?:s|ent|ency|encies)? on\b",
        ),
    ),
    (
        TOPIC_SHORTAGES,
        (
            r"\bsafety stocks?\b",
            r"\b(?:low|short|insufficient|not enough) (?:on )?(?:stock|inventory)\b",
            r"\bshortages?\b",
            r"\bstock ?outs?\b",
            r"\bout of stock\b",
            r"\brunning (?:low|out)\b",
            r"\bre-?order(?:s|ed|ing)?\b",
            r"\bunder-?stock(?:ed)?\b",
            r"\bbelow (?:the |its |their )?(?:minimum|threshold|reorder)\b",
            r"\bshort (?:on|of)\b",
            r"\brunning short\b",
            r"\benough\b",
        ),
    ),
    (
        TOPIC_DELAYS,
        (
            r"\bdelay(?:s|ed|ing)?\b",
            r"\blate\b",
            r"\blateness\b",
            r"\boverdue\b",
            r"\bbehind schedule\b",
            r"\bpast due\b",
            r"\bslipp?(?:ed|ing)\b",
            r"\bnot on time\b",
            r"\bmissed\b",
        ),
    ),
    (
        TOPIC_INTAKE,
        (
            r"\bupload(?:s|ed|ing)?\b",
            r"\bfiles?\b",
            r"\bbatch(?:es)?\b",
            r"\breadiness\b",
            r"\b(?:data|workspace|upload|file|batch)\b[^?.!]*\bready\b",
            r"\bready\b[^?.!]*\b(?:publish|published|data)\b",
            r"\b(?:pending|awaiting|waiting for|needs?) review\b",
            r"\breview queue\b",
            r"\b(?:left to review|to be reviewed)\b",
            r"\bclaims?\b",
            r"\bconflicts?\b",
            r"\b(?:un)?publish(?:ed|ing)?\b",
            r"\bdata (?:status|quality|sources?)\b",
            r"\bsources?\b",
        ),
    ),
    (
        TOPIC_OVERVIEW,
        (
            r"\bsummar(?:y|ies|ise|ize)\b",
            r"\boverview\b",
            r"\bwhat (?:data )?do i have\b",
            r"\bwhat(?:'s|s| is) (?:in|inside) (?:my|the|this)\b",
            r"\bin (?:my|the|this) (?:graph|workspace|data)\b",
            r"\bdescribe (?:my|the|this) (?:data|workspace|graph)\b",
            r"\bstate of the world\b",
            r"\bworld state\b",
            # Open questions about how things stand: the overview leads with
            # what is late, short or flagged.
            r"\b(?:need|needs|needing|require|requires) (?:my |our |your |any )?attention\b",
            r"\bworr(?:y|ied|ying)\b",
            r"\b(?:problems?|issues?|concerns?)\b",
            r"\burgent\b",
            r"\bpriorit(?:y|ies)\b",
            r"\bhow (?:are|is) (?:we|things|it|everything) (?:doing|going|looking)\b",
            r"\bwhat(?:'s|s| is) (?:going on|happening|the situation|the status|the picture)\b",
            r"\bbrief(?:ing)?\b",
            r"\bstand(?:s|ing)? out\b",
            r"\bhighlights?\b",
        ),
    ),
)

# Words that name a kind of record, mapped to canonical graph entity types.
# Longer phrases are matched first and consumed, so "purchase order" is not
# also read as the generic "order".
_TYPE_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bill of materials", ("BOM",)),
    ("bill of material", ("BOM",)),
    ("distribution centre", ("Facility",)),
    ("distribution center", ("Facility",)),
    ("purchase order", ("PurchaseOrder",)),
    ("procurement order", ("PurchaseOrder",)),
    ("supplier order", ("PurchaseOrder",)),
    ("inbound order", ("PurchaseOrder",)),
    ("customer order", ("SalesOrder",)),
    ("outbound order", ("SalesOrder",)),
    ("sales order", ("SalesOrder",)),
    ("demand region", ("DemandRegion",)),
    ("stock level", ("InventoryItem", "InventoryLot")),
    ("cross dock", ("Facility",)),
    ("on hand", ("InventoryItem", "InventoryLot")),
    ("consignment", ("Shipment",)),
    ("inventory", ("InventoryItem", "InventoryLot")),
    ("warehouse", ("Facility",)),
    ("component", ("Product",)),
    ("territory", ("Region",)),
    ("supplier", ("Supplier",)),
    ("customer", ("Customer",)),
    ("facility", ("Facility",)),
    ("shipment", ("Shipment",)),
    ("delivery", ("Shipment",)),
    ("material", ("Product",)),
    ("carrier", ("Carrier",)),
    ("factory", ("Facility",)),
    ("product", ("Product",)),
    ("vendor", ("Supplier",)),
    ("client", ("Customer",)),
    ("region", ("Region", "DemandRegion")),
    ("stock", ("InventoryItem", "InventoryLot")),
    ("plant", ("Facility",)),
    ("depot", ("Facility",)),
    ("order", ("PurchaseOrder", "SalesOrder")),
    ("route", ("Route",)),
    ("item", ("Product",)),
    ("part", ("Product",)),
    ("port", ("Facility",)),
    ("lane", ("Route",)),
    ("site", ("Facility",)),
    ("sku", ("Product",)),
    ("bom", ("BOM",)),
    ("lot", ("InventoryLot",)),
    ("po", ("PurchaseOrder",)),
    ("dc", ("Facility",)),
)

# Ways of asking for a kind of record by what it does: "who supplies ball
# bearings?" asks for suppliers without the word "supplier". Each entry is
# (how the question says it, the kinds it asks for, the words to set aside so
# they are not looked up as data).
_RELATION_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...], re.Pattern[str]], ...] = (
    (
        re.compile(r"\bsuppl(?:ies|ied|ying)\b"),
        ("Supplier",),
        re.compile(r"\bsuppl(?:ies|ied|ying)\b(?: by\b)?"),
    ),
    (
        re.compile(r"\b(?:sourced|provided|sold|made|manufactured) by\b"),
        ("Supplier",),
        re.compile(r"\b(?:sourced|provided|sold|made|manufactured) by\b"),
    ),
    (
        re.compile(r"\bwho (?:sells|provides|makes|manufactures|delivers)\b"),
        ("Supplier",),
        re.compile(r"\b(?:sells|provides|makes|manufactures|delivers)\b"),
    ),
    (
        # "Who do we buy C-2000 from?", "where do we get the housings from?"
        re.compile(r"\b(?:who|whom|where)\b[^?.!]*\b(?:buy|get|purchase|procure)\b[^?.!]*\bfrom\b"),
        ("Supplier",),
        re.compile(r"\b(?:buy|get|purchase|procure|from)\b"),
    ),
    (
        re.compile(r"\bwho (?:buys|purchases)\b"),
        ("Customer",),
        re.compile(r"\b(?:buys|purchases)\b"),
    ),
)

# A request for one figure over the listed records, checked in this order at
# the place each first appears in the question.
_AGGREGATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "sum",
        re.compile(
            r"\b(?:total|totals|sum|combined|altogether|in total|in all|add(?:ed)? up)\b"
            r"|\bhow many (?:units|pieces|pcs)\b|\bhow much\b"
        ),
    ),
    ("average", re.compile(r"\b(?:average|avg|on average)\b|\bmean (?:of|for)\b|\bthe mean\b")),
    (
        "max",
        re.compile(
            r"\b(?:highest|largest|biggest|greatest|maximum|max|longest|most expensive|costliest)\b"
        ),
    ),
    ("min", re.compile(r"\b(?:lowest|smallest|least|minimum|min|shortest|cheapest)\b")),
)
AGGREGATE_SUM = "sum"
AGGREGATE_AVERAGE = "average"
AGGREGATE_MAX = "max"
AGGREGATE_MIN = "min"

_COMPARE = re.compile(
    r"\bcompar(?:e|es|ed|ing|ison)\b|\bversus\b|\bvs\b|\bdifferences? between\b"
    r"|\bside by side\b|\bhow do(?:es)? [^?.!]* differ\b"
)
# Orders that have not arrived: "on order", "open", "outstanding".
_OPEN_ONLY = re.compile(
    r"\bon order\b|\bopen\b|\boutstanding\b|\bundelivered\b"
    r"|\bnot (?:yet )?(?:delivered|received|arrived)\b|\bstill (?:due|to come|to arrive)\b"
)

# Words that carry no subject of their own. What is left of a question after
# its topic words, record kinds, names and values is compared with this list
# before anything is looked up by a single word.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "about", "above", "across", "after", "again", "against", "all", "also", "am", "an",
        "and", "any", "anything", "are", "around", "as", "at", "be", "because", "been", "before",
        "being", "below", "between", "both", "but", "by", "can", "could", "did", "do", "does",
        "doing", "done", "down", "during", "each", "either", "else", "every", "everything", "few",
        "for", "from", "further", "get", "gets", "give", "given", "gives", "go", "going", "got",
        "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how",
        "however", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "know", "let",
        "like", "list", "look", "made", "make", "makes", "many", "may", "me", "might", "more",
        "most", "much", "must", "my", "need", "needs", "no", "nor", "not", "now", "of", "off",
        "ok", "okay", "on", "once", "one", "only", "or", "other", "our", "ours", "out", "over",
        "own", "per", "please", "quick", "really", "right", "s", "same", "say", "see", "seen",
        "shall", "she", "should", "show", "shows", "so", "some", "something", "such", "sure", "t",
        "take", "tell", "than", "thank", "thanks", "that", "the", "their", "theirs", "them",
        "then", "there", "these", "they", "thing", "things", "this", "those", "through", "to",
        "too", "under", "until", "up", "upon", "us", "use", "used", "using", "very", "via", "want",
        "wants", "was", "we", "were", "what", "whats", "when", "where", "whether", "which",
        "while", "who", "whom", "whose", "why", "will", "with", "within", "without", "would",
        "yes", "yet", "you", "your", "yours", "currently", "today", "tomorrow", "yesterday",
        "week", "month", "year", "date", "time", "times", "data", "record", "records",
        "information", "info", "details", "detail", "workspace", "published", "file", "files",
        "question", "answer", "cortex", "nexus", "vanessa", "hi", "hello", "hey",
    }
)  # fmt: skip


def fold_word(word: str) -> str:
    """Form of a word used to compare a question with a name: "bearings" -> "bearing".

    Only regular plurals are folded, and the same folding is applied to both
    sides of a comparison, so it never has to be good English.
    """
    if len(word) > 4 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def content_words(text: str) -> list[str]:
    """Words of a normalised text that could name something: no stop words, no numbers."""
    words: list[str] = []
    for word in text.split():
        if len(word) < 3 or word in STOP_WORDS or not word.isalpha():
            continue
        if word not in words:
            words.append(word)
    return words


# Everyday phrases that contain a record-kind word without naming a record.
_IDIOMS = re.compile(
    r"\b(?:a lot(?: of)?|lots of|part of|in part|for the most part|in order (?:to|for)|"
    r"sort of|kind of|sign off|point of|as part)\b"
)

# Upper-case words that are vocabulary, not record identifiers.
_NOT_IDENTIFIERS = frozenset(
    {
        "API",
        "BOM",
        "BOMS",
        "CSV",
        "DC",
        "ERP",
        "ETA",
        "ID",
        "IDS",
        "KPI",
        "OTIF",
        "PO",
        "POS",
        "SKU",
        "SKUS",
        "SLA",
        "SO",
        "TMS",
        "WMS",
        "XLSX",
    }
)

_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?")
# A date, time or plain quantity: digits and separators only.
_NUMERIC = re.compile(r"\d[\d.,:/-]*")
# Single quotes count only when they do not sit inside a word ("S-101's").
_QUOTED = re.compile(
    r"\"([^\"]{2,120})\"|(?<![A-Za-z0-9])'([^']{2,120})'(?![A-Za-z0-9])|“([^”]{2,120})”"
)
_COUNT = re.compile(r"\bhow many\b|\bnumber of\b|\bcount\b|\bhow much\b")
_WHY = re.compile(
    r"\bwhy\b|\bhow come\b|\breason(?:s)? (?:for|behind)\b|\bcause(?:s|d)? (?:of|by)?\b"
)
_QUESTION_OPENERS = re.compile(
    r"^(?:what|which|who|whom|whose|where|when|why|how|is|are|was|were|do|does|did|can|could|"
    r"will|would|should|has|have|had|show|list|give|tell|find|get|display|describe|name|any)\b"
)
MAX_IDENTIFIER_CANDIDATES = 20


@dataclass(frozen=True)
class QuestionFocus:
    """How a question was read. Every field is derived from its words alone."""

    topic: str = TOPIC_ENTITIES
    entity_types: tuple[str, ...] = ()
    # Tokens shaped like identifiers (a digit, hyphen or underscore): "S-101".
    identifier_candidates: tuple[str, ...] = ()
    # Words written in capitals. They may be identifiers ("ACME") or not ("ASAP"),
    # so they are looked up but never reported as "not found".
    capital_words: tuple[str, ...] = ()
    # Capitalised words that are not just the start of the sentence: likely
    # part of a name ("Bharat Castings"). Names are matched against the data.
    proper_nouns: tuple[str, ...] = ()
    # Two-letter codes written in capitals inside an otherwise lower-case
    # question ("suppliers in DE"). They are used only to match a stored value
    # that is exactly that code; "in" and "us" as ordinary words never count.
    short_codes: tuple[str, ...] = ()
    quoted_phrases: tuple[str, ...] = ()
    wants_count: bool = False
    asks_why: bool = False
    is_question: bool = False
    # One figure over the listed records: "sum", "average", "max" or "min"
    # ("total quantity on order", "average lead time", "longest lead time").
    aggregate: str | None = None
    # The words that asked for it ("most expensive"): they can also say which
    # field is meant.
    aggregate_words: tuple[str, ...] = ()
    # "Compare A and B", "A vs B".
    wants_comparison: bool = False
    # Only orders that have not arrived ("on order", "open", "outstanding").
    open_only: bool = False
    # Lower-cased question with punctuation removed, used to find names.
    normalized: str = ""
    # The same text with topic and record-kind words blanked out, used to find
    # attribute values ("in transit", "tier 1") without matching the question's own vocabulary.
    residual: str = ""
    topic_phrases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def names_data(self) -> bool:
        """True when the question names a topic, a kind of record or an identifier."""
        # A hyphenated everyday word ("follow-up") is not an identifier; a
        # token with a digit or a capital ("PO-5001", "WH-PUNE") may be one.
        identifiers = [
            token
            for token in self.identifier_candidates
            if any(character.isdigit() or character.isupper() for character in token)
        ]
        return bool(
            self.topic != TOPIC_ENTITIES
            or self.entity_types
            or identifiers
            or self.proper_nouns
            or self.quoted_phrases
            # "Highest unit price" names a figure in the data, not a record.
            or self.aggregate
        )


def normalize_text(value: str) -> str:
    """Lower-case and reduce to words separated by single spaces."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _plural(phrase: str) -> str:
    """Regular expression matching the singular and plural of a phrase."""
    if phrase.endswith("y") and not phrase.endswith(("ay", "ey", "oy")):
        return rf"{re.escape(phrase[:-1])}(?:y|ies)"
    return rf"{re.escape(phrase)}(?:s|es)?"


# Every word used to name a kind of record ("distribution", "centre", "order").
# A name is not recognised by these words alone.
TYPE_WORDS: frozenset[str] = frozenset(
    fold_word(word) for phrase, _types in _TYPE_PHRASES for word in phrase.split()
)

# Longest phrase first, so a phrase is consumed before the words inside it.
_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(rf"\b{_plural(phrase)}\b"), types)
    for phrase, types in sorted(_TYPE_PHRASES, key=lambda item: -len(item[0]))
)
_COMPILED_TOPICS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (topic, tuple(re.compile(pattern) for pattern in patterns))
    for topic, patterns in _TOPIC_PATTERNS
)


def _identifier_candidates(
    text: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Tokens that could be record identifiers or coded values.

    Returns (shaped, capitals, codes): tokens carrying a digit, hyphen or
    underscore; words of three or more letters written fully in capitals; and
    two-letter capital codes, which count only when the question is not
    written in capitals throughout.
    """
    shaped: list[str] = []
    capitals: list[str] = []
    codes: list[str] = []
    mixed_case = any(character.islower() for character in text)
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if len(token) < 2 or token.upper() in _NOT_IDENTIFIERS:
            continue
        if (
            len(token) == 2
            and token.isalpha()
            and token.isupper()
            and mixed_case
            and token not in codes
            and len(codes) < MAX_IDENTIFIER_CANDIDATES
        ):
            codes.append(token)
            continue
        if _NUMERIC.fullmatch(token):
            continue
        has_digit = any(character.isdigit() for character in token)
        has_joiner = bool(re.search(r"[A-Za-z0-9][-_][A-Za-z0-9]", token))
        if has_digit or has_joiner:
            if token not in shaped and len(shaped) < MAX_IDENTIFIER_CANDIDATES:
                shaped.append(token)
        elif (
            len(token) >= 3
            and token.isalpha()
            and token.isupper()
            and token not in capitals
            and len(capitals) < MAX_IDENTIFIER_CANDIDATES
        ):
            capitals.append(token)
    return tuple(shaped), tuple(capitals), tuple(codes)


_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
# Capitalised words that are ordinary English, not names.
_NOT_NAMES = frozenset(
    {
        "I", "I'm", "I've", "I'd", "OK", "Ok", "Please", "Thanks", "Thank", "Hello", "Hi", "Hey",
        "Cortex", "Nexus", "Vanessa", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday", "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
    }
)  # fmt: skip


def _proper_nouns(text: str) -> tuple[str, ...]:
    """Capitalised words that are likely part of a name.

    The first word of a sentence is capitalised anyway, so it counts only when
    the next word is capitalised too ("Bharat Castings").
    """
    found: list[str] = []
    for sentence in re.split(r"[.?!]\s+", text):
        words = _WORD.findall(sentence)
        capitalised = [
            word[:1].isupper() and word[1:].islower() and word not in _NOT_NAMES for word in words
        ]
        for position, word in enumerate(words):
            if not capitalised[position]:
                continue
            follows = position + 1 < len(words) and capitalised[position + 1]
            if (position > 0 or follows) and word not in found:
                found.append(word)
    return tuple(found[:MAX_IDENTIFIER_CANDIDATES])


def parse_question(text: str) -> QuestionFocus:
    """Read a question into a QuestionFocus. Pure and deterministic."""
    raw = (text or "").strip()
    lowered = raw.lower().replace("’", "'")
    spaced = " ".join(lowered.split())

    topic = TOPIC_ENTITIES
    topic_phrases: list[str] = []
    residual = spaced
    for candidate, patterns in _COMPILED_TOPICS:
        matches = [match.group(0) for pattern in patterns for match in pattern.finditer(spaced)]
        if not matches:
            continue
        if topic == TOPIC_ENTITIES:
            topic = candidate
        topic_phrases.extend(matches)
        for pattern in patterns:
            residual = pattern.sub(" ", residual)

    # "On order" is set aside before the word "order" is read as a kind of
    # record, or its "on" would be left behind as if it meant something.
    open_only = bool(_OPEN_ONLY.search(spaced))
    residual = _OPEN_ONLY.sub(" ", residual)

    # An identifier such as "PO-5001" or "SKU-42" is not a mention of a record kind.
    shaped, capitals, codes = _identifier_candidates(raw)
    type_text = _IDIOMS.sub(" ", spaced)
    for token in shaped:
        type_text = type_text.replace(token.lower(), " ")

    entity_types: list[str] = []
    for pattern, types in _TYPE_PATTERNS:
        if not pattern.search(type_text):
            continue
        type_text = pattern.sub(" ", type_text)
        residual = pattern.sub(" ", residual)
        for entity_type in types:
            if entity_type not in entity_types:
                entity_types.append(entity_type)
    # "Who supplies ...", "made by ...": a kind of record named by what it does.
    for pattern, types, relation_words in _RELATION_PATTERNS:
        if not pattern.search(type_text):
            continue
        type_text = relation_words.sub(" ", type_text)
        residual = relation_words.sub(" ", residual)
        for entity_type in types:
            if entity_type not in entity_types:
                entity_types.append(entity_type)

    aggregate: str | None = None
    aggregate_words: tuple[str, ...] = ()
    first_position: int | None = None
    for name, pattern in _AGGREGATE_PATTERNS:
        found = pattern.search(spaced)
        if found is None:
            continue
        if first_position is None or found.start() < first_position:
            aggregate, first_position = name, found.start()
            aggregate_words = tuple(found.group(0).split())
        residual = pattern.sub(" ", residual)
    wants_comparison = bool(_COMPARE.search(spaced))
    residual = _COMPARE.sub(" ", residual)

    # "How many suppliers are in my workspace?" asks about suppliers, not for an overview.
    if topic == TOPIC_OVERVIEW and entity_types:
        topic = TOPIC_ENTITIES

    quoted = tuple(
        next(group for group in match.groups() if group).strip() for match in _QUOTED.finditer(raw)
    )

    return QuestionFocus(
        topic=topic,
        entity_types=tuple(entity_types),
        identifier_candidates=shaped,
        capital_words=capitals,
        proper_nouns=_proper_nouns(raw),
        short_codes=codes,
        quoted_phrases=quoted,
        wants_count=bool(_COUNT.search(spaced)),
        asks_why=bool(_WHY.search(spaced)),
        is_question=bool(raw.endswith("?") or _QUESTION_OPENERS.search(spaced)),
        aggregate=aggregate,
        aggregate_words=aggregate_words,
        wants_comparison=wants_comparison,
        open_only=open_only,
        normalized=normalize_text(raw),
        residual=normalize_text(residual),
        topic_phrases=tuple(topic_phrases),
    )
