DEFAULT_MAINS = [
    "Human",
    "Elf",
    "Dark Elf",
    "Dwarf",
    "Orc",
    "Kamael"
]

DEFAULT_SUBCLASSES = {
    "Human": [
        "Phoenix Knight",
        "Dreadnought",
        "Adventurer",
        "Sagittarius",
        "Archmage",
        "Cardinal"
    ],
    "Elf": [
        "Eva's Templar",
        "Sword Muse",
        "Windrider",
        "Moonlight Sentinel",
        "Mystic Muse",
        "Eva's Saint"
    ],
    "Dark Elf": [
        "Shillien Templar",
        "Spectral Dancer",
        "Ghost Hunter",
        "Ghost Sentinel",
        "Storm Screamer",
        "Shillien Saint"
    ],
    "Dwarf": [
        "Eternal Guardian",
        "War Slayer",
        "Bounty Hunter",
        "Warsmith",
        "Eldrich Wizard",
        "Master Sage"
    ],
    "Orc": [
        "Destroyer",
        "Bellator",
        "Tyrant",
        "Warcryer"
    ],
    "Kamael": [
        "Doombringer",
        "Trickster",
        "Soulhound",
        "Arcana"
    ]
}

async def initialize_default_classes(db):
    for main in DEFAULT_MAINS:
        await db.add_main(main)
    
    for main, subclasses in DEFAULT_SUBCLASSES.items():
        for subclass in subclasses:
            await db.add_subclass(main, subclass)
