<!--
  GENERATED FILE — do not edit by hand.
  Regenerate with:
      python3 tools/gen_glossary.py <path/to/data1.rda> docs/technical/dial_glossary.md
  The definitions come from the game's own AI schema
  (addondata/config/ai/properties.xml); German descriptions are the
  developers' original text.
-->

# Dial glossary — every AI dial documented by the game itself

Every dial the game defines for AI character profiles, with its type, value
range, schema default, and the developers' (German) description. Grouped by
category. Paths shown as `Category/Dial` (nested: `Category/Sub/Dial`).


Source archive: a vanilla `addon/data1.rda` (local file: data1.rda)

Dials documented: **23 categories**, **394 dials**.


## Audio

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Audio/AudioGUIDOffset` | Integer | — | — | Offest der für dieses Profil auf jede Audio-GUID addiert wird. |
| `Audio/AudioPools` | Array | — | — | Vom Profil verwendete Audio-Pools. |
| `Audio/MaxGUID` | Integer | — | — |  |
| `Audio/MinGUID` | Integer | — | — |  |

## Balancing

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Balancing/AudioPriorities` | Array | — | — | Prioritäten der einzelnen Audio Kategorien. |
| `Balancing/Category` | Choice | — | — |  |
| `Balancing/CompetenceGrayZone` | Array | — | — | Grauzonen der einzelnen Kopetenzvergleichswerte. Innerhalb dieser Grauzone wird kein "Übergewicht" berechnet. Bsp. Ships Player1: 2; Ships Player 2: 4; GreyZone: 2; CompetenceResult: 0% |
| `Balancing/CompetenceIntervall` | Time | — | 60000 | Intervall in welchem der Kopetenzvergleich aktualisiert wird. Nicht zu verwechseln mit dem Intervall in welchem sich das Profil bezüglich vergleichend meldet. |
| `Balancing/EscortMaxDistance` | RealInt | — | 20480 | Maximaler Abstand der Eskortierenden Schiffe zum Eskortziel. |
| `Balancing/EscortTargetDistance` | RealInt | — | 8192 | Maximaler Abstand der Eskortierenden Schiffe zum Eskortziel. |
| `Balancing/EscortTimeOffset` | Time | — | 15000 | Die Eskorte fährt immer zum Zielpunkt in dieser Zeit, also beispielsweise heißt 5 Sekunden dass die Eskorte zu dem Punkt fährt an dem das Ziel-Schiff in 5 Sekunden sein wird. Wenn das Schiff nicht fährt wird die EscortTargetDistance genommen |
| `Balancing/MaxCompetenceResult` | Integer | — | 500 | Maximales Ergebnis eines einzelnen Kompetenzvergleichswertes und des kompletten Kompetenzvergleichs (in Prozent). |
| `Balancing/MaxRunningQuestPools` | Array | — | — | Wie viele Questpools dürfen parallel Quests ausschreiben (pro ZivStufe) |
| `Balancing/MessageCategories` | Array | — | — | Kategorie der einzelnen Meldungen. Wird zur Unterteilung der Meldungen im Tab Messsages verwendet. |
| `Balancing/MinBankBookMoney` | Integer | — | 2000 | Minimales Vermögen, um Geld in ein BankBook einzuzahlen (PropertyBuild->BankBooks) |
| `Balancing/OfferTreatyCooldown` | Time | — | 3600000 | Wie lange wartet ein Profil bis er den gleichen Vertrag nochmals anbietet nachdem dieser vom Spieler abgelehnt wurde. |
| `Balancing/RelationStrength` | Array | — | — | Rufbonus der in jedem Regressionsintervall addiert wird. |
| `Balancing/ShipGroupDistanceToCenter` | RealInt | — | 20480 | Größe einer Schiffgruppe vom Zentrum aus betrachtet |
| `Balancing/ShipGroupDistanceToNeighbour` | RealInt | — | 40960 | Abstand zwischen Schiffen in einer Schiffsgruppe |
| `Balancing/ShipTaskPriorities` | Array | — | — | Prioritäten der verschiedenen Schiffsaufgaben der KI. |
| `Balancing/TradeReactionsGoldAmount` | Integer | — | 1000 | In welchem Warenwert-Intervall werden die TRADED_WITh-Nachrichten getriggert |
| `Balancing/UseGroupMovement` | Boolean | — | 1 | Wenn auf TRUE gesetzt, nutzen Schiffsgruppen die Gruppenbewegung |

