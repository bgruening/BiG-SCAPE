"""Contains constant values"""
DB_SCHEMA_PATH = "big_scape/data/schema.sql"
PROFILER_UPDATE_INTERVAL = 0.5

MIN_LCS_LEN = 3
MIN_EXPAND_LEN = 5

EXPAND_MATCH_SCORE = 5
EXPAND_MISMATCH_SCORE = -3
EXPAND_GAP_SCORE = -2
EXPAND_MAX_MATCH_PERC = 0.1

LEGACY_ANCHOR_DOMAINS = [
    "PF02801",
    "PF02624",
    "PF00109",
    "PF00501",
    "PF02797",
    "PF01397",
    "PF03936",
    "PF00432",
    "PF00195",
    "PF00494",
    "PF00668",
    "PF05147",
]

# according with current (2021-05) antiSMASH rules:
# prodigiosin and PpyS-KS -> PKS
# CDPS -> NRPS
ANTISMASH_CLASSES = {
    "pks1_products": ["t1pks", "T1PKS"],
    "pksother_products": [
        "transatpks",
        "t2pks",
        "t3pks",
        "otherks",
        "hglks",
        "transAT-PKS",
        "transAT-PKS-like",
        "T2PKS",
        "T3PKS",
        "PKS-like",
        "hglE-KS",
    ],
    "nrps_products": ["nrps", "NRPS", "NRPS-like", "thioamide-NRP", "NAPAA"],
    "ripps_products": [
        "lantipeptide",
        "thiopeptide",
        "bacteriocin",
        "linaridin",
        "cyanobactin",
        "glycocin",
        "LAP",
        "lassopeptide",
        "sactipeptide",
        "bottromycin",
        "head_to_tail",
        "microcin",
        "microviridin",
        "proteusin",
        "lanthipeptide",
        "lipolanthine",
        "RaS-RiPP",
        "fungal-RiPP",
        "TfuA-related",
        "guanidinotides",
        "RiPP-like",
        "lanthipeptide-class-i",
        "lanthipeptide-class-ii",
        "lanthipeptide-class-iii",
        "lanthipeptide-class-iv",
        "lanthipeptide-class-v",
        "ranthipeptide",
        "redox-cofactor",
        "thioamitides",
        "epipeptide",
        "cyclic-lactone-autoinducer",
        "spliceotide",
        "RRE-containing",
    ],
    "saccharide_products": [
        "amglyccycl",
        "oligosaccharide",
        "cf_saccharide",
        "saccharide",
    ],
    "others_products": [
        "acyl_amino_acids",
        "arylpolyene",
        "aminocoumarin",
        "ectoine",
        "butyrolactone",
        "nucleoside",
        "melanin",
        "phosphoglycolipid",
        "phenazine",
        "phosphonate",
        "other",
        "cf_putative",
        "resorcinol",
        "indole",
        "ladderane",
        "PUFA",
        "furan",
        "hserlactone",
        "fused",
        "cf_fatty_acid",
        "siderophore",
        "blactam",
        "fatty_acid",
        "PpyS-KS",
        "CDPS",
        "betalactone",
        "PBDE",
        "tropodithietic-acid",
        "NAGGN",
        "halogenated",
        "pyrrolidine",
    ],
}
