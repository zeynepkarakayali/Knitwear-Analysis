"""Constants shared by cleaning, analysis, figures and the dashboard (same definitions as notebook 01)."""

# fibre columns of the clean tables ("<fibre>_pct"); other_animal = yak, camel, angora, vicuna
FIBRES = ["other_animal", "cashmere", "mohair", "alpaca", "wool", "silk", "cotton", "linen",
          "lyocell", "modal", "viscose", "acetate", "polyamide", "acrylic", "elastane", "polyester", "other"]
PCT = [f + "_pct" for f in FIBRES]

# fibre groups -> group column (percent of the garment)
FIBRE_GROUPS = {
    "animal_pct": ["wool", "cashmere", "mohair", "alpaca", "silk", "other_animal"],
    "plant_pct": ["cotton", "linen"],
    "cellulosic_pct": ["viscose", "lyocell", "modal", "acetate"],
    "synthetic_pct": ["polyester", "acrylic", "polyamide", "elastane"],
    "other_group_pct": ["other"],
}
# fibre order used in heatmaps (grouped: animal | plant | cellulosic | synthetic | other)
FIB_ORDER = ["wool", "cashmere", "mohair", "alpaca", "silk", "other_animal", "cotton", "linen",
             "viscose", "lyocell", "modal", "acetate", "polyester", "acrylic", "polyamide", "elastane", "other"]

SEGMENT = {"Zara": "Fast fashion", "Mango": "Fast fashion", "H&M": "Fast fashion", "Bershka": "Fast fashion",
           "UNIQLO": "Mid/premium", "COS": "Mid/premium", "& Other Stories": "Mid/premium",
           "Massimo Dutti": "Mid/premium"}
# brands grouped by segment (fast fashion first), used in heatmaps
BRAND_ORDER = ["H&M", "Bershka", "Mango", "Zara", "UNIQLO", "& Other Stories", "Massimo Dutti", "COS"]
SHORT = {"& Other Stories": "&OS", "Massimo Dutti": "M. Dutti"}

# where a sustainability claim can be read, per brand ("none captured" -> claims are unknown, not "no claim")
CLAIM_SOURCE = {"Zara": "sustainability field", "Massimo Dutti": "sustainability field", "Bershka": "sustainability field",
                "& Other Stories": "sustainability field", "UNIQLO": "sustainability field",
                "Mango": "composition text", "COS": "description", "H&M": "none captured"}
SUST_BRANDS = [b for b, s in CLAIM_SOURCE.items() if s != "none captured"]

# product names that mention an animal fibre (Q3); merino counts as wool
NAMED_FIBRES = {"wool": r"wool|merino", "cashmere": r"cashmere", "mohair": r"mohair", "alpaca": r"alpaca"}