## Build

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Build/BankBooks` | Array | — | — | Sparbücher der KI für bestimmte Investitionen. Kann jeweils pro ZivStufe angegeben werden. |
| `Build/BuildingSpeed` | Integer | — | 100 | Relative Baugeschwindigkeit in Prozent! |
| `Build/CheatResources` | Boolean | — | 1 | Wenn auf TRUE gesetzt, cheatet die AI Ressourcen. |
| `Build/ColonizeDelayTime` | Time | — | — | Zeitdauer nach Spielbeginn zur Verzögerung der Inselbesiedlung durch KI |
| `Build/DecorationPerLevel` | Array | — | — | Dekorationselemente pro ZivStufe |
| `Build/IsBeautyBuilder` | Boolean | — | — | Gibt an, ob die KI ein Schönbauer ist und ob die Dekorationspattern stärker vertreten sind (nicht verwendet) |
| `Build/IsConceptBuilder` | Boolean | — | — | Ist die KI ein statischer Bautyp |
| `Build/IslandDetectionNeutralBuilding` | Boolean | — | — | Bei der Inselbesiedelung werden die neutralen Gebaeude mitbewertet |
| `Build/KontorRebuildDelay` | Time | — | 300000 | Menschliches Versagen eingebaut. Wie lange die KI mind. warten soll, bis das Kontor wiederaufgebaut werden soll |
| `Build/LimitToPlayer` | Boolean | — | — | Ist die KI an die aktuelle Zivilisationsstufe des Spielers gebunden? |
| `Build/MarketHouseRebuildDelay` | Time | — | 300000 | Menschliches Versagen eingebaut. Wie lange die KI mind. warten soll, bis das Warenhaus wiederaufgebaut werden soll |
| `Build/MaxCivilizationLevel` | Choice | — | Outlaw | Maximale Zivilisationsstufe bis zu welcher das Profil aufsteigt |
| `Build/MaxEspionageBuildings` | Integer | 0..99 | 20 | Maximum amount of espionage bases build by the AI |
| `Build/MaxOverproductionfactor` | Array | — | — | Maximal erlaubte Überprodujtion. Falls mehr produziert wird, werden Produktionsketten abgerissen. |
| `Build/MaxValuePerLevel` | Array | — | — | maximum money in bankbook for each level |
| `Build/MinCapitalStock` | Integer | 0..100000 | 5000 | Höhe des Grundkapitals, wird immer dann hinzugefuegt, wenn der Wert unter 1000 Gold faellt. |
| `Build/MinWareAddition` | Integer | 0..10 | 3 | Menge in Tonnen einer Ware, die im obigen Intervall ercheatet wird. |
| `Build/MinWareIntervall` | Time | — | 120000 | Intervall in dem Waren bei Unterschreiten der Grenze ercheatet werden. |
| `Build/MinWareStock` | Integer | 0..50 | 25 | Untergrenze in Tonnen an benötigter Endwaren/Baumaterialien auf einer Insel. Beim Unterschreiten darf die entsprechende Ware ercheatet werden. |
| `Build/NomadStartLevel` | Choice | — | Outlaw | Level, ab wann die Ki anfängt Nomaden anzusiedeln! |
| `Build/NomadbyLevel` | Array | — | — | Wieviele Nomadenhäuser baut die KI pro Stufe. ACHTUNG: Aufstiegsbeschränkungen für Gesandte beachten. |
| `Build/Overproductionfactor` | Array | — | — | Überproduktion der KI für einzelne Produkte. 100% bedeutet, dass die KI exakt soviel produziert, wie sie verbraucht! |
| `Build/PercentageOfBalance` | Integer | — | — | percentage of balance added to bankbook each minute |
| `Build/RepairTowerCount` | Integer | 1..3 | 1 | Anzahl an Reparaturkränen, die eine KI baut. |
| `Build/ResidentByLevel` | Array | — | — | Wieviele Wohnhäuser (Gesamtanzahl) darf die KI auf der betreffenden Stufe maximal haben? |
| `Build/ResidentUpgradeCount` | Integer | — | 8 | Min/Max Anzahl Häuser pro Aufstiegsintervall und pro Stufe |
| `Build/Resoluteness` | Boolean | — | — | Entscheidung der KI, ob sie Inseln, die anderen gehören, bei der Inselwahl berücksichtigt |
| `Build/SpecialPatternList` | Integer | — | — | Liste an Spezialpatterns, die die KI baut. |
| `Build/StartMarkethouseCount` | Integer | — | 1 | wieviele Markthäuser setzt das Profil maximal direkt bei der Inselbesiedlung um diese abzusichern (unabhängig von der Anzahl Markthäuser beim normalen Aufbau) |
| `Build/StopProductionValue` | Integer | — | 80 | Schwellenwert Überschuss Produktion zum Stilllegen von Betrieben. Angegeben im relativen Bezug auf die Kapazität des Warenlagers. Angegeben in % |
| `Build/TaxMultiplier` | Integer | — | — | 100% = exakt der Wert, den der Spieler auch bekommt. Die Werte sind in Prozent angegeben! |
| `Build/TowersPerLevel` | Integer | — | — | Anzahl Türme pro ZivStufe (Wert wird nicht mehr verwendet) |
| `Build/TransportRouteProductPriority` | Array | — | — | Priorität verschiedenener Waren für Transportrouten. |
| `Build/UpgradeDelayTime` | Time | — | 300000 | Gibt eine Zeitspanne an, wie lange die KI noch brauchen wird, bis sie aufsteigt, wenn ein anderer Spieler aufgestiegen istund das Flag LimitToPlayer aktiv ist |

## BuyShips

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `BuyShips/BuyCorsairShips` | Boolean | — | 1 | Wenn auf true gesetzt kauft die KI auch Korsarenschiffe |
| `BuyShips/MaxBuyShipPricePercentage` | Integer | — | 30 | Wieviel Prozent ihres Geldes gibt die KI maximal für ein Schiff aus. |

## Diplomacy

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Diplomacy/BegForPeaceAmountPercentage` | Integer | — | 200 | Wieviel Prozent eines normalen Tributs zahlt der CSP für den Frieden |
| `Diplomacy/BegForPeaceCooldown` | Time | — | 3600000 | Wie lange wird nicht mehr um Frieden gebettelt nachdem das einmal getan wurde |
| `Diplomacy/ChangeTreatyShift` | Time | — | 30000 | Wie lange darf der CSP keine Verträge anbieten/auslösen nach einer Rufänderung |
| `Diplomacy/CheckAssistanceIntervall` | Time | — | 3600000 | In welchem Intervall wird geprüft ob die KI in einen Krieg eines Bündnispartners miteintritt |
| `Diplomacy/CheckMilitarySupportIntervall` | Time | — | — | In welchem Intervall wird geprüft ob die KI um Hilfe rufen soll(nur im Krieg). Wenn auf 0 gesetzt benutzt die KI die Hilfe nie. |
| `Diplomacy/CheckTroopsIntervall` | Time | — | 1200000 | Intervall, nach welchem das Profil nach fremden Truppen auf der eigenen Insel sucht. Werden Truppen entdeckt, wird die Meldung TROUPS_IN_INFLUENCE getriggert. |
| `Diplomacy/CompetenceType` | Choice | — | — |  |
| `Diplomacy/CompetenceUsageRanges` | Array | — | — | Entscheidungen, die durch die Ergebnisse eines Kompetenzvergleichs getroffen werden. Befindet sich der Vergleichswert innerhalb des eingestellten Intervalls, ist die Entscheidung positiv. Negativer Wert bedeutet, Profil ist um den entsprechenden Betrag unterlegen. Positiver Wert bedeutet, Profil ist um den entsprechenden Betrag überlegen. *** Min: Wert (zwischen -500 und +500), der mindestens verlangt wird *** Max: Wert (zwischen -500 und +500), der maximal verlangt wird *** CompetenceType: Art von Kompetenzvergleich, die für den entsprechenden Fall benutzt wird |
| `Diplomacy/CompetenceWeights` | Matrix | — | — | Gewichtung der jeweiligen Faktoren für die verschiedenen Vergleichsarten. Das Profil vergleicht sich mit dem Spieler und erhält gemäß der Gewichtungen ein bestimmtes Ergebnis, aus welchem die KI das weitere Vorgehen ableitet. *** Normal: Normaler Kompetenzvergleich *** Military: Militärischer Kompetenzvergleich *** Buildings: Anzahl der Gebäude *** MilitaryBuildings: Anzahl der Militärgebäude *** TradingShips: Anzahl Handelsschiffe *** MilitaryShips: Anzahl Kriegsschiffe *** Ressources: Anzahl Ressourcen unter Kontrolle, sprich im Einflußbereich *** Fertilities: Anzahl Fruchtbarkeiten unter Kontrolle, sprich im Einflußbereich *** NeutralBuildings: Anzahl Neutraler Gebäude unter Kontrolle *** GoldAmount: Höhe des Goldvermögens *** CivilizationLevel: Zivilisationsstufenvorsprung *** Peasant: Anzahl an Bauern in der Bevölkerung *** Citizen: Anzahl an Bürgern in der Bevölkerung *** Patrician: Anzahl an Patriziern *** Nobleman: Anzahl an Adligen *** Honour: Anzahl an Ruhmpunkten *** Enemies: Anzahlan Feinden (Mitspieler mit denen Krieg herrscht) *** Allies: Anzahl Verbündeter (Mitspieler mit denen Bündnis herrscht) *** Disaster: Katastrophe wütet vor einer bestimmten Zeitdauer *** Talents: Anzahl freigeschalteter Talentstufen |
| `Diplomacy/Cooldown` | Time | — | — | Dauer, bis die Wahrscheinlichkeit nach einer Ausführung wieder auf das Maximum angestiegen ist. |
| `Diplomacy/CorsairTreatyMaxCost` | Integer | — | 10 | Wieviel darf der Korsarenvertrag maximal kosten, in Prozent vom aktuellen Vermögen. |
| `Diplomacy/CorsairTreatyPercentage` | Integer | — | — | Zu welcher Wahrscheinlichkeit geht die KI einen Vertrag mit den korsaren ein |
| `Diplomacy/CreditAmountPercentage` | Integer | — | 100 | Wieviel % des Standard-Werts verschenkt die KI bei einem Geldgeschenk |
| `Diplomacy/DeclareWarMinPlayTime` | Time | — | 3600000 | Wie lange muss das Spiel mindestens laufen bis die KI den Krieg erklärt |
| `Diplomacy/DiplomacyBehaviour` | Array | — | — | Diplomatie-Optionen aus dem Diplomatie-Menü. Zugehörige Cooldowns und Wahrscheinlichkeiten. |
| `Diplomacy/DiscoverPlayers` | Boolean | — | — | nur wenn der Wert auf true gesetzt wird entdeckt die KI auch andere Spieler. Ansonsten muss der Spieler die KI selbst aufdecken |
| `Diplomacy/ExecuteAssistanceVersusFriend` | Boolean | — | — | Wenn auf false gestellt tritt diese KI keinem Krieg mit einem ihrer Freunde bei |
| `Diplomacy/ExplorationCooldown` | Time | — | 900000 | Wie lange werden diplomatische Atkionen nach der Entdeckung geblockt. Außer rufbedingte Vertragsangebote. |
| `Diplomacy/IceAgeDuration` | Time | — | 900000 | Dauer der Eiszeit nach Krieg. |
| `Diplomacy/IngratiateCooldown` | Time | — | — | In welchem Intervall schmeichelt die KI sich ggf. beim Spieler ein |
| `Diplomacy/IntimidateCooldown` | Time | — | — | In welchem Zeitintervall prüft die KI ob sie einen Spieler beleidigen soll |
| `Diplomacy/IsCrazyIntervall` | Time | — | 3600000 | In welchem Intervall wird geprüft ob die KI den Krieg erklären soll weil sie stark genug dafür ist |
| `Diplomacy/LongTreatyRegressions` | Array | — | — | Rufregression ab einer bestimmten Länge eiens bestimmten Vertrags- bzw. Paktzustandes |
| `Diplomacy/Max` | Integer | — | — |  |
| `Diplomacy/MaxMoneyToOfferCredit` | Array | — | — | Pro Stufe die Maximalgrenze des Geldes dass der Spieler haben darf damit die KI ihm ein Darlehen anbietet.0=Kein Limit |
| `Diplomacy/MaxShipLimitPercentageToOrderSupport` | Integer | — | 70 | Wieviel Prozent des Schiffslimits darf maximal erreicht sein damit die KI Hilfe anfordert. Beispielsweise heisst 75 dass die KI maximal 3/4 des Schiffslimits belegt haben darf. |
| `Diplomacy/MaxTributePerLevel` | Array | — | — | Maximale Tributforderung pro Stufe. Wird ignoriert wenn auf 0 gesetzt |
| `Diplomacy/MilitaryCompareIntervall` | Time | — | 2100000 | Zeitdauer zwischen militärischen Kompetenzvergleichen |
| `Diplomacy/Min` | Integer | — | — |  |
| `Diplomacy/MinDuration` | Time | — | — | minum duration of this treaty |
| `Diplomacy/MinMoneyToOrderTribute` | Integer | — | 5000 | Wieviel Geld muss der Spieler minimal haben damit der CSP Tribut fordert. |
| `Diplomacy/MinPeaceTreatyDuration` | Time | — | — | Wie lange dauert ein Friedensvertrag mindestens |
| `Diplomacy/MinTributePerLevel` | Array | — | — | Pro Stufe das Minimum einer Tributforderung |
| `Diplomacy/OfferCreditIntervall` | Time | — | — | In welchem Zeitintervall wird geprüft ob die KI dem Spieler Geld schenken will. 0 heißt die KI schenkt einem kein Geld |
| `Diplomacy/OfferPeacePactAmount` | Integer | — | — | Wieviel Prozent eines normalen Tributs fordert ein CSP für einen Friedens-Pakt wenn er stark überlegen ist(CompetenceUsage OfferPeacePact) 0 schaltet das Feature aus |
| `Diplomacy/OfferPeacePactCooldown` | Time | — | — | Wie lange muss Krieg sein damit die KI einem gegen viel Geld einen Friedensvertrag anbietet |
| `Diplomacy/OrderMilitarySupportPreconditions` | Flags | — | — | Wenn alle angekreuzten Bedingungen eintreffen darf die KI die Hilfsflotte anfordern(Kein Kruez würde heißen die KI hat keine Beschränkung) |
| `Diplomacy/OrderTributeIntervall` | Time | — | — | Zeitintervall in dem Tribut gefordert wird(0=Keine Tributforderungen). Es wird nur gefordert wenn der CSP stark genug ist. |
| `Diplomacy/PeacePactAmountPerReputation` | Integer | — | — | Wenn die KI Frieden gegen viel Geld anbietet wid auf das Tribut noch dieser Wert pro Rufpunkt draufgerechnet |
| `Diplomacy/Percentage` | Integer | — | — | Wahrscheinlichkeit dass der Check gelingt |
| `Diplomacy/RelationChangeIntervall` | Time | — | 600000 | In welchem Intervall wird der Ruf je nach Beziehung zu den anderen CSPs angepasst |
| `Diplomacy/ReputationBoost` | Integer | — | — | reputation boost for each regression intervall(replaces default regression value if <> 0) |
| `Diplomacy/ReputationChangeIntervall` | Time | — | 1800000 | Intervall, nach welchem der Ruf modifiziert wird |
| `Diplomacy/StartTreaty` | Choice | — | TradeTreaty | Vertragszustand zwischen Profil und Spieler zu Beginn des Spiels. |
| `Diplomacy/SuccessPercentage` | Integer | — | — | Wahrscheinlichkeit, dass die Aktion erfolgreich ist. Sinkt nach einmaligem |
| `Diplomacy/TreatyForIngratiate` | Flags | — | TradeTreaty;AllianceTreaty | Bei welchen Vertragszuständen schmeichelt sich der Charakter ein |
| `Diplomacy/TreatyForIntimidate` | Flags | — | War;PeaceTreaty | Bei welchen Vertragszuständen beleidigt der Charakter einen Spieler |
| `Diplomacy/TreatyForIsCrazy` | Flags | — | — | In welchen Vertragszuständen darf grundlos der Krieg erklärt werden, wenn der Militärvergleich erfolgreich war |
| `Diplomacy/TreatyLockTime` | Time | — | 1800000 | Wie lange wird ein Vertrag nicht gekündigt nachdem er geschlossen wurde bzw. kein neuer angeboten wenn ein Vertrag aufgelöst wurde |
| `Diplomacy/TreatyRegressions` | Array | — | — | Rufregression bei einem bestimmten Vertrags- bzw. Paktzustand |
| `Diplomacy/TreatyToDemandForAssistance` | Flags | — | — | Auf welchen Vertragsstufen zum Spieler fordert der CSP, dass der Spieler einem Krieg beitritt |
| `Diplomacy/TreatyToExecuteAssistance` | Flags | — | — | Bei welchen Verträgen tritt die KI in einen Krieg mit ein |
| `Diplomacy/TreatyToOfferCredit` | Flags | — | — | Minimaler Vertrag, ab welchem das Profil freiwillige Geld schenkt |
| `Diplomacy/TreatyToOrderTribute` | Flags | — | — | Vertrags-Stati in denen Tribut gefordert wird |
| `Diplomacy/TributeAmountBadPercentage` | Integer | — | — | Prozentzahl der Forderung vom normalen Tribut(das schon charakterabhängig ist) |
| `Diplomacy/TributeAmountGoodPercentage` | Integer | — | — | Prozentzahl der Forderung vom normalen Tribut(das schon charakterabhängig ist) |
| `Diplomacy/TributeAmountPercentage` | Integer | — | 100 | Wieviel Tribut verlangt der Charakter(in Prozent vom Standard) |
| `Diplomacy/TributeContractsIntervall` | Time | — | 1800000 | In welchem Zeitabstand wird gecheckt, ob die KI einen Vertrag für Geld anbietet oder einen vetrag auflöst wenn Spieler nicht zahlt. Außerdem wird während diesem Cooldown nicht IsCrazy geprüft |
| `Diplomacy/TributePercentageToPlayer` | Array | — | — | Wieviel Prozent des Spieler-Golds fordert dieser Spieler. Ignoriert wenn gleich 0 |
| `Diplomacy/TributeValueBad` | Integer | — | — | Rufpunkte die man zur nächstniedrigen Stufe haben muss, bis der CSP Tribut fordert damit der vertrag bestehen bleibt |
| `Diplomacy/TributeValueGood` | Integer | — | — | Rufpunkte die man zur nächsthöheren Stufe braucht, bis der CSP Tribut fordert damit der nächste Vertrag geschlossen werden kann |
| `Diplomacy/TributeValues` | Array | — | — | Rufgrenzen ab denen der CSP Verträge gegen tribut anbietet oder kündigt |
| `Diplomacy/UseActiveDiplomacy` | Boolean | — | 1 | Wenn auf false gestellt sind für diesen Charakter alle aktiven diplomatischen Aktionen ausgeschaltet |
| `Diplomacy/WarshipCheckIntervall` | Time | — | — | Intervall in dem Kriegs-Schiffe anderer Spieler gecheckt werden. 0 = Nicht checken |
| `Diplomacy/WarshipCheckRadius` | RealInt | — | 102400 | Radius um alle Kontore in dem nach Kriegsschiffen gesucht wird |
| `Diplomacy/WarshipCheckStrength` | Integer | — | 7 | Ab welcher Schiffs-Stärke wird die Meldung WarshipsInInfluence getriggert |

