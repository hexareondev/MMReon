"""Герои Доты: внутренний код (как в GSI, без npc_dota_hero_) ↔ английское имя (как в «Истории»)."""
from __future__ import annotations

import difflib
import re

NAMES = {
    "abaddon": "Abaddon", "abyssal_underlord": "Underlord", "alchemist": "Alchemist",
    "ancient_apparition": "Ancient Apparition", "antimage": "Anti-Mage", "arc_warden": "Arc Warden",
    "axe": "Axe", "bane": "Bane", "batrider": "Batrider", "beastmaster": "Beastmaster",
    "bloodseeker": "Bloodseeker", "bounty_hunter": "Bounty Hunter", "brewmaster": "Brewmaster",
    "bristleback": "Bristleback", "broodmother": "Broodmother", "centaur": "Centaur Warrunner",
    "chaos_knight": "Chaos Knight", "chen": "Chen", "clinkz": "Clinkz", "rattletrap": "Clockwerk",
    "crystal_maiden": "Crystal Maiden", "dark_seer": "Dark Seer", "dark_willow": "Dark Willow",
    "dawnbreaker": "Dawnbreaker", "dazzle": "Dazzle", "death_prophet": "Death Prophet",
    "disruptor": "Disruptor", "doom_bringer": "Doom", "dragon_knight": "Dragon Knight",
    "drow_ranger": "Drow Ranger", "earth_spirit": "Earth Spirit", "earthshaker": "Earthshaker",
    "elder_titan": "Elder Titan", "ember_spirit": "Ember Spirit", "enchantress": "Enchantress",
    "enigma": "Enigma", "faceless_void": "Faceless Void", "grimstroke": "Grimstroke",
    "gyrocopter": "Gyrocopter", "hoodwink": "Hoodwink", "huskar": "Huskar", "invoker": "Invoker",
    "wisp": "Io", "jakiro": "Jakiro", "juggernaut": "Juggernaut", "keeper_of_the_light": "Keeper of the Light",
    "kez": "Kez", "kunkka": "Kunkka", "largo": "Largo", "legion_commander": "Legion Commander",
    "leshrac": "Leshrac", "lich": "Lich", "life_stealer": "Lifestealer", "lina": "Lina", "lion": "Lion",
    "lone_druid": "Lone Druid", "luna": "Luna", "lycan": "Lycan", "magnataur": "Magnus",
    "marci": "Marci", "mars": "Mars", "medusa": "Medusa", "meepo": "Meepo", "mirana": "Mirana",
    "monkey_king": "Monkey King", "morphling": "Morphling", "muerta": "Muerta",
    "naga_siren": "Naga Siren", "furion": "Nature's Prophet", "necrolyte": "Necrophos",
    "night_stalker": "Night Stalker", "nyx_assassin": "Nyx Assassin", "ogre_magi": "Ogre Magi",
    "omniknight": "Omniknight", "oracle": "Oracle", "obsidian_destroyer": "Outworld Destroyer",
    "pangolier": "Pangolier", "phantom_assassin": "Phantom Assassin", "phantom_lancer": "Phantom Lancer",
    "phoenix": "Phoenix", "primal_beast": "Primal Beast", "puck": "Puck", "pudge": "Pudge",
    "pugna": "Pugna", "queenofpain": "Queen of Pain", "razor": "Razor", "riki": "Riki",
    "ringmaster": "Ringmaster", "rubick": "Rubick", "sand_king": "Sand King",
    "shadow_demon": "Shadow Demon", "nevermore": "Shadow Fiend", "shadow_shaman": "Shadow Shaman",
    "silencer": "Silencer", "skywrath_mage": "Skywrath Mage", "slardar": "Slardar", "slark": "Slark",
    "snapfire": "Snapfire", "sniper": "Sniper", "spectre": "Spectre", "spirit_breaker": "Spirit Breaker",
    "storm_spirit": "Storm Spirit", "sven": "Sven", "techies": "Techies",
    "templar_assassin": "Templar Assassin", "terrorblade": "Terrorblade", "tidehunter": "Tidehunter",
    "shredder": "Timbersaw", "tinker": "Tinker", "tiny": "Tiny", "treant": "Treant Protector",
    "troll_warlord": "Troll Warlord", "tusk": "Tusk", "undying": "Undying", "ursa": "Ursa",
    "vengefulspirit": "Vengeful Spirit", "venomancer": "Venomancer", "viper": "Viper",
    "visage": "Visage", "void_spirit": "Void Spirit", "warlock": "Warlock", "weaver": "Weaver",
    "windrunner": "Windranger", "winter_wyvern": "Winter Wyvern", "witch_doctor": "Witch Doctor",
    "skeleton_king": "Wraith King", "zuus": "Zeus",
}


def _key(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


_BY_KEY = {_key(name): code for code, name in NAMES.items()}


def name(code: str | None) -> str:
    if not code:
        return "Неизвестный герой"
    return NAMES.get(code) or code.replace("_", " ").title()


def code_from_text(text: str) -> str | None:
    """Код героя по распознанному имени, с поправкой на ошибки OCR."""
    k = _key(text)
    if not k:
        return None
    if k in _BY_KEY:
        return _BY_KEY[k]
    match = difflib.get_close_matches(k, _BY_KEY.keys(), n=1, cutoff=0.72)
    return _BY_KEY[match[0]] if match else None
