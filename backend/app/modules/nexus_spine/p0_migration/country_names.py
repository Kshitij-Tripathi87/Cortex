"""Country names and codes, so a question can name a country either way.

Files usually store a country as a two-letter code ("DE"); people ask about
"Germany" or "German suppliers". Without this table the Ask box read "Which
suppliers are in Germany?" as "which suppliers do I have" and listed all of
them. The table is ISO 3166-1 (two- and three-letter codes, English short
names) plus the everyday names and adjectives people actually type.

Nothing here decides that a field holds a country: the caller only consults
the table for fields whose name says so (``is_country_field``), and a match
always ends up as a filter on a value that is stored in the workspace.
"""

from __future__ import annotations

import re
from functools import lru_cache

# code | three-letter code | names (first is the usual one) | adjectives
_TABLE = """
AF|AFG|Afghanistan|Afghan
AL|ALB|Albania|Albanian
DZ|DZA|Algeria|Algerian
AD|AND|Andorra|Andorran
AO|AGO|Angola|Angolan
AG|ATG|Antigua and Barbuda|
AR|ARG|Argentina|Argentine;Argentinian
AM|ARM|Armenia|Armenian
AU|AUS|Australia|Australian
AT|AUT|Austria|Austrian
AZ|AZE|Azerbaijan|Azerbaijani
BS|BHS|Bahamas;The Bahamas|Bahamian
BH|BHR|Bahrain|Bahraini
BD|BGD|Bangladesh|Bangladeshi
BB|BRB|Barbados|Barbadian
BY|BLR|Belarus|Belarusian
BE|BEL|Belgium|Belgian
BZ|BLZ|Belize|Belizean
BJ|BEN|Benin|Beninese
BT|BTN|Bhutan|Bhutanese
BO|BOL|Bolivia|Bolivian
BA|BIH|Bosnia and Herzegovina;Bosnia|Bosnian
BW|BWA|Botswana|
BR|BRA|Brazil;Brasil|Brazilian
BN|BRN|Brunei;Brunei Darussalam|Bruneian
BG|BGR|Bulgaria|Bulgarian
BF|BFA|Burkina Faso|Burkinabe
BI|BDI|Burundi|Burundian
CV|CPV|Cabo Verde;Cape Verde|Cape Verdean
KH|KHM|Cambodia|Cambodian
CM|CMR|Cameroon|Cameroonian
CA|CAN|Canada|Canadian
CF|CAF|Central African Republic|
TD|TCD|Chad|Chadian
CL|CHL|Chile|Chilean
CN|CHN|China;Mainland China;Peoples Republic of China;PRC|Chinese
CO|COL|Colombia|Colombian
KM|COM|Comoros|Comorian
CG|COG|Congo;Republic of the Congo;Congo Brazzaville|
CD|COD|Democratic Republic of the Congo;DR Congo;DRC;Congo Kinshasa|
CR|CRI|Costa Rica|Costa Rican
CI|CIV|Cote d Ivoire;Ivory Coast|Ivorian
HR|HRV|Croatia|Croatian
CU|CUB|Cuba|Cuban
CY|CYP|Cyprus|Cypriot
CZ|CZE|Czechia;Czech Republic|Czech
DK|DNK|Denmark|Danish
DJ|DJI|Djibouti|
DM|DMA|Dominica|
DO|DOM|Dominican Republic|Dominican
EC|ECU|Ecuador|Ecuadorian
EG|EGY|Egypt|Egyptian
SV|SLV|El Salvador|Salvadoran
GQ|GNQ|Equatorial Guinea|
ER|ERI|Eritrea|Eritrean
EE|EST|Estonia|Estonian
SZ|SWZ|Eswatini;Swaziland|
ET|ETH|Ethiopia|Ethiopian
FJ|FJI|Fiji|Fijian
FI|FIN|Finland|Finnish
FR|FRA|France|French
GA|GAB|Gabon|Gabonese
GM|GMB|Gambia;The Gambia|Gambian
GE|GEO|Georgia|Georgian
DE|DEU|Germany;Deutschland|German
GH|GHA|Ghana|Ghanaian
GR|GRC|Greece|Greek
GD|GRD|Grenada|
GT|GTM|Guatemala|Guatemalan
GN|GIN|Guinea|Guinean
GW|GNB|Guinea Bissau|
GY|GUY|Guyana|Guyanese
HT|HTI|Haiti|Haitian
HN|HND|Honduras|Honduran
HU|HUN|Hungary|Hungarian
IS|ISL|Iceland|Icelandic
IN|IND|India|Indian
ID|IDN|Indonesia|Indonesian
IR|IRN|Iran|Iranian
IQ|IRQ|Iraq|Iraqi
IE|IRL|Ireland;Republic of Ireland|Irish
IL|ISR|Israel|Israeli
IT|ITA|Italy|Italian
JM|JAM|Jamaica|Jamaican
JP|JPN|Japan|Japanese
JO|JOR|Jordan|Jordanian
KZ|KAZ|Kazakhstan|Kazakh
KE|KEN|Kenya|Kenyan
KI|KIR|Kiribati|
KP|PRK|North Korea|North Korean
KR|KOR|South Korea;Korea;Republic of Korea|South Korean;Korean
KW|KWT|Kuwait|Kuwaiti
KG|KGZ|Kyrgyzstan|Kyrgyz
LA|LAO|Laos|Laotian;Lao
LV|LVA|Latvia|Latvian
LB|LBN|Lebanon|Lebanese
LS|LSO|Lesotho|
LR|LBR|Liberia|Liberian
LY|LBY|Libya|Libyan
LI|LIE|Liechtenstein|
LT|LTU|Lithuania|Lithuanian
LU|LUX|Luxembourg|Luxembourgish
MG|MDG|Madagascar|Malagasy
MW|MWI|Malawi|Malawian
MY|MYS|Malaysia|Malaysian
MV|MDV|Maldives|Maldivian
ML|MLI|Mali|Malian
MT|MLT|Malta|Maltese
MH|MHL|Marshall Islands|
MR|MRT|Mauritania|Mauritanian
MU|MUS|Mauritius|Mauritian
MX|MEX|Mexico|Mexican
FM|FSM|Micronesia|
MD|MDA|Moldova|Moldovan
MC|MCO|Monaco|
MN|MNG|Mongolia|Mongolian
ME|MNE|Montenegro|Montenegrin
MA|MAR|Morocco|Moroccan
MZ|MOZ|Mozambique|Mozambican
MM|MMR|Myanmar;Burma|Burmese
NA|NAM|Namibia|Namibian
NR|NRU|Nauru|
NP|NPL|Nepal|Nepalese;Nepali
NL|NLD|Netherlands;The Netherlands;Holland|Dutch
NZ|NZL|New Zealand|
NI|NIC|Nicaragua|Nicaraguan
NE|NER|Niger|
NG|NGA|Nigeria|Nigerian
MK|MKD|North Macedonia;Macedonia|Macedonian
NO|NOR|Norway|Norwegian
OM|OMN|Oman|Omani
PK|PAK|Pakistan|Pakistani
PW|PLW|Palau|
PA|PAN|Panama|Panamanian
PG|PNG|Papua New Guinea|
PY|PRY|Paraguay|Paraguayan
PE|PER|Peru|Peruvian
PH|PHL|Philippines;The Philippines|Philippine;Filipino
PL|POL|Poland|Polish
PT|PRT|Portugal|Portuguese
QA|QAT|Qatar|Qatari
RO|ROU|Romania|Romanian
RU|RUS|Russia;Russian Federation|Russian
RW|RWA|Rwanda|Rwandan
KN|KNA|Saint Kitts and Nevis|
LC|LCA|Saint Lucia|
VC|VCT|Saint Vincent and the Grenadines|
WS|WSM|Samoa|Samoan
SM|SMR|San Marino|
ST|STP|Sao Tome and Principe|
SA|SAU|Saudi Arabia;KSA|Saudi
SN|SEN|Senegal|Senegalese
RS|SRB|Serbia|Serbian
SC|SYC|Seychelles|
SL|SLE|Sierra Leone|
SG|SGP|Singapore|Singaporean
SK|SVK|Slovakia|Slovak;Slovakian
SI|SVN|Slovenia|Slovenian
SB|SLB|Solomon Islands|
SO|SOM|Somalia|Somali
ZA|ZAF|South Africa|South African
SS|SSD|South Sudan|
ES|ESP|Spain|Spanish
LK|LKA|Sri Lanka|Sri Lankan
SD|SDN|Sudan|Sudanese
SR|SUR|Suriname|
SE|SWE|Sweden|Swedish
CH|CHE|Switzerland|Swiss
SY|SYR|Syria|Syrian
TJ|TJK|Tajikistan|Tajik
TZ|TZA|Tanzania|Tanzanian
TH|THA|Thailand|Thai
TL|TLS|Timor Leste;East Timor|
TG|TGO|Togo|Togolese
TO|TON|Tonga|Tongan
TT|TTO|Trinidad and Tobago|
TN|TUN|Tunisia|Tunisian
TR|TUR|Turkey;Turkiye|Turkish
TM|TKM|Turkmenistan|Turkmen
TV|TUV|Tuvalu|
UG|UGA|Uganda|Ugandan
UA|UKR|Ukraine|Ukrainian
AE|ARE|United Arab Emirates;UAE;Emirates|Emirati
GB|GBR|United Kingdom;UK;U K;Great Britain;Britain;England;Scotland;Wales;Northern Ireland|British;English;Scottish;Welsh
US|USA|United States;United States of America;USA;U S A;U S;America;The States|American
UY|URY|Uruguay|Uruguayan
UZ|UZB|Uzbekistan|Uzbek
VU|VUT|Vanuatu|
VA|VAT|Vatican City;Holy See|
VE|VEN|Venezuela|Venezuelan
VN|VNM|Vietnam;Viet Nam|Vietnamese
YE|YEM|Yemen|Yemeni
ZM|ZMB|Zambia|Zambian
ZW|ZWE|Zimbabwe|Zimbabwean
HK|HKG|Hong Kong|
MO|MAC|Macau;Macao|
TW|TWN|Taiwan|Taiwanese
PR|PRI|Puerto Rico|Puerto Rican
PS|PSE|Palestine|Palestinian
XK|XKX|Kosovo|Kosovar
GL|GRL|Greenland|
GI|GIB|Gibraltar|
BM|BMU|Bermuda|
KY|CYM|Cayman Islands|
VG|VGB|British Virgin Islands|
JE|JEY|Jersey|
GG|GGY|Guernsey|
IM|IMN|Isle of Man|
FO|FRO|Faroe Islands|
NC|NCL|New Caledonia|
PF|PYF|French Polynesia|
GU|GUM|Guam|
AW|ABW|Aruba|
CW|CUW|Curacao|
RE|REU|Reunion|
GP|GLP|Guadeloupe|
MQ|MTQ|Martinique|
GF|GUF|French Guiana|
"""