## Espionage

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Espionage/EspionageActionIntervall` | Time | — | 900000 |  |
| `Espionage/Prop_FireRaiser` | Integer | 0..100 | 50 |  |
| `Espionage/Prop_NoAction` | Integer | 0..100 | 50 |  |
| `Espionage/Prop_Poisen` | Integer | 0..100 | 50 |  |
| `Espionage/Prop_Prophet` | Integer | 0..100 | 50 |  |
| `Espionage/Prop_Revolt` | Integer | 0..100 | 50 |  |
| `Espionage/Prop_Thief` | Integer | 0..100 | 50 |  |
| `Espionage/SpyDetectMinValue` | Integer | 0..100 | 10 | Mindestwahrscheinlichkeit für die Entdeckung der Spione |
| `Espionage/SpyDetectValue` | Integer | 0..100 | 30 | Die Wahrscheinlichkeit einen Spion zu enttarnen. |
| `Espionage/SpyMarketplaceDec` | Integer | 0..50 | 10 | Verringert die Wahrscheinlichkeit einen Spion zu entdecken, anhand der Anzahl der Marketplaces |
| `Espionage/TreatyToHigh` | Choice | — | AlliancePact |  |

## HonourTradeData

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `HonourTradeData/Achievement` | Asset | — | — |  |
| `HonourTradeData/Cooldown` | Time | — | — | Wie lange ist das Mischen von Items für alle Spieler geblockt nachdem es einmal benutzt wurde |
| `HonourTradeData/EmperorItemPool` | Quest | — | — | Pool der aktiv wird wenn man den Kaiser aktiviert hat |
| `HonourTradeData/FeatureLevel` | Vector | — | — | Vom Profil zum Kauf angebotene Errungenschaften |
| `HonourTradeData/Features` | Vector | — | — |  |
| `HonourTradeData/GoldCost` | Integer | — | — | Wieviel Gold kostet das Mischen von Items auf dieser Stufe |
| `HonourTradeData/HonourCost` | Integer | — | — | Wieviel Ruhm kostet das Mischen von Items auf dieser Stufe |
| `HonourTradeData/ItemAchievement` | Asset | — | — | Errungenschaft, die benötigt wird, um auf die angebotenen Items Zugriff zu haben. |
| `HonourTradeData/ItemPool` | Quest | — | — | Pool aus dem gewählt wird |
| `HonourTradeData/ItemProductionTimeMax` | Time | — | — | Maximale Zeit um ein neues Item zum Verkauf einzustellen. Der Timer startet, sobald der entsprechende Slot leer ist. |
| `HonourTradeData/ItemProductionTimeMin` | Time | — | — | Minimale Zeit um ein neues Item zum Verkauf einzustellen. Der Timer startet, sobald der entsprechende Slot leer ist. |
| `HonourTradeData/ItemSlots` | Vector | — | — | Item-Pool Zuweisung für die einzelnen Item-Verkaufsslots |
| `HonourTradeData/ItemsAtStart` | Integer | — | — | Startanzahl an Items (bezogen auf die Anzahlan Verkaufsslots) |
| `HonourTradeData/LevelTradeData` | Array | — | — | Vom Profil angebotene Waren und Items mit Mengen und Verfügbarken auf den verschiedenen ZivStufen. |
| `HonourTradeData/NeededLevelIcon` | Text | — | — |  |
| `HonourTradeData/NeededLevelPoints` | Integer | — | — | Anzahl von Levelpunkten, die in der vorigen Ebene ausgegeben werden müssen um diesen La |
| `HonourTradeData/NeededLevelText` | Text | — | — |  |
| `HonourTradeData/OrientItemPool` | Quest | — | — | Pool der benutzt wird wenn der höchste Orient-Status erreicht wurde |
| `HonourTradeData/Product` | Choice | — | — | Zum Verkauf angebotene Ware |
| `HonourTradeData/ProductAchievement` | Asset | — | — | Errungenschaft, die benötigt wird, um auf die angebotenen Waren Zugriff zu haben. |
| `HonourTradeData/ProductCount` | Integer | — | — | Maximale Menge mit der die Ware angeboten wird. Wird ignoriert, wenn auf 0 gesetzt. |
| `HonourTradeData/ProductCountAtStart` | Integer | — | — | Wieviele Tonen sind bei Spielstart im Kontor bereist vorhanden |
| `HonourTradeData/ProductionTimeMax` | Time | — | — | Maximale Zeit, um 1 Tonne der Ware aufzufüllen. Timer läuft an sobald die Menge weniger ProductCount ist. |
| `HonourTradeData/ProductionTimeMin` | Time | — | — | Minimale Zeit, um 1 Tonne der Ware aufzufüllen. Timer läuft an sobald die Menge weniger ProductCount ist. |
| `HonourTradeData/Products` | Vector | — | — | Einstellungen zu den angebotenen Waren |
| `HonourTradeData/ProductsProduced` | Integer | — | — | Wie viele Tonen der Ware werden pro Intervall produziert. |
| `HonourTradeData/SellProduct` | Boolean | — | — | true = Ware steht zum Verkauf. false = Ware wird angekauft. |
| `HonourTradeData/ShuffleItems` | Struct | — | — | Daten für das Mischen von Items |
| `HonourTradeData/SultanItemPool` | Quest | — | — | Pool der aktiv wird wenn man den Sultan aktiviert hat |
| `HonourTradeData/Tooltip` | Text | — | — |  |
| `HonourTradeData/VolcanoItemPool` | Quest | — | — | Pool der nur aktiv ist wenn man auf einer Welt mit Vulkan spielt |

## HonourUsage

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `HonourUsage/Achievement` | Asset | — | — |  |
| `HonourUsage/AchievementPriorities` | Vector | — | — | Spezielle Freischaltungs-Prioritäten.0=Wird nicht freigeschaltet, ansonsten je höher desto besser. Defaultmäßig wird die Priorität der Nation genommen |
| `HonourUsage/AchievementWeightsPerNation` | Array | — | — | Wie hoch sind die einzelnen Nationen gewichtet. Es werden zuerst alle Freischaltungen gesammelt die verfügbar sind. Danach wird je nach Gewichtung entschieden welche zuerst freigeschaltet wird. |
| `HonourUsage/BuyAchievementIntervall` | Time | — | 300000 | In welchem Intrevall kauft die KI Errungenschaften |
| `HonourUsage/HonourPerLevel` | Array | — | — | Wieviele Ruhmpunkte bekommt der CSP einmalig bei Erreichen einer neuen Stufe |
| `HonourUsage/HonourPercentage` | Integer | — | — | Wieviel Prozent Ruhm des Spielers bekommt der CSP |
| `HonourUsage/Priority` | Integer | — | — | Priorität der Freischaltung. Default ist die Priorität der Nation |

## ItemUsage

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `ItemUsage/BuyItemInvervall` | Time | — | 900000 | In welchem Intervall probiert die KI Items zu kaufen |
| `ItemUsage/ItemPriorities` | Array | — | — | Priorität für die einzelnen Item-Typen |
| `ItemUsage/UseItemIntervall` | Time | — | 300000 | Intervall in dem gecheckt wird ob die KI globale Items benutzen kann |
| `ItemUsage/UseWhiteFlagPercentage` | Integer | — | 20 | Ab wieviel Prozent der Hitpoints benutzt die KI die weiße Flagge |

## Messages

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Messages/AudioGUIDs` | Vector | — | — | Zusätzliche Audiomeldungen, die bei Anzeige der Meldung ausgewählt werden können *** Info: Über den Auswahl-Button können neue Audiomeldungen hinzugefügt oder gelöscht werden. Für jede Audiomeldung kann eine Priorität eingestellt werden, mit welcher sie gewählt wird. |
| `Messages/AudioPools` | Vector | — | — | Audiopools, aus welchen bei Anzeige der Meldung eine Audiomeldung gewählt wird *** Info: Über den Auswahl-Button können neue Audiopools hinzugefügt oder gelöscht werden. Für jeden Audiopool kann eine Priorität eingestellt werden, mit welcher eine Audiomeldung aus dem enstprechenden Pool gewählt wird. |
| `Messages/Caption` | Text | — | — | Ausprägung der 4 Rufstufen des Profils. Die Ausprägung wird durch die Obergrenze der entsprechenden Stufe angegeben. |
| `Messages/CityStatus` | Choice | — | — | Stadt-Status der erreicht wurde. Nur für Trigger CITYSTATUS_REACHED |
| `Messages/DisabledAudioGUIDs` | Vector | — | — | Audiomeldungen aus den zugewiesenen Audiopools, die für die entsprechende Meldung gesperrt sind *** Info: Auf dem Reiter Sounds werden alle Audiomeldungen, die einer Meldung zugeordnet sind, als Baum angezeigt. *** Bei Linksklick auf die entsprechende Audiomeldung wird diese abgespielt. *** Doppelter Linksklick auf das Symbol vor der Audiomeldung sperrt diese bzw. gibt diese für die entsprechende Meldung. *** Haken: Audiomeldung wird von entsprechender Meldung verwendet *** Kreuz: Audiomeldung ist für entsprechende Meldung gesperrt |
| `Messages/Executor` | Choice | — | — | Auslöser des Triggers *** Player: der Spieler *** Self: das Profil selbst *** Third: ein dritter Spieler |
| `Messages/HonourBonus` | Integer | — | — | Anzahl an Ruhmpunkten, die der Spieler erhält, wenn die Meldung angezeigt wird |
| `Messages/Intervall` | Integer | — | — | Anzahl, wie oft ein Trigger ausgelöst werden muss, damit die enstprechende Meldung erneut gestartet wird |
| `Messages/MaxCallCount` | Integer | — | — | Maximale Anzahl, mit welcher die Meldung angezeigt wird |
| `Messages/MaxDelay` | Time | — | — | Maximale Verzögerung, mit der eine Meldung gestartet wird |
| `Messages/MaxReputation` | Integer | — | — | Maximale Rufstufe, bei welcher die Meldung angezeigt wird |
| `Messages/Messages` | Vector | — | — |  |
| `Messages/MinDelay` | Time | — | — | Minimale Verzögerung, mit der eine Meldung gestartet wird |
| `Messages/MinPlayTime` | Time | — | — | Wie lange muss das Spiel mindestens laufen |
| `Messages/MinReputation` | Integer | — | — | Mindeste Rufstufe, bei welcher die Meldung angezeigt wird |
| `Messages/Mood` | Choice | — | — | Stimmung des Portraits. Default ist rufabhängig. |
| `Messages/Object` | Asset | — | — | GUID für spezielle Objekt-Trigger |
| `Messages/Percentage` | Integer | — | — | Wahrscheinlichkeit, mit welcher die Meldung angezeigt wird |
| `Messages/Pool` | Choice | — | — |  |
| `Messages/PortraitBackground` | FileName | — | — | Hintergrund des Portraits |
| `Messages/PortraitForeground` | FileName | — | — | Vordergrundbild als Portrait |
| `Messages/Priority` | Choice | — | — | priority of this sound |
| `Messages/ProfileGUID` | AIProfile | — | — | Profile auf das sich die Meldung beziegt. Für TALK_BOUT_CHARACTER |
| `Messages/Quest` | Quest | — | — | Quest, bei welcher die Meldung verwendet wird. *** Info: Gilt nur für die Trigger der Kategorie Quests. Es werden nur bei speziellen Quests extra Meldungen angelegt, wenn dort ein vom Standard abweichender Text angezeigt werden soll. Wird im Feld eine 0 (=INVALID) gesetzt, wird die Meldung für alle Quests angezeigt, die keine spezielle Meldung besitzen. *** Spezielle Texte werden direkt bei der jeweiligen Quest im QuestEditor auf dem Unterreiter Messages angezeigt und können dort sogar neu angelegt werden. |
| `Messages/Reaction` | Choice | — | — | Art der Rufveränderung, die die Meldung nach sich zieht *** IncreaseReputation: Ruf steigt um ReactionValue *** DecreaseReputation: Ruf sinkt um ReactionValue *** SetReputation_01: Ruf wird auf Stufe 1 gesetzt *** SetReputation_02: Ruf wird auf Stufe 2 gesetzt *** SetReputation_03: Ruf wird auf Stufe 3 gesetzt *** SetReputation_04: Ruf wird auf Stufe 4 gesetzt *** DeclareWar: Profil erklärt Spieelr den Krieg *** CallForHelp: Profil ersucht den Spiele um Hilfe *** SetTradeTreaty: Vertragszustand wird auf Handelsvertrag gesetzt |
| `Messages/ReactionValue` | Integer | — | — | Konkreter Wert der Rufveränderung Info: Wird nur bei Reaction IncreaseReputation und DecreaseReputation verwendet |
| `Messages/RemoveOnDeselect` | Boolean | — | — | Wenn auf true gesetzt wird diese Meldung beim Deselektieren eines Objektes automatisch entfernt |
| `Messages/ScenarioID` | Integer | — | — | Spezielle ID für Nachrichten über die Ablaufsteuerung |
| `Messages/Sex` | Flags | — | — | Für welche Geschlechter ist der Sound |
| `Messages/Sound` | Text | — | — |  |
| `Messages/StartIntervall` | Integer | — | — | Anzahl, wie oft ein Trigger ausgelöst werden muss, dass die entsprechende Meldung zum ersten Mal gestartet wird |
| `Messages/TalkingProfile` | AIProfile | — | — | Profil das im Portait angezeigt wird |
| `Messages/Text` | Text | — | — | Text der bei Ausgabe der Meldung angezeigt wird. Info: Über den Auswahl-Button wird der TreeView des Texteditors geöffnet und es kann ein bestehender Text ausgewählt oder ein neuer Text hinzugefügt werden. |
| `Messages/Timeout` | Time | — | — | Wie lange wird die Nachricht geblockt wenn sie einmal ausgeführt wurde |
| `Messages/Treaties` | Flags | — | — | Vertrags- oder Paktzustand bei welchem die entsprechende Meldung verwendet wird. Info: Wird nur für Meldungen mit Vertrag oder Pakt verwendet. Dort ersetzt die Unterscheidung des Vertrages oder Paktes in der Meldung eine Unterscheidugn auf Ebene der Trigger. |

