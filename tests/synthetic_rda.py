#!/usr/bin/env python3
"""synthetic_rda — build a tiny, fake but structurally valid data1.rda.

The real game archive can't ship with the repo (and most test machines
don't have it), so without this almost every Session/GUI test skipped.
This module writes a ~10-character archive with the same members, XML
shapes and GUIDs the engine and the three personas rely on:

  * addondata/config/ai/aiprofiles.xml            (CSP assets, Relations)
  * addondata/config/balancing/addon_01_aiprofiles.xml
  * addondata/config/ai/properties.xml            (schema docs + defaults)
  * addondata/config/game/assets.xml              (a few EXTRAS assets)
  * addondata/config/game/randommapgenerator.xml  (<FertilityRates>)

It contains NO game data — every value is invented.

    from synthetic_rda import make_synthetic_rda
    make_synthetic_rda("/tmp/x/data1.rda")              # "vanilla"
    make_synthetic_rda("/tmp/x/modded.rda", variant=1)  # different md5
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from annoedit.rda import write_rda  # noqa: E402

EOL = "\r\n"

# guid -> (name, template). GUIDs match the ones the personas reference.
CHARACTERS = [
    ("1645006", "Lord Northburgh", "MediumCSP"),
    ("1645020", "Baronessa Constanza Zanchi", "HardCSP"),
    ("1645021", "Leif Jorgensen", "EasyCSP"),
    ("1645022", "Rufus Rumbleberg", "MediumCSP"),
    ("1645023", "Hildegard von Lewenstein", "EasyCSP"),
    ("1645024", "Cardinal Lucius", "HardCSP"),
    ("1645025", "Willem van der Mark", "EasyCSP"),
    ("1645026", "Giovanni Garibaldi", "HardCSP"),
    ("1645027", "Marie Guillaume", "MediumCSP"),
    ("1645028", "Edward Hawkins", "MediumCSP"),
]
ADDON_CHARACTERS = [
    ("1645100", "Doge of Venice", "HardCSP"),
]

# Per-character Relations overrides so the synthetic archive carries the
# same vanilla facts the real-data tests rely on, plus the risky shapes
#
#   * 1645021 Leif / 1645025 Willem: NO War list (real vanilla facts the
#     SessionRelationsTests rely on); Willem carries Trade+Ally+AvoidWar.
# * 1645027 Marie: a NON-CSP GUID (1650020) in a War list — the
#     shape: a GUID that is in the vanilla list but not in the CSP roster.
# * 1645022 Rufus: self-closed <Trade/> — the shape.
# Remaining characters keep the seed-based lists (1- and 2-item War lists:
# the "one-item list looks scalar" shape stays represented).
REL_OVERRIDES = {
    "1645021": {"War": None},
    "1645025": {"War": None, "Ally": ["1645026"], "AvoidWar": ["1645022"]},
    "1645027": {"War": ["1650020", "1645024"]},
}

# risky shape: Marie carries a NESTED same-name chain
# Diplomacy/CompetenceUsageRanges/TownAcquisition — so the descendant-axis
# engine bug (dial lands inside the nested block) is exercised on data.
NESTED_SAME_NAME = {"1645027"}
SELF_CLOSED_TRADE = {"1645022"}
# Rufus carries a scalar Flags leaf UNDER
# <Relationships> BEFORE <Relations> — the trigger (the old
# `<Relationships>\s*<Relations>` regex required Relations to be the
# FIRST child; the span walk must not).
F09_FRIEND_STATE = {"1645022"}
# Baronessa carries the dial shapes with real values
# Choice/Flags/Boolean/RealInt leaves the typed validators exercise.
F07_DIALS = {"1645020"}


def _asset(guid, name, template, seed, variant):
    i = int(guid) % 100 + variant * 7
    kinds = {"War": [g for g, _n, _t in CHARACTERS if g != guid][: (seed % 2) + 1],
             "Trade": [g for g, _n, _t in CHARACTERS if g != guid][-1:]}
    for k, v in REL_OVERRIDES.get(guid, {}).items():
        if v is None:
            kinds.pop(k, None)
        else:
            kinds[k] = v
    items = lambda gs: "".join(
        f"            <Item>{EOL}"
        f"              <ProfileGUID>{g}</ProfileGUID>{EOL}"
        f"            </Item>{EOL}" for g in gs)
    dip = ""
    if guid in NESTED_SAME_NAME:
        dip = (f"      <Diplomacy>{EOL}"
               f"        <CompetenceUsageRanges>{EOL}"
               f"          <TownAcquisition>{EOL}"
               f"            <Max>5</Max>{EOL}"
               f"          </TownAcquisition>{EOL}"
               f"        </CompetenceUsageRanges>{EOL}"
               f"      </Diplomacy>{EOL}")
    # (extra leaves are appended INSIDE the single category
    # blocks below — see build_extra/mil_extra/ship_extra/dip_extra.)
    # A scalar Flags leaf BEFORE <Relations> under
    # <Relationships> (Rufus) — the child-order-independent locate shape.
    friend = ""
    if guid in F09_FRIEND_STATE:
        friend = (f"        <FriendState>PeaceTreaty;TradeTreaty</FriendState>{EOL}"
                  f"        <RivalState>War;PeaceTreaty</RivalState>{EOL}")
    rel_blocks = []
    for kind in ("War", "Ally", "Trade", "AvoidWar"):
        if kind not in kinds:
            continue
        if kind == "Trade" and guid in SELF_CLOSED_TRADE:
            rel_blocks.append(f"          <Trade/>{EOL}")
            continue
        rel_blocks.append(
            f"          <{kind}>{EOL}"
            f"            <Profiles>{EOL}{items(kinds[kind])}            </Profiles>{EOL}"
            f"          </{kind}>{EOL}")
    # Real-typed EXTRA leaves on Baronessa, appended INSIDE
    # the existing single category blocks (a second block would be ambiguous
    # — the child-axis engine refuses 2 <ShipFight> at the same level).
    # Values mirror real vanilla spellings (Choice 'Patrician', Flags
    # 'War;PeaceTreaty', Boolean 'true', RealInt 204800).
    if guid in F07_DIALS:
        build_extra = (f"        <MaxCivilizationLevel>Patrician</MaxCivilizationLevel>{EOL}")
        mil_extra = (f"        <BuildSupplyDepot>true</BuildSupplyDepot>{EOL}")
        ship_extra = (f"        <CallForHelpRange>204800</CallForHelpRange>{EOL}")
        dip_extra = (f"      <Diplomacy>{EOL}"
                    f"        <TreatyForIntimidate>War;PeaceTreaty</TreatyForIntimidate>{EOL}"
                    f"      </Diplomacy>{EOL}")
    else:
        build_extra = mil_extra = ship_extra = dip_extra = ""
    return (
        f"  <Asset>{EOL}"
        f"    <Template>{template}</Template>{EOL}"
        f"    <Values>{EOL}"
        f"      <Build>{EOL}"
        f"        <BuildingSpeed>{50 + i}</BuildingSpeed>{EOL}"
        f"        <TowersPerLevel>{2 + seed % 3}</TowersPerLevel>{EOL}"
        f"{build_extra}"
        f"      </Build>{EOL}"
        f"      <Military>{EOL}"
        f"        <MaxUnitCount>{20 + i}</MaxUnitCount>{EOL}"
        f"        <AttackDelay>{60000 + 1000 * seed}</AttackDelay>{EOL}"
        f"{mil_extra}"
        f"      </Military>{EOL}"
        f"      <ShipFight>{EOL}"
        f"        <ShipAttackIntervall>{90000 - 1000 * seed}</ShipAttackIntervall>{EOL}"
        f"{ship_extra}"
        f"      </ShipFight>{EOL}"
        f"      <Espionage>{EOL}"
        f"        <SpyDetectValue>{10 + seed}</SpyDetectValue>{EOL}"
        f"      </Espionage>{EOL}"
        f"{dip}"
        f"{dip_extra}"
        f"      <Relationships>{EOL}"
        f"{friend}"
        f"        <Relations>{EOL}{''.join(rel_blocks)}"
        f"        </Relations>{EOL}"
        f"        <SpecialProfiles>{EOL}"
        f"        </SpecialProfiles>{EOL}"
        f"      </Relationships>{EOL}"
        f"    </Values>{EOL}"
        f"    <Standard>{EOL}"
        f"      <Name>{name}</Name>{EOL}"
        f"      <GUID>{guid}</GUID>{EOL}"
        f"    </Standard>{EOL}"
        f"  </Asset>{EOL}")


def _profiles_xml(chars, variant):
    body = "".join(_asset(g, n, t, k, variant)
                   for k, (g, n, t) in enumerate(chars))
    return f"<Assets>{EOL}{body}</Assets>{EOL}"


SCHEMA = (
    "<Properties>" + EOL +
    "  <DefaultValues>" + EOL +
    "    <Build><BuildingSpeed>100</BuildingSpeed><TowersPerLevel>3</TowersPerLevel>"
    "<ColonizeDelayTime>120000</ColonizeDelayTime></Build>" + EOL +
    "    <Military><MaxUnitCount>40</MaxUnitCount><AttackDelay>90000</AttackDelay>"
    "<FleeHealth>30</FleeHealth></Military>" + EOL +
    "    <ShipFight><ShipAttackIntervall>120000</ShipAttackIntervall>"
    "<ShipAmountPerLevel>4</ShipAmountPerLevel></ShipFight>" + EOL +
    "    <Espionage><SpyDetectValue>20</SpyDetectValue>"
    "<Prop_Thief>10</Prop_Thief></Espionage>" + EOL +
    "  </DefaultValues>" + EOL +
    "  <Group>" + EOL +
    "".join(
        f"    <Property><Name>{cat}</Name>"
        + "".join(
            vd
            for vd in dial_defs)
        + "</Property>" + EOL
        for cat, dial_defs in (
            ("Build", [(f"<ValueDefinition><Name>BuildingSpeed</Name>"
                        "<DataType>Integer</DataType>"
                        "<Description>Synthetic test dial</Description>"
                        "<Min>0</Min><Max>200</Max></ValueDefinition>"),
                       (f"<ValueDefinition><Name>TowersPerLevel</Name>"
                        "<DataType>Integer</DataType>"
                        "<Description>Synthetic test dial</Description>"
                        "<Min>0</Min><Max>20</Max></ValueDefinition>"),
                       ("<ValueDefinition><Name>ColonizeDelayTime</Name>"
                        "<DataType>Time</DataType>"
                        "<Description>Synthetic test dial</Description>"
                        "<Min>0</Min><Max>600000</Max></ValueDefinition>"),
                       # Real types — Choice w/ DataSet
                       ("<ValueDefinition><Name>MaxCivilizationLevel</Name>"
                        "<DataType>Choice</DataType>"
                        "<Description>Max civ level</Description>"
                        "<DataSet>ResidentLevel</DataSet></ValueDefinition>")]),
            ("Military", [("<ValueDefinition><Name>MaxUnitCount</Name>"
                          "<DataType>Integer</DataType>"
                          "<Description>Synthetic test dial</Description>"
                          "<Min>0</Min><Max>100</Max></ValueDefinition>"),
                          ("<ValueDefinition><Name>AttackDelay</Name>"
                           "<DataType>Time</DataType>"
                           "<Description>Synthetic test dial</Description>"
                           "<Min>0</Min><Max>600000</Max></ValueDefinition>"),
                          ("<ValueDefinition><Name>FleeHealth</Name>"
                           "<DataType>Integer</DataType>"
                           "<Description>Synthetic test dial</Description>"
                           "<Min>0</Min><Max>100</Max></ValueDefinition>"),
                          # Boolean (digit spelling in profiles)
                          ("<ValueDefinition><Name>BuildSupplyDepot</Name>"
                           "<DataType>Boolean</DataType>"
                           "<Description>Build depots</Description>"
                           "</ValueDefinition>")]),
            ("ShipFight", [("<ValueDefinition><Name>ShipAttackIntervall</Name>"
                            "<DataType>Time</DataType>"
                            "<Description>Synthetic test dial</Description>"
                            "<Min>0</Min><Max>600000</Max></ValueDefinition>"),
                           ("<ValueDefinition><Name>ShipAmountPerLevel</Name>"
                            "<DataType>Integer</DataType>"
                            "<Description>Synthetic test dial</Description>"
                            "<Min>0</Min><Max>30</Max></ValueDefinition>"),
                           # RealInt (fixed-point, NEVER decimal)
                           ("<ValueDefinition><Name>CallForHelpRange</Name>"
                            "<DataType>RealInt</DataType>"
                            "<Description>Call for help radius</Description>"
                            "</ValueDefinition>")]),
            ("Espionage", [("<ValueDefinition><Name>SpyDetectValue</Name>"
                            "<DataType>Integer</DataType>"
                            "<Description>Synthetic test dial</Description>"
                            "<Min>0</Min><Max>50</Max></ValueDefinition>"),
                           ("<ValueDefinition><Name>Prop_Thief</Name>"
                            "<DataType>Integer</DataType>"
                            "<Description>Synthetic test dial</Description>"
                            "<Min>0</Min><Max>100</Max></ValueDefinition>"),
                           # Text = read-only
                           ("<ValueDefinition><Name>Prop_Decoy</Name>"
                            "<DataType>Text</DataType>"
                            "<Description>Read-only text dial</Description>"
                            "</ValueDefinition>")]),
            ("Diplomacy", ["<ValueDefinition><Name>TreatyForIntimidate</Name>"
                           "<DataType>Flags</DataType>"
                           "<Description>Treaties for intimidation</Description>"
                           "<DataSet>Treaty</DataSet></ValueDefinition>"]),
            ("Relationships", ["<ValueDefinition><Name>FriendState</Name>"
                              "<DataType>Flags</DataType>"
                              "<Description>Friend states</Description>"
                              "<DataSet>Treaty</DataSet></ValueDefinition>",
                              "<ValueDefinition><Name>RivalState</Name>"
                              "<DataType>Flags</DataType>"
                              "<Description>Rival states</Description>"
                              "<DataSet>Treaty</DataSet></ValueDefinition>"]),
        )) +
    "  </Group>" + EOL +
    "</Properties>" + EOL)


# The Choice/Flags enumerations — a mini datasets.xml with
# the real file's shape (DataSet -> Items -> Item -> Name). Matches real
# vanilla spellings (War/PeaceTreaty/TradeTreaty/AllianceTreaty,
# ResidentLevel Outlaw..Nobleman).
DATASETS_XML = (
    "<DataSets>" + EOL +
    "  <DataSet>" + EOL +
    "    <Name>Treaty</Name>" + EOL +
    "    <Items>" + EOL +
    "".join(f"      <Item><Name>{n}</Name></Item>{EOL}" for n in
            ("None", "War", "PeaceTreaty", "TradeTreaty", "AllianceTreaty")) +
    "    </Items>" + EOL +
    "  </DataSet>" + EOL +
    "  <DataSet>" + EOL +
    "    <Name>ResidentLevel</Name>" + EOL +
    "    <Items>" + EOL +
    "".join(f"      <Item><Name>{n}</Name></Item>{EOL}" for n in
            ("Outlaw", "Beggar_on_street", "Ruin_of_ambassador", "Nomad",
             "Ambassador", "Ruin_of_peasant", "Peasant", "Citizen",
             "Patrician", "Nobleman")) +
    "    </Items>" + EOL +
    "  </DataSet>" + EOL +
    "</DataSets>" + EOL)


def _assets_xml(variant):
    def a(name, guid, inner):
        return (f"  <Asset>{EOL}    <Template>Building</Template>{EOL}"
                f"    <Values>{EOL}{inner}    </Values>{EOL}"
                f"    <Standard>{EOL}      <Name>{name}</Name>{EOL}"
                f"      <GUID>{guid}</GUID>{EOL}    </Standard>{EOL}  </Asset>{EOL}")
    return ("<Assets>" + EOL
            + a("Warehouse01", 1001,
                f"      <PassiveTradeSlots>{4 + variant}</PassiveTradeSlots>{EOL}"
                f"      <Capacity>30</Capacity>{EOL}")
            # Real assets.xml shapes — ProductionTime lives
            # inside <WareProduction> (first child), never directly
            # under <Values>; PrintingHouse has WareProduction but NO
            # ProductionTime (the INSERT case)
            + a("Bakery", 1002,
                f"      <WareProduction>{EOL}"
                f"        <ProductionTime>40000</ProductionTime>{EOL}"
                f"        <Product>Bread</Product>{EOL}"
                f"      </WareProduction>{EOL}"
                f"      <MoneyCost>15</MoneyCost>{EOL}")
            + a("PrintingHouse", 1003,
                f"      <WareProduction>{EOL}"
                f"        <Product>Book</Product>{EOL}"
                f"      </WareProduction>{EOL}"
                f"      <MoneyCost>40</MoneyCost>{EOL}")
            + a("Mill", 1005,
                f"      <WareProduction>{EOL}"
                f"        <ProductionTime>40000</ProductionTime>{EOL}"
                f"      </WareProduction>{EOL}"
                f"      <MoneyCost>15</MoneyCost>{EOL}")
            + a("Noria", 1004,
                f"      <NoriaEndRadius>8</NoriaEndRadius>{EOL}"
                f"      <NoriaEndRadius>10</NoriaEndRadius>{EOL}")
            # duplicate NAME, distinct GUID (ambiguous-asset
            # shape — find_asset must demand 'Name [GUID]' addressing)
            + a("Warehouse01", 204391,
                f"      <PassiveTradeSlots>6</PassiveTradeSlots>{EOL}"
                f"      <Capacity>25</Capacity>{EOL}")
            + "</Assets>" + EOL)


def _fert_xml():
    north = ("Cider", "Hemp", "Wheat", "Herbs", "Grape", "Bees")
    crops = ("Almond", "Bees", "Cider", "Clay", "Coffee", "Dates", "Grape",
             "Hemp", "Herbs", "Indigo", "Rose", "Silk", "Spices",
             "Sugarcane", "Wheat", "Wildcard")
    tiers = []
    for tier, pct in (("low", 60), ("medium", 50), ("high", 70)):
        entries = "".join(
            f"<k><Fertility>{c}</Fertility></k><v><North>"
            f"{pct if c in north or c == 'Wildcard' else 0}</North><South>"
            f"{0 if c in north else pct}</South></v>{EOL}" for c in crops)
        tiers.append(f"<k><ResourceAmount>{tier}</ResourceAmount></k>{EOL}"
                     f"<v>{EOL}{entries}</v>{EOL}")
    return (f"<RandomMapGenerator>{EOL}<WorldSizes>CDATA[binary]</WorldSizes>{EOL}"
            f"<FertilityRates>{EOL}{''.join(tiers)}</FertilityRates>{EOL}"
            f"</RandomMapGenerator>{EOL}")


def make_synthetic_rda(path, variant=0):
    """Write the synthetic archive to path. variant != 0 = different bytes."""
    ts = 1700000000
    entries = {
        "addondata/config/ai/aiprofiles.xml":
            (_profiles_xml(CHARACTERS, variant).encode("utf-8"), ts),
        "addondata/config/balancing/addon_01_aiprofiles.xml":
            (_profiles_xml(ADDON_CHARACTERS, variant).encode("utf-8"), ts),
        "addondata/config/ai/properties.xml": (SCHEMA.encode("utf-8"), ts),
        # Choice/Flags enumerations (datasets.xml member)
        "addondata/config/game/datasets.xml":
            (DATASETS_XML.encode("utf-8"), ts),
        "addondata/config/game/assets.xml":
            (_assets_xml(variant).encode("cp1252"), ts),
        "addondata/config/game/randommapgenerator.xml":
            (_fert_xml().encode("cp1252"), ts),
        "data/readme.txt": (b"synthetic test archive - no game data", ts),
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    write_rda(entries, path)
    return path


if __name__ == "__main__":
    print(make_synthetic_rda(sys.argv[1] if len(sys.argv) > 1 else
                             "synthetic_data1.rda"))