# Phrases that contain a country name without naming that country. They are
# removed from a question before country names are looked for.
_NOT_A_COUNTRY: tuple[str, ...] = (
    "north america",
    "south america",
    "latin america",
    "central america",
    "north american",
    "south american",
    "latin american",
    "central american",
    "new mexico",
    "new jersey",
    "indian ocean",
)

# Names that are also ordinary words or abbreviations: they count as a
# country only when written in capitals ("US", "UK", "UAE", "USA", "DRC").
_CAPITALS_ONLY: frozenset[str] = frozenset({"uk", "us", "usa", "uae", "prc", "drc", "ksa"})

# Three-letter codes that are English words. "Which suppliers ARE late?" does
# not mention the United Arab Emirates, so these are never read from a
# question; as a stored value in a country column they still mean the country.
_CODES_THAT_ARE_WORDS: frozenset[str] = frozenset(
    {
        "and", "are", "bel", "ben", "can", "cod", "cog", "cub", "fin", "gab", "geo", "gum",
        "lie", "mac", "mar", "mus", "nor", "pan", "per", "pry", "sur", "ton", "tun", "tur", "vat",
    }
)  # fmt: skip


def _normalize(text: str) -> str:
    """Lower-case words separated by single spaces, accents and punctuation removed."""
    replaced = (
        text.lower()
        .replace("ô", "o")
        .replace("é", "e")
        .replace("ç", "c")
        .replace("ü", "u")
        .replace("’", " ")
        .replace("'", " ")
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", replaced).split())


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """(name -> code, three-letter code -> code, adjective -> code, code -> usual name)."""
    names: dict[str, str] = {}
    alpha3: dict[str, str] = {}
    adjectives: dict[str, str] = {}
    usual: dict[str, str] = {}
    for line in _TABLE.strip().splitlines():
        code, three, name_list, adjective_list = line.split("|")
        alpha3[three.lower()] = code
        for position, name in enumerate(part for part in name_list.split(";") if part):
            names[_normalize(name)] = code
            if position == 0:
                usual[code] = name
        for adjective in (part for part in adjective_list.split(";") if part):
            adjectives[_normalize(adjective)] = code
    return names, alpha3, adjectives, usual


def country_name(code: str) -> str | None:
    """Usual English name for a two-letter code: 'Germany' for 'DE'."""
    return _index()[3].get(code.upper())


def country_code(value: str) -> str | None:
    """Two-letter code for a stored value: a code, a three-letter code or a name.

    'DE', 'de', 'DEU' and 'Germany' all give 'DE'. None when the value is not
    a country this table knows.
    """
    names, alpha3, _adjectives, usual = _index()
    text = value.strip()
    if len(text) == 2 and text.isalpha():
        return text.upper() if text.upper() in usual else None
    if len(text) == 3 and text.isalpha() and text.lower() in alpha3:
        return alpha3[text.lower()]
    return names.get(_normalize(text))


def is_country_field(field_name: str) -> bool:
    """True when a column name says it holds a country ('country', 'origin_country')."""
    key = field_name.strip().lower()
    words = set(re.split(r"[^a-z0-9]+", key))
    return (
        bool(words & {"country", "countries", "nation", "coo"})
        or key.startswith("country")
        or key.endswith("country")
        or key in {"origin", "destination", "made_in", "ship_from", "ship_to"}
    )


def countries_mentioned(question: str) -> dict[str, str]:
    """Countries a question names, as {two-letter code: the words that named it}.

    Names and adjectives are read whatever their case ("germany", "German").
    Three-letter codes and the short names in ``_CAPITALS_ONLY`` count only
    when written in capitals inside a question that is not in capitals
    throughout ("DEU", "UK"): "us", "it" and "are" are ordinary words. Two-
    letter codes ("DE") are left to the caller, which applies the same rule.
    """
    names, alpha3, adjectives, _usual = _index()
    found: dict[str, str] = {}

    if any(character.islower() for character in question):
        for match in re.finditer(r"\b[A-Z]{2,3}\b", question):
            word = match.group(0).lower()
            if word in _CODES_THAT_ARE_WORDS:
                continue
            if len(word) == 3:
                code = alpha3.get(word) or names.get(word)
            else:
                code = names.get(word) if word in _CAPITALS_ONLY else None
            if code and code not in found:
                found[code] = match.group(0)

    text = f" {_normalize(question)} "
    for phrase in _NOT_A_COUNTRY:
        text = text.replace(f" {phrase} ", "  ")
    # Longest names first, each consumed, so "South Sudan" is not also "Sudan".
    for phrase in sorted(names, key=len, reverse=True):
        if phrase in _CAPITALS_ONLY or len(phrase) < 4:
            continue
        needle = f" {phrase} "
        if needle in text:
            text = text.replace(needle, "  ")
            found.setdefault(names[phrase], phrase)
    for phrase in sorted(adjectives, key=len, reverse=True):
        position = text.find(f" {phrase} ")
        if position < 0:
            continue
        before = text[:position].split()
        after = text[position + len(phrase) + 2 :].split()
        text = text.replace(f" {phrase} ", "  ")
        # "Answer in German" and "the French version" name a language.
        if (before and before[-1] == "in") or (
            after and after[0] in {"language", "version", "translation"}
        ):
            continue
        found.setdefault(adjectives[phrase], phrase)
    return found


__all__ = [
    "countries_mentioned",
    "country_code",
    "country_name",
    "is_country_field",
]