## Military

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Military/AttackMainIsland` | Boolean | — | — | Die KI soll NUR die Hauptinsel angreifen |
| `Military/BuildSupplyDepot` | Boolean | — | 1 | Soll die Ki das SupplyDepot bauen? |
| `Military/BuildWall` | Boolean | — | — | Baut die KI Mauern. |
| `Military/DangerousValue` | Integer | 0..1000 | 200 | Ein Wert, der angibt, wann die KI Einheit mit sicherheit nicht loslaufen soll, wenn sie durch feindliches Gebiet läuft. D.h. Es wird für jedes Tile analysiert, wieviel Gegner im Militäreinflussbereich sind. D.h. Feindlicher Militärbereich = +3, Im Gegnerischen Range Combat Tile = +10. Ist die letzte Position einer Nahkampf einheit in einem feindlichen RangCombatRadius +999 |
| `Military/EnemyPlayerPreferred` | Integer | -1..16 | -1 | Bevorzugt einen Spieler beim der Inselwahl nehmen (-1 = kein Spieler bevorzugt) |
| `Military/EnemyProp_FightTogether` | Integer | 0..60 | 22 | Bonus auf die Gewichtung des nächsten Targets, wenn das Target schon angegriffen wird. |
| `Military/EnemyProp_IsEnemyInRange` | Integer | 0..100 | 500 | Zusätzliche Gewichtung, wenn das Ziel schon in Reichweite ist. Gilt für Nah- Und Fernkampf. |
| `Military/EnemyProp_IsKontor` | Integer | 0..100 | 4 | Grundsystem: Bei der Zielsuche wird das am besten gewichtete Ziel ausgesucht. Alle EnemyProp Werte fügen dieser Gewichtung einen Bonus oder einen Malus hinzu.[CR]Gewichtet gegnerische Handelsgebäude und Dorfzentrum. |
| `Military/EnemyProp_Near_IsCloseCombat` | Integer | 0..100 | 48 | Nahkämpfer: Gewichtung, die dazugefuegt wird, wenn der Gegner eine Nahkampfeinheit ist |
| `Military/EnemyProp_Near_IsRangeCombat` | Integer | 0..100 | 55 | Nahkämpfer: Gewichtung die dazugezaehlt wird, wenn der Gegner eine Distanz-Schuss-Einheit ist |
| `Military/EnemyProp_Near_IsTower` | Integer | 0..100 | 30 | Nahkämpfer: Gewichtung, die dazugefuegt wird, wenn der Gegner ein Fortress oder ein Tower ist. |
| `Military/EnemyProp_Near_IsWall` | Integer | 0..100 | — | Nahkämpfer: Gewichtung, wenn der Gegner ein Wandtile ist. Wird nicht benutzt, da Nahkämpfer Mauern nicht angreifen können. |
| `Military/EnemyProp_Near_Monument` | Integer | 0..100 | — | Nahkämpfer: Gewichtung die dazugezaehlt wird, wenn der Gegner ein Monument ist |
| `Military/EnemyProp_Near_Supply` | Integer | 0..100 | — | Angriff auf ein SupplyDepot |
| `Military/EnemyProp_Range_IsCloseCombat` | Integer | 0..100 | 10 | Fernkämpfer: Gewichtung, die dazugefuegt wird, wenn der Gegner eine Nahkampfeinheit ist |
| `Military/EnemyProp_Range_IsRangeCombat` | Integer | 0..100 | 20 | Fernkämpfer: Gewichtung die dazugezaehlt wird, wenn der Gegner eine Distanz-Schuss-Einheit ist |
| `Military/EnemyProp_Range_IsTower` | Integer | 0..100 | 60 | Fernkämpfer: Gewichtung, die dazugefuegt wird, wenn der Gegner ein Fortress oder ein Tower ist. |
| `Military/EnemyProp_Range_IsWall` | Integer | 0..100 | 30 | Fernkämpfer: Gewichtung, wenn der Gegner ein Wandtile ist. Wert zwischen (1-10) macht Sinn. |
| `Military/EnemyProp_Range_Monument` | Integer | 0..100 | 10 | Fernkämpfer: Gewichtung die dazugezaehlt wird, wenn der Gegner ein Monument ist |
| `Military/EnemyProp_Range_SupplyDepot` | Integer | 0..100 | 10 | Angriff auf ein SupplyDepot |
| `Military/EnemyProp_TargetDist` | Integer | 0..100 | 10 | Einen Factor auf die Entfernung. Dabei ist 100Tiles das Limit!,D.h. Ist der Faktor 10, So werden alle 10 Tiles einen Minuspunkt der Gewichtung hinzugerechnet. Die ersten 20 Tiles werden dabei aber ignoriert, da die Ziele in nächster Nähe liegen und meist sofort angegriffen wwerden können. |
| `Military/FightTogether` | Boolean | — | 1 | Versuchen sich die Einheiten der KI zu unterstützen? |
| `Military/IslandPrio_MilitaryUnits` | Integer | 0..100 | 10 | Pro Militäreinheit/Gebäude wird ein Bonus/Malus für den Angriff auf eine Insel gegeben. |
| `Military/IslandPrio_ProductionBuildings` | Integer | 0..100 | 3 | Pro Productionsgebäude wird ein Bonus für den Angriff auf eine Insel gegeben. Im Property balancen. |
| `Military/MaxMilitaryPoints` | Integer | — | 80 | Maximale Benutzung der Militärpunkte, in prozent angegeben! |
| `Military/MaxMilitaryPointsInWar` | Integer | — | 100 | Maximale Benutzung der Militärpunkte im Kriegsfall |
| `Military/MaxMilitaryPointsRessourceIsland` | Integer | 0..100 | — | Wird angegeben, wieviel von der Verteidigung der Inseln auf die Ressourceninseln uebertragen werden |
| `Military/MaxTowerBuild` | Integer | — | 20 | Anzahl der Militärpunkte, die in die Türme gehen. Prozentwert von den aktuellen Militärpunkten, die der Spieler hat. Für HAupt- und Ressourceninseln. |
| `Military/MaxUnitCount` | Integer | 0..100 | 70 | Anzahl an Einheiten die die KI produzieren darf. Steht in relation zu den Militaerpunkten und wird in % angegeben. |
| `Military/MaxUnitCount_MoneyProblems` | Integer | 0..100 | 15 | Anzahl der Einheiten, wenn die KI In Geldschwierigkeiten steckt. InProzent vom Militärlimit. |
| `Military/MilitaryWarRecruitingDelay` | Time | — | — | Intervall, wann Einheiten mind. nachgebaut werden sollen (Das Intervall ist nicht exakt, aber gibt eine mindestdauer vor), sollte der feindliche Spieler auf der KI Hauptinsel stehen und diese keine Rohstoffe zur Nachproduktion der Einheiten haben. |
| `Military/ReduceSupportInWar` | Integer | — | 50 | Reduzierung der ercheateten Menge an Gold und Baurohstoffe, sollte der gegnerische Spieler auf einer Insel der KI stehen |
| `Military/UnitMinRegeneration` | Integer | 0..100 | 80 | Prozentsatz der HP nach der Regeneration der Einheit, ab wann sie wieder loslaufen kann. |
| `Military/UnitPaymentValue` | Integer | 0..99 | 8 | Legt den Wert fest, wieviele Waffen die KI für ein Camp ausgeben soll! |
| `Military/UnitRetreatValue` | Integer | 0..100 | 50 | Gibt an, ab wieviel Prozent der eigenen Lebenspunkte die Einheit zurueck zum Kontor/Trutzburg soll! |

## MilitarySupport

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `MilitarySupport/Cooldown` | Time | — | — | Dauer, bis die Wahrscheinlichkeit nach einer Forderung wieder auf das Maximum angestiegen ist. |
| `MilitarySupport/Count` | Integer | — | — | Anzahl der Schiffe |
| `MilitarySupport/HonourCost` | Integer | — | — | Ruhm-Kosten pro Forderung der Hilfsflotte |
| `MilitarySupport/Levels` | Vector | — | — | Ausbaustufen der Hilfsflotte |
| `MilitarySupport/NeededAchievement` | Asset | — | — | Benötigte Errungenschaft für diese Ausbaustufe der Hilfsflotte |
| `MilitarySupport/Ship` | Asset | — | — | Typ des Schiffs |
| `MilitarySupport/ShipList` | Vector | — | — | Liste der Schiffe in dieser Ausbaustufe der Hilfsflotte |
| `MilitarySupport/SuccessPercentage` | Integer | — | — | Wahrscheinlichkeit, dass die Anfrage erfolgreich ist. Sinkt nach einer Anfrage auf 0 und steigt dann wieder langsam an(die Dauer des Cooldowns) |

## Quest

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Quest/CheckIntervallMax` | Time | — | 60000 | Maximale Zeit nach welcher das Profil eine neue Quest ausschreiben darf |
| `Quest/CheckIntervallMin` | Time | — | — | Minimale Zeit nach welcher das Profil eine neue Quest ausschreiben darf |
| `Quest/CheckIntervallOffset` | Array | — | — | Offset auf das Check-Intervall pro ZivStufe |
| `Quest/CheckMaxRunningPools` | Boolean | — | 1 | wenn auf TRUE gesetzt startet dieser pool Aufträge nur, wenn nicht die Maximalzahl an Pools erreicht ist |
| `Quest/Group` | QuestGroup | — | — | Zugewiesene Questgruppe |
| `Quest/IgnoreOffsetTimes` | Boolean | — | — | Wenn auf true gesetzt wird die NextCheckTime nicht erhöht wenn eine Quest eines anderen Spielers gestartet wurde |
| `Quest/MaxRunningQuests` | Integer | — | 1 | Wie viele Quests darf das Profil maximal gleichzeitig ausschreiben. |
| `Quest/Offset` | Time | — | — | Zeit die für diese Stufe auf CheckIntervall addiert wird |
| `Quest/Percentage` | Integer | — | — | Wahrscheinlichkeit, dass eine Quest aus dieser Gruppe im angegebenen Intervall ausgewählt wird. |
| `Quest/PoolOffsetTime` | Time | — | — | Zeit, die auf das CheckIntervall anderer Profile addiert wird, wenn dieses Profil gerade eien Quest ausgeschrieben hat |
| `Quest/QuestGroups` | Vector | — | — | Questgruppen, die das Profil benutzt. Aus den zugewiesen Questgruppen kann das Profil Quests ausschreiben. Pro Pool kann eine maximale anzhal an Quests die gleichzeitig aus dem enstprechenden Pool gestartet werden darf und die Wahrscheinlichkeit, das eine Quest aus dem Pool gestartet wird, eingestellt werden. Zuweisung auch im Questeditor über die entsprechende Quest-Gruppe möglich. |
| `Quest/StartTimeMax` | Time | — | 120000 | Maximale Zeit nach der die Questpools des Profils den ersten Auftrag ausschreiben dürfen. |
| `Quest/StartTimeMin` | Time | — | 60000 | Minimale Zeit nach der die Questpools des Profils den ersten Auftrag ausschreiben dürfen. |
| `Quest/WelcomeQuest` | Quest | — | 0 | Quest, die beim ersten Anklicken des Hauptgebäudes gestartet wird (für Neutrale Gebäude verwendet) |

