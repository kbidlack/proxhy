from dataclasses import dataclass


@dataclass(frozen=True)
class Stat:
    name: str
    json_key: str
    main: str
    aliases: list[str]


BEDWARS_NON_DREAM_MAPPING: dict[str, str] = {
    "Solo": "eight_one",
    "Doubles": "eight_two",
    "3v3v3v3": "four_three",
    "4v4v4v4": "four_four",
    "4v4": "two_four",
}

BEDWARS_DREAM_MAPPING_SIMPLE: dict[str, str] = {
    "Rush": "rush",
    "Ultimate": "ultimate",
    "Lucky": "lucky",
    "Swap": "swap",
    "Voidless": "voidless",
    "Armed": "armed",
    "One Block": "oneblock",
    "Castle": "castle",
}

BEDWARS_DREAM_MAPPING_FULL: dict[str, str] = {
    "Rush Solos": "eight_one_rush",
    "Rush 2s": "eight_two_rush",
    "Rush 4s": "four_four_rush",
    "Ultimate Solos": "eight_one_ultimate",
    "Ultimate 2s": "eight_two_ultimate",
    "Ultimate 4s": "four_four_ultimate",
    "Lucky 2s": "eight_two_lucky",
    "Lucky 4s": "four_four_lucky",
    "Swap 2s": "eight_two_swap",
    "Swap 4s": "four_four_swap",
    "Voidless 2s": "eight_two_voidless",
    "Voidless 4s": "four_four_voidless",
    "Castle": "castle",
    "Armed 2s": "eight_two_armed",
    "Armed 4s": "four_four_armed",
    "One Block": "eight_one_oneblock",
}


BEDWARS_MAPPING_FULL = BEDWARS_NON_DREAM_MAPPING | BEDWARS_DREAM_MAPPING_FULL
BEDWARS_MAPPING_SIMPLE = BEDWARS_NON_DREAM_MAPPING | BEDWARS_DREAM_MAPPING_SIMPLE
