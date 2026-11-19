"""Field sizes shared by the tables, the API schemas and the import validation.

Defined once so the three can never disagree about how long a code may be or
how many decimals a quantity has.
"""

WORKSPACE_NAME_MAX = 160
SLUG_MAX = 80
CODE_MAX = 64
NAME_MAX = 200
LOCATION_MAX = 200
PLACE_MAX = 100
PO_NUMBER_MAX = 80
ACTOR_MAX = 120
SOURCE_REFERENCE_MAX = 200
SPECIFICATION_TEXT_MAX = 1_000
FILENAME_MAX = 255
SHEET_NAME_MAX = 160

MONEY_PRECISION = 18
MONEY_SCALE = 2
QUANTITY_PRECISION = 18
QUANTITY_SCALE = 3