## Relationships

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Relationships/FriendState` | Flags | — | — | Welche Vertrags-Stati zählen zum Freund-Status |
| `Relationships/Profile` | AIProfile | — | — | Auf welches Profil bezieht sich der Status |
| `Relationships/ProfileGUID` | AIProfile | — | — |  |
| `Relationships/Profiles` | Vector | — | — |  |
| `Relationships/Relations` | Array | — | — | Beziehungstendenz des Profils zu den anderen CSPs |
| `Relationships/RivalState` | Flags | — | — | Welche Vertrags-Stati zählen zum Rivalen-Status |
| `Relationships/SpecialProfiles` | Vector | — | — | Liste von Profilen die einen besonderen Status haben(Freund oder Rivale) je nach Vertrags-Status |

## Reputation

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Reputation/Regression` | Choice | — | — |  |
| `Reputation/Regressions` | Array | — | — | Rufregression auf der entsprechenden Rufstufe. *** Neutral: keine Regression *** Negative: Ruf sinkt *** Positive: Ruf steigt *** Center: Ruf tendiert zur Mitte der Rufstufe *** IncreaseToCenter: Ruf steigt bis zur Mitte der Rufstufe *** DecreaseToCenter: Ruf sinkt bis zur Mitte der Rufstufe |
| `Reputation/ReputationLimits` | Array | — | — | Ausprägung der 4 Rufstufen des Profils. Die Ausprägung wird durch die Obergrenze der entsprechenden Stufe angegeben. |
| `Reputation/StartReputation` | Integer | — | — | Startruf des Spielers beim Profil |
| `Reputation/StartReputationPerTreaty` | Array | — | — | Pro Vertrags-Status der pro CSP voreingestellt werden kann wird hier der Start-Ruf eingetragen(nur für CSPs relevant) |

## Research

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Research/ResearchSpeed` | Integer | — | — | Geschwindigkeit der Forschung (nicht verwendet) |

## SecretDiplomacy

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `SecretDiplomacy/MaxTreatyForSecretDiplomacy` | Choice | — | War | Maximaler Vertragsstatus um Geheimdiplomatie anzuwenden (nicht verwendet) |
| `SecretDiplomacy/SecretDiplomacyPercentage` | Integer | — | — | Wahrscheinlichkeit für Geheimdiplomatie (nicht verwendet) |

## ShipFight

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `ShipFight/AdditionalShipPercentage` | Integer | — | — | Wenn ein Ziel gefunden wurde wird versucht noch Schiffe bis zu dieser Stärke(in Prozent zu den benötigten) mitzunehmen. Beispielsweise bedeutet 50%, dass bei 2 benötigten Schiffen noch ein drittes dazugeholt wird falls vorhanden |
| `ShipFight/BlockEnemyShipTime` | Time | — | 120000 | Wie lange wird ein Schiff als Angriffsziel geblockt wenn es länger als [ShipHuntDuration] verfolgt wurde. Auch am besten im Property balancen. |
| `ShipFight/CallForHelpMinStrengthPercentage` | Integer | — | 70 | Ab welcher Stärke in Prozent zum Gegner helfen alle Schiff in der Reichweite [CallForHelpRange] bei Beschuss |
| `ShipFight/CallForHelpRange` | RealInt | — | — | In welcher Reichweite kommen ggf. Schiffe zur Hilfe wenn die KI angegriffen wurde. Es werden nur Schiffe gerufen, die selbst keinen Angriff ausführen. |
| `ShipFight/DestroyForts` | Boolean | — | — | Werden Trutzburgen zerstört ? |
| `ShipFight/DestroyHarbourBuildings` | Boolean | — | — | Zerstört die Schiffs-KI Hafengebäude. Ausnahmen können gesondert eingestellt werden (Werft, Kontor, Turm). Mit der einstellung werden beispielsweise Reparaturkräne angegriffen. |
| `ShipFight/DestroyKontors` | Boolean | — | — | Zerstörung von Kontoren durch das Profil im Schiffskampf |
| `ShipFight/DestroyShipYards` | Boolean | — | — | Zerstörung von Werften durch das Profil im Schiffskampf |
| `ShipFight/DestroyTowers` | Boolean | — | — | Werden Türme angegriffen. |
| `ShipFight/DestroyWarshipsInEmergency` | Boolean | — | — | Wenn auf true gesetzt zerstört die KI Kriegs-Schiffe wenn sie in Geldnot ist oder das Einheitenlimit überschritten hat |
| `ShipFight/HuntShips` | Boolean | — | — | Suche nach ungeschützten Schiffen, um diese anzugreifen. KI Schiffe sammeln sich und greifen dann ein ungeschütztes Ziel an. Welches Ziel gewählt wird, ergibt sich aus der Gewichtung. |
| `ShipFight/IgnoreEnemyCheckRange` | RealInt | — | 204800 | In welcher Reichweite um einen potentiellen Gegner checkt eine Schiffsgruppe ob sie ein Sekundärziel angreifen soll. Nur relevant wenn IgnoreEnemyStrengthpercentage gesetzt ist. Am besten nur im Property balancen. |
| `ShipFight/IgnoreEnemyStrengthPercentage` | Integer | — | — | Bis zu welcher Stärke werden Feinde ignoriert, die kein Primärziel sind (Patrouille, Eskorte oder auf dem Weg zum Primärziel). Beispielsweise heißt 30, dass Schiffe Ziele ignorieren wenn der die KI weniger als 30% der Stärke des Gegners hat. Wird ignoriert wenn auf 0 gesetzt. Ähnlich wieShipSecurityPercentage - nur für unterwegs. |
| `ShipFight/MaxBalanceToDestroyWarships` | Integer | — | -400 | Wie hoch darf die Bilanz maximal sein damit die KI Kriegs-Schiffe zerstört um an Geld zu kommen |
| `ShipFight/MaxOffensiveShipPercentage` | Integer | — | 75 | Maximale Anzahl an Schiffen, die für offensive Zwecke genutzt wird. Der restliche Anteil wird für defensive Zwecke, wie z.B. Patrouillen oder Eskorte verwendet. |
| `ShipFight/MaxShareShipsTime` | Time | — | 300000 | Wie lange wartet die Schiffs-KI maximal bevor sie losfährt beim Sammelpunkt.(Wenn ungleich 0) |
| `ShipFight/MinWarShipPercentageToDestroyShips` | Integer | — | 30 | Wieviel Prozent des Schiffslimit benutzt die KI minimal so lange sie nicht in Geldnot ist |
| `ShipFight/MinWarshipCount` | Integer | — | — | Wieviele Kriegs-Schiffe behält die KI minimal, auch in Geldnot oder wenn das Schiffslimit erreicht ist |
| `ShipFight/RepairHitpointPercentage` | Integer | — | 30 | Grenze an Hitpoints, ab welcher ein Schiff sich zu reparieren versucht |
| `ShipFight/ShareAttackingShips` | Boolean | — | — | Zusammenbleiben der gesamten angreifenden Kriegsflotte. Es wird das beste Ziel gewählt aber unabhängig von den AdditionalShips werden alle verfügbaren Angriffs-Schiffe für den Angriff auf ein Ziel benutzt. |
| `ShipFight/ShareShipsMinDistance` | RealInt | — | 163840 | Ab welcher Distanz in Tiles zum Mittelpunkt der Gruppe werden die Schiffe vorher gesammelt. Am besten nur im Property balancen bzw. so lassen. |
| `ShipFight/ShipAmountPerLevel` | Array | — | — | Anzahl Kriegsschiffe pro Zivilisationsstufe. Dieser Wert stellt sozusagen die Untergrenze an Kriegsschiffen der KI dar. |
| `ShipFight/ShipAttackIntervall` | Time | — | — | Zeitintervall, nach welchem das Profil nach neuen Hauptzielen sucht. Es werden alle Gebäude und alle Schiffe berücksichtigt (alle möglichen Ziele). Je kürzer desto "stressiger" wird das Profil. Hauptregler um Profile in der Aggressivität zu unterscheiden. |
| `ShipFight/ShipDangerRadius` | RealInt | — | 122880 | Radius in Tiles, um den gesucht wird bei der Bewertung der Angriffsziele. Alle Stärken der Feinde in diesem Umkreis werden addiert.Gilt beim Suchen von Hauptzielen. Je größer desto vorsichtiger und umgekehrt. Eher im Property balancen. |
| `ShipFight/ShipDropItemPercentage` | Integer | — | — | Zu welcher Wahrscheinlichkeit wird ein Item gedroppt bei der Zerstörung eines Schiffes |
| `ShipFight/ShipDropPool` | Quest | — | 0 | Aus welchem Pool werden Items ausgewürfelt wenn ein Schiff zerstört wurde |
| `ShipFight/ShipGroupDangerRadius` | RealInt | — | 163840 | In welchem Radius wird gecheckt ob die komplette Gruppe fliehen soll und ob potentielle Feinde ignoriert werden sollen. Sollte nur im Property gebalanced werden. |
| `ShipFight/ShipGroupFleeMovePercentage` | Integer | — | — | Stärke in Prozent zu der des Gegners im Umkreis in Prozent ab der die Gruppe anfängt zu fliehen (wähend der Bewegung). 50% heisst beispielsweise dass die Flotte flieht sobald der Gegner doppelt so stark ist. |
| `ShipFight/ShipGroupFleePercentage` | Integer | — | 25 | Stärke in Prozent zu der des Gegners im Umkreis in Prozent ab der die Gruppe anfängt zu fliehen(Wähend dem Kampf). 50% heisst beispielsweise dass die Flotte flieht sobald der Gegner doppelt so stark ist. Gilt wenn die Schiffsgruppe am Ziel angekommen ist (vgl. extra Wert, wenn Schiffsgruppe unterwegs ist.) |
| `ShipFight/ShipGroupSearchDistance` | RealInt | — | 81920 | In welchem Abstand sucht eine Angriffsgruppe die gerade auf dem Weg zu ihrem Primärziel ist nach Sekundärzielen. Wenn das Primärziel tot ist wird in dem Radius nach optionalen Zielen gesucht, danach wird der Angriff abgebrochen |
| `ShipFight/ShipHuntDuration` | Time | — | — | Wie lange jagt eine Flotte ein sich bewegendes Ziel das momentan nicht angreift. 0 = Keine Zeitbeschränkung. Die Zeit zählt sobald die Gruppe nah genug am Ziel ist. Am besten im Property balancen. |
| `ShipFight/ShipPatrolFleePercentage` | Integer | — | — | Stärke in Prozent zu der des Gegners im Umkreis in Prozent ab der die Gruppe anfängt zu fliehen(Während der Patrouille). 50% heisst beispielsweise dass die Flotte flieht sobald der Gegner doppelt so stark ist. |
| `ShipFight/ShipPatrolIntervall` | Time | — | 5000 | Zeitintervall, nach dem das Profil prüft, ob eine neue Patrouille gestartet werden soll. Wert am besten nur im Property balancen bzw. so lassen. |
| `ShipFight/ShipPatrolSearchDistance` | RealInt | — | 204800 | In welchem Abstand sucht eine Patrouillen-Gruppe nach Zielen |
| `ShipFight/ShipPatrolSize` | Integer | — | 3 | Maximale Größe einer Schiffsgruppe auf Patrouille. Die angepeilte größe wird über ShipPatrolSizePercentage geregelt |
| `ShipFight/ShipPatrolSizePercentage` | Integer | — | — | Wieviel Prozent der Kriegsschiffe werden probiert in eine Patrouillien-Gruppe zu stecken. Wird ignoriert wenn gleich 0. Wenn die KI beispielsweise 10 Schiffe hat und dieser Wert 25% ist, werden versucht 5er-Gruppen zu bilden. Die maximale Größe wird in ShipPatrolSize geregelt |
| `ShipFight/ShipRatioToPlayer` | Integer | — | — | In Prozent wieviele Kriegsschiffe das Profil gegenüber dem besten menschlichen Spieler bauen kann. Wert wird überschrieben, falls ShipAmountPerLevel höher ist. Z.B. 150% bedeutet die KI darf das 1,5fache an Kriegsschiffen haben wie der Spieler. |
| `ShipFight/ShipRepairIntervall` | Time | — | — | Zeitintervall, nach dem das Profil prüft, ob ein Schiff repariert werden muss |
| `ShipFight/ShipSecurityPercentage` | Integer | — | 100 | Schiffs-Stärke, die das Profil benötigt, um ein Ziel anzugreifen.(In Prozent zur Stärke des Gegners, beispielsweise heißt 150% dass die KI mindestens 3/2 im Vorteil sein muss) Wird bei der Zielauswahl und nicht während eines laufenden Kampfes genutzt. |
| `ShipFight/ShipsAttackStrongestTargetFirst` | Boolean | — | — | Greift die KI zuerst die stärksten Ziele an (es werden dabei nur Ziele beachtet die schwach genug sind, dass Die KI den Kampf noch gewinnt, siehe ShipSecurity). Die KI würde z.B. zuerst die Hauptflotte des Gegners attackieren, statt einfache Ziel zuerst auszuschalten. |
| `ShipFight/StopWaitingMinStrengthPercentage` | Integer | — | 150 | Wenn ungleich 0 : Ab welcher Stärke fährt die KI während dem Sammeln los ohne auf den Rest zu warten(prozentual zum Gegner) Beispielsweise heißt 200 dass die KI losfährt sobald sie doppelt so stark ist |
| `ShipFight/TargetPriorities` | Array | — | — | Pro Ziel kann hier eine Priorität eingestellt werden, je höher desto besser. Nach der Priorität je Objekttyp werden die Spezialfälle draufaddiert(beispielsweise BuildingOnIsland wenn es ein Gebäude auf einer Insel des CSPs ist) |
| `ShipFight/UseShipEscort` | Boolean | — | — | Verwendung von Schiffseskorten durch das Profil. Die KI eskortiert Handelsschiffe bei allen möglichen Aufgaben, die von diesen durchgeführt werden. Hauptsächlich Inselbesiedlung und Transportrouten. |
| `ShipFight/UseShipPatrol` | Boolean | — | — | TRUE : KI benutzt Schiffs-Patrouillen, FALSE : KI benutzt keine Patrouillen |

## ShipSpawner

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `ShipSpawner/Max` | Integer | — | — | Maximale Anzahl an Schiffen auf dieser Stufe |
| `ShipSpawner/Min` | Integer | — | — | Minimale Anzahl an Schiffen auf dieser Stufe |
| `ShipSpawner/ShipHasLoadPercentage` | Integer | — | — | Wahrscheinlichkeit, dass ein gespawntes Schiff eine Ladung bekommt |
| `ShipSpawner/ShipLoadPool` | Quest | — | 0 | Pool aus dem zufällig eine Ladung bestimmt wird für gespawnte Schiffe |
| `ShipSpawner/ShipPercentageToBestPlayer` | Integer | — | — | Verhältnis der Schiffe zum besten Spieler, 50% sind beispielsweise halb so viele Schiffe. Es werden aber nie mehr als im Maximum der aktuellen Stufe eingestellt |
| `ShipSpawner/ShipSpawnIntervall` | Time | — | — | Intervall in dem gecheckt wird ob ein neues Schiff produziert wird |
| `ShipSpawner/ShipSpawnPool` | Quest | — | 0 | Pool aus dem Schiffe zum Spawnen ausgewählt werden |
| `ShipSpawner/ShipsPerLevel` | Array | — | — | Minimale und maximale Anzahl an Schiffen pro Stufe |

## ShipTrade

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `ShipTrade/CheckShipLimit` | Boolean | — | — | Wenn auf true gesetzt dürfen keine Schiffe verkauft werden wenn das Schiffslimit erreicht wurde |
| `ShipTrade/SellShipsPlayerAlreadyOwns` | Boolean | — | 1 | Wenn auf false gestellt werden keine Schiffe verkauft, die der Spieler schon besitzt.(Schiffe mit derselben GUID) |
| `ShipTrade/ShipBuyPricePercentage` | Integer | — | — | Wieviel Prozent des normalen Preises zahlt der CSP für Schiffe. 0=CSP kauft keine Schiffe |
| `ShipTrade/ShipCountPerLevel` | Array | — | — | Wie viele Schiffe werden gleichzeitig pro Stufe zum Verkauf angeboten (Schiffsverkaufsslots) |
| `ShipTrade/ShipPool` | Quest | — | 0 | Pool aus dem Schiffe ausgewählt werden, die verkauft werden |
| `ShipTrade/ShipSellCooldown` | Time | — | — | Spawn-Pause nach dem ein Schiff verkauft wurde. |
| `ShipTrade/ShipSellPricePercentage` | Integer | — | — | Wieviel Prozent des Standardpreises verlangt der CSP für seine Schiffe ? |
| `ShipTrade/ShipTradeEnabled` | Boolean | — | 1 | wenn auf false gesetzt ist der Schiffshandel beim Start ausgeschaltet und kann über Meldungen wieder angeschaltet werden |

## Standard

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Standard/Available` | Boolean | — | — | Verfügbarkeit des Charakters |
| `Standard/Description` | Text | — | 0 | Text zur Beschreibung des Profils (wird nirgends verwendet) |
| `Standard/DestroyKontorDropPercentage` | Integer | — | — | Zu welcher Wahrscheinlichkeit wird ein Item gedroppt wenn ein Kontor dieses Spielers von einem menschlichen Spieler zerstört wurde |
| `Standard/DestroyKontorDropPool` | Quest | — | 0 | Aus welchem Reward-Pool wird ein Item gedroppt wenn ein Kontor dieses Spielers von einem menschlichen Spieler zerstört wurde |
| `Standard/Difficulty` | Choice | — | Easy | Schwierigkeit des Charakters (ohne Auswirkungen auf das Spiel) |
| `Standard/Enabled` | Boolean | — | 1 | Verfügbarkeit des Charakters |
| `Standard/GUID` | Text | — | 0 | GUID des Profils |
| `Standard/HideInDiplomacyMenu` | Boolean | — | — | Wenn auf true gesetzt wird dieser Charakter nicht im Diplomatie-Menü angezeigt |
| `Standard/IsAttackable` | Boolean | — | — | Nur wenn auf true gesetzt kann dieser Spieler angegriffen werden |
| `Standard/Name` | String | — | — | Name des Profils |
| `Standard/NamePool` | Choice | — | None |  |
| `Standard/Nation` | Choice | — | Player | Zu welcher Nation gehört der Charakter |
| `Standard/Picture` | FileName | — | — | Für die Profilauswahl im Menü verwendetes Bild |
| `Standard/PlayerType` | Choice | — | Empty | Spielertyp des Charakters |
| `Standard/PortraitBackground` | FileName | — | — | Background-File des Profil-Portraits |
| `Standard/PortraitFilename` | FileName | — | — | Portrait des Profils |
| `Standard/ProfileColor` | Color | — | -16777216 | Spielerfarbe des Charakters |
| `Standard/Sex` | Choice | — | Male | Geschlecht des Charakters |
| `Standard/ShortName` | Text | — | 0 | Kurzname des Charakters. Beispielsweise "Richard" statt "Lord Richard Northburg" |
| `Standard/Symbol` | Text | — | 0 | Für den Charakter verwendetes Symbol |
| `Standard/SymbolTexture` | FileName | — | — | Textur für das Symbol des Charakters |

## TownAcquisition

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `TownAcquisition/BudgetAfterTakeover` | Integer | — | — | mit welchem Budget-Wert wird nach einer Übernahme wieder gestartet? |
| `TownAcquisition/BudgetPerMinute` | Integer | — | — | wie viel Budget bekommt die KI pro Minute für Aktienkauf/Übernahme |
| `TownAcquisition/MinBalanceForSharePurchase` | Integer | — | — | KI braucht mindestens diese Bilanz um Aktien zu kaufen |
| `TownAcquisition/PreferMainAttack` | Integer | — | — | KI wählt zu x% eine Hauptinsel bei einer versuchten Übernahme |
| `TownAcquisition/PreferMainDefense` | Integer | — | — | KI wählt zu x% die eigene Hauptinsel beim Verteidigen |
| `TownAcquisition/Prios` | Array | — | — | wie wichtig ist der KI eine der Aktionen (die Werte sind beliebig aber positiv, sie bestimmen das Verhältnis der Aktionen untereinander) |
| `TownAcquisition/TownAquisitionInterval` | Time | — | — | wie häufig prüft die KI einen Aktienkauf |

## Trade

| Dial | Type | Range | Default | Description (German) |
|---|---|---|---|---|
| `Trade/ActiveTradeDelayTime` | Time | — | 1200000 | AKTIVHANDEL: Wartezeit, bis er wieder versucht, einen aktiven Handel durchzufuehren! |
| `Trade/AllyBuyPrice` | Integer | — | 100 | Im Bündnis: Der Preis, den der Spieler für die Waren des CSPs zahlt, wenn dieser am eigenen Kontor verkauft. In Prozent vom Standardpreis. |
| `Trade/AllySellPrice` | Integer | — | 100 | Im Bündnis: Der Preis, den der Spieler für seine Waren beim CSPs erhält, wenn Spieler am Kontor des CSP verkauft. In Prozent vom Standardpreis. |
| `Trade/BuyPrice` | Integer | — | 100 | Der Preis, den der Spieler für die Waren des CSPs zahlt, wenn dieser am eigenen Kontor verkauft. In Prozent vom Standardpreis. |
| `Trade/DeniedWarePriority` | Integer | 0..100 | 100 | AKTIVHANDEL: Gewichtung, die zur Auswahl im aktiven Handel der dringend benoetigter Waren einfliesst. |
| `Trade/IndependentSlotCount` | Integer | 0.. | 3 | Anzahl an Notfallslos zum Ankauf von Waren am eigenen Kontor des CSPs. Kann Verkaufsslost überschreiben. |
| `Trade/ItemBuyPrice` | Integer | — | 100 | Modulator auf den Preis, der beim Verkauf von Items verlangt wird |
| `Trade/ItemSellPrice` | Integer | — | 100 | Modulator auf den Presi, der für Items gezahlt wird |
| `Trade/MaxActiveTradeCount` | Integer | 0..4 | 2 | Maximale Anzahl an aktiv gehandelten waren |
| `Trade/MaxTradeAmount` | Integer | 0..100 | 30 | Maximale Menge, die die KI in Tonnen im passiven Handel pro slot einstellt! |
| `Trade/MinPassiveSellAmount` | Integer | 0..1000 | 10 | Minimale Verkaufsmenge im Passiven Handel |
| `Trade/PassiveTradeCooldown` | Time | — | 1200000 | Intervall, wann die KI erneut Waren in den passiven Handel einstellen darf! |
| `Trade/PreferredSellWares` | Array | — | — | Wenn die KI mehrere Waren wg. Überschuss verkaufen kann, werden hier gewichtete Waren bevorzugt. Die angegeben Gewichtung wird absolut gewertet. D.h. Eine 1 kann auschlaggebend sein,wenn alle anderen Waren auf 0 gesetzte sind. |
| `Trade/PreferredWarePriority` | Integer | 0..100 | 100 | AKTIVHANDEL: Gewichtung, wie stark die bevorzugte Ware in die Auswahl der Aktiven Waren miteinfliessen! |
| `Trade/PreferredWareSellPrice` | Integer | — | — | Preis in Prozent für alle Lieblingswaren des CSP, wenn man dem CSP die Ware verkauft. |
| `Trade/PreferredWares` | Flags | — | — | Lieblingswaren des CSPs |
| `Trade/PriceRegionIntervall` | Integer | 0..100 | 40 | AKTIVHANDEL: Prozentwert, zwischen dem Standardpreis einer Ware und dem aktuell eingestellten Preis, in der gehandelt wird |
| `Trade/ProductPricePriority` | Array | — | — | Beim Verkauf von Waren durch die KI: Erhoeht den eingesetzten Preis vom Mittelwert um die angegebene Prozentzahl. |
| `Trade/ProductSellAmount` | Integer | — | 60 | Schwellenwert des Lagerbestandes zum Verkauf von Waren. In Tonnen angegeben. Waren werden verkauft sobald sich mehr als der angegebene Wert im Lager befinden. PreferredSellWares entscheidet bei mehreren überschüssicgen Waren. |
| `Trade/SellPrice` | Integer | — | 100 | Der Preis, den der Spieler für seine Waren beim CSPs erhält, wenn Spieler am Kontor des CSP verkauft. In Prozent vom Standardpreis. |
| `Trade/SellSlotCount` | Integer | 0..100 | 20 | Anzahl an Verkaufsslots prozentual zu der Anzahl der verfügbaren Slots. (Prozentwert zwischen 0 und 100). Ein Slot ist allerdings immer dafür reserviert |
| `Trade/TradeWilling` | Integer | — | — | ALTER WERT: Wird nicht mehr benutzt. GP bitte prüfen und löschen. |
