"""Which words in a borehole description are ordinary, and which are worth a second look.

The rule runs the opposite way from what it looks like at first sight. A list of interesting terms
can only ever find what somebody thought of in advance, and a geotechnician wants the oddity
precisely BECAUSE nobody expected it. So `ORDINARY` is an allowlist - the plain matrix (zand,
klei, leem, silt), its usual modifiers, the colours, the moisture and consistency words, the
drilling method, the sample administration and the units - and everything else a description names
surfaces. A word nobody put on the list is by definition a rarity.

**The vocabulary only decides what is ORDINARY and therefore suppressed. Anything unknown is
flagged.** An incomplete list therefore produces noise, never a missed rarity: the failure
direction is the harmless one, and it must never be inverted for convenience.

Nothing here interprets. What a term MEANS for the ground is never concluded, only quoted: the
layer's own sentence and its depth go into the report beside the word.

The lists were curated against the real thing, not from Dutch intuition. `scripts/
lithology_vocabulary.py` counts every layer description around twelve points spread over the
geological settings of Flanders - the coastal polders, sandy Flanders, the Scheldt valley, the
Boom clay, the loess belt, the Campine, the Maasland gravels and two cities for made ground - and
every word below earned its place in that count. Re-run that script when DOV changes or when a
region turns out noisy, and widen ORDINARY from its frequency table.

Four things that count, and not convention, settled.

*Half the old descriptions are in French.* "sable", "gris", "argile", "avec" are among the most
frequent words in the whole corpus. Without them every pre-war borehole would flag on every layer,
so the French matrix, colours and modifiers are ordinary too.

*A coded description holds no words.* A layer of the gecodeerde lithologie reads
"FZ (groenbruin) bijmenging: SI/M, GL/N" - machine codes, not observations - and scanning it only
produces "bijmenging" over and over. Those layers are skipped; the codes stay untranslated (see
the known debt in CLAUDE.md), so nothing is claimed about them.

*A bed is a rarity, an admixture is not.* Shells are named some 380 times in the sample and almost
all of them are admixtures: "schelpen" 141, "coquilles" 124, "schelpengruis" 92, "schelpgruis" 16,
against 21 for the French "banc"/"bancs" that marks a bed. There is no "schelpenbank" compound
anywhere in the sample - the bed carries its own word instead. So the plain shell words are
ordinary and the bed is caught by the word that marks it (`bank`, `banc`, `bancs`, and every
compound built on a flagged material such as "zandsteenniveau"), while `laag`/`lagen`/`laagje` and
the singular `niveau` stay ordinary: they are used constantly for ordinary clay laminae in sand and
for plain depth levels.

*"geen kalk" is not a report of kalk.* A description that denies a material must not be quoted as
if it named one, so a word preceded by a denial is skipped (`DENIALS`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from .model import LithologyLayer

# The plain matrix, its modifiers, and everything a description says about how the sample looked,
# felt and was taken - in Dutch and in the French of the older records. Extend THIS list to quieten
# a word that turns out to be ordinary after all; that is the knob, never the flagging rule.
ORDINARY = frozenset("""
aalter aan aangevuld aangevulde aantal abondants af affleure affleurement afgerond afw afwisselend
afwisselende afwisseling ale alluviaal alluvial alluviale als alsmede altéré amas analogue andere
aquifère argile argiles argileuse argileuses argileux argilo arm asse assez au aux avec bas base
basis basisklei beaucoup beetje beige bepaalde berm beschrijving bevatten bewaarde bien bigarré
bij bijna bijzonder blanc blanche blanchâtre blauw blauwachtige blauwe blauwgrijs blauwgrijze
blauwgroen blauwgroenwit bleek bleekgeel bleekgeelgroen bleekgrijs bleekgrijsgroen bleekgrijze
bleke blekere bleu bleue bleuâtre blijft blokken boom boorbeschrijving boormeester boring bouwlaag bouwvoor
bouwzand boven bovenaan bovengrond bovenste brede breed brisées brokje brokjes brokkelig brokkelige brokken brokstukken
brosse bruin bruinachtig bruinachtige bruine bruingeel bruingeelachtig bruingrijs bruingrijsachtig
bruingrijze bruingroen bruingroenachtig brun brune brunâtre calcaires calcarifère ce cette chemin
chocolaté citadel clair claire cm coherent coherente cohérent comme compact compacte complex
concentratie concentraties contact contient coquillages coquille coquilles coquillier couche
couches coupe cremebruin daaronder dan dans dat de deels delen demi des dessus determineerbare
detritus devenant devient diameter dicht die diepte dik dikke divers dm doch donker donkerblauw
donkerbruin donkerbruine donkerder donkere donkergrijs donkergrijze donkergroen donkergroene door
doorheen doorschijnend droog du duidelijk dun dunne dunner dur dure débris eau ech edelmanboor een
eenige einde elementen elle en enigszins enigzins enkele entre environ er est et exemplaren
extreem facies fijn fijne fijner fijnste fijnzand fijnzandhoudende fin fine finement flandriaan
flandrien foncé foncée fond formatie fragmenten fragmentjes fragments friable gauche geboord
gebroken gedeelte gedeeltelijk gedeelten gedraaid geel geelachtig geelbruin geelbruinachtig
geelgrijs geelgroen geelgroenachtig geellichtgroen geelrode geen gegolfd gegolfde gehele gelaagd
gelaagdheid gele geleidelijk gelijke gemarmerd gemengd gemiddeld geoprobe gepakt geroerd gerold
gerolde gesorteerd gespikkeld gestippeld gevlekt gewassen gijze glad glaise glaiseuse glauconie
glimmer glimmerachtig glimmerhoudend glimmerplaatjes glimmerrijk glimmers goed grains grand
grandes gras grens grenzen grijs grijsachtig grijsachtige grijsbeige grijsblauw grijsbruin
grijsbruine grijsgeel grijsgroen grijsgroenachtig grijsgroene grijswit grijze grijzer grijzere
grind grindboring grindje gris grise grisâtre groen groenachtig groenachtige groenblauw groenbruin
groene groengeel groengrijs groengrijsachtig groengrijze groenig grof grofzand grond groot gros
grosse grosses grossier grossière grote grotere grove grover grovere gruis half halffijn
halfstijve hard harde haut hebben heeft heel helft het heterogeen heterogene heteromorf hoekig
hoeveelheden hoger homogeen homogène hoofdzakelijk horizontaal houdend hsc humeus humeuze humide
humiques humus hétérogène ici idem ieper ieperiaan iets in inf inférieur inférieure insluitsel
insluitsels intercalaties is jaune jaunâtre jusqu kakikleurig kalk kalkarm kalkhoudend
kalkhoudende kalkloos kalkrijk kalkrijke keitjes kern kernboor kist klei kleiachtig kleiachtige
kleibrokjes kleibrokken kleigehalte kleihoudend kleihoudende kleiig kleiige kleiiger kleiigere
kleilaagje kleilaagjes kleilagen kleilensjes kleilenzen klein kleine kleiner kleirijk kleiïg kleur
komen korrel korrelgrootte korrelig korrels kwartair kwarts kwartsachtig kwartszand la laag laagje
laagjes laagsgewijs lagen lang le lediaan leem leemachtig leemhoudend leemrijke lemig lemige
lengte lensjes lentilles lenzen les licht lichtbeige lichtbruin lichte lichtgrijs lichtgroen
lichtjes lid lijkt limon limoneuse limoneuses limoneux linéoles lit lithotheek lits lokaal lokale
loodrecht los losse losser lossere légèrement maar mais maldegem massa massief materiaal matig matières
medium meer meerdere meestal met meter meters meuble micacé micacée micacées middelfijn middelgrof
middelmatig middelmatige min mince minder mm moderne modernes moins molle monster monsters mooi
mooie morceaux mou même na naar nat nesten neutraal normaal normale neutraalbruin neutraalgrijs niet niveau
niveau_onbekend nog nogal noir noire noirs noirâtre nombreuses nombreux non nu of om omstreeks
onbekend onder onderaan onderste ongeveer onregelmatig onregmatig ontbreekt ook ookpaniseliaan op
opnieuw oranje oranjebruin organisch organische over overgaat overgang overvloed overwegend paar
paillettes pailletée paillété paniseliaan par parfois partie parties pas passant percé percés
petit petite petites petits peu plaats plaatselijk plaatselijke plaatsen place plant plantaardig
plantaardige planten plantje plastique plastisch plastische plastischer plat platte plus pointillé
pointillée polders pour profondeur puis pulsboring pur pure pâle quartair quarts quartseux
quartzeux quaternaire que quelques qui ramkernsondering rares recent recente reeds resten rijk
rode roestbruin roetzwart rond ronde rood roodachtig roodbruin rouge rougeâtre roulé roulés route
roux rude rupeliaan sable sables sableuse sableuses sableux sablière sablonneux sale samenhangend
sans saturé schelp schelpen schelpengruis schelpfragmenten schelpgruis schelphoudend schelpjes
schelpstukken scherp scherpe schijn schilferachtig schilferig schilferige schuin sec semblable
silt silteus silteuse silteux silteuze silthoudend silthoudende siltig siltrijk situ situé slap
slappe slecht smalle sol sommet sommige soms sont sous spikkels spoelboring sporadisch sporadische
sporen staal stabilisatiezand stalen steeds steekboor steen steentjes stenen sterk stevig stevige
stijf stijgt stijve stippels stippen stoffen stratification stratifié stuk stukje stukjes stukken
substraat suite sup supérieur supérieure sur taai taaie taches talrijk talrijke tamelijk te
teelaarde teeltaarde terre tertiair
terug toch toe top tot tout traces tres très trés tussen type typisch uit uiterst un une van vanaf
vase vast vaste veel vegetale vele verbrijzeld verbrijzelde verdieping verdâtre verdâtres
vergruisde verhard verkleurend verkleurende verkleuring vermengd vermoedelijk vers verschillende
verspreid verspreide vert verte verticaal verweerd verweerde verwering verzadigd vet vette vettig
visible vlekjes vlekken vochtig vol volgens volledig voor vooral voorkomen voornamelijk voorwerk
vormen vrij végétale waaronder waarschijnlijk was wat water waterzand weer weinig weke wemmeliaan
werd wit witachtig witachtige witgeel witgrijs witgrijze witte wordt wortel wortels worteltjes
zacht zachte zand zandachtig zandachtige zanden zandhoudend zandhoudende zandig zandige zandiger
zandigere zandlaagjes zandlagen zandleem zavel zavelgrond zeer zelfde zijn zoet zoetwater zoetwaterschelpen
zonder zone zones zwak zwakke zware zwart zwartbruin zwartdonkergroene zwarte zwartgrijs één
""".split())

# Words that surface whatever else the sentence says, because a geotechnician asked for them by
# name: a concretion of any kind, sandstone, glauconite, peat and man-made debris. They live here
# rather than merely outside ORDINARY so that widening ORDINARY can never silence them. Matched as
# a stem, so "glauconiethoudend" and "glauconietrijk" both count.
ALWAYS_NOTABLE = ("concreti", "konkreti", "zandsteen", "glauconiet", "glauconif", "veen", "turf",
                  "tourbe", "ligniet", "baksteen", "beton", "asfalt", "puin", "houtskool",
                  "kolengruis", "koolas", "keramiek", "metaal", "glashoudend", "kassei",
                  "straatsteen", "geremanieerd", "talus", "slak", "sintel")
# Fossil, genus and species names, and the words for what a fossil is. SUPPRESSED, exactly like
# ORDINARY: a species name says which formation you are standing in, not that you will hit
# anything, and a geotechnician asked for it to disappear from the remarks ("nummulites planulatus
# shouldn't be flagged at all"). That is a domain call, and it widens the ordinary side of the
# rule, which is its safe direction - never narrow the flagging rule itself for convenience.
#
# Why these and not the `ALWAYS_NOTABLE` materials: sandstone, peat and rubble are things a machine
# meets, and the user named them for exactly that reason; a Nummulites is a date stamp. So do not
# "helpfully" restore these to the flagged side - it was asked for, not overlooked. A shell BED is
# unaffected: it is caught by the word that marks it (`bank`, `banc`), never by the species in it.
#
# Harvested from the same frequency count as ORDINARY (nummulites 31, cardium 22, ditrupa 15,
# ostrea 13, planulatus 12 ...); extend it here.
FOSSILS = frozenset("""
ammonites annelides annélides anoplo arca astarte belemnieten bivalve bivalves bryozoa bryozoaires
bryozoen buccinum cardita cardium cerithes cerithium coquiller coquillière coquillières corbula
corbules corneus crinoiden cymbula dentalium ditrupa echinodermen edita edule elegans foraminifera
foraminiferen fossiel fossielen fossielenen fossielfragmenten fossielhoudend fossielhoudende
fossielrijk fossilifère gastropoden gebrokenschelpjes glycimeris haaietand haaietanden hispida
laevigatus lingula lucina macrofossielen meerfossielhoudend myabivalves mytilus natica nucula
nummulieten nummulites nummulitesplanulatus orbignyi ostrea pecten phora planicosta planulata
planulatus porulosum roggetanden schelpbrokjes schelpdelen schelpenbrokjes schelpenbrokken
schelpenfragmenten schelpenhoudend schelpenpuin schelpenresten schelpenrijke schelpensporen
schelpfragmentjes schelprestjes schelpresten schelpstukjes serpula stukkenfossielen tenuissima
terebratula turbinolia turritella variolaria variolarius venericardia vijverschelpen vistanden
wemmelensis zoetwaterschelpjes
""".split())
# A denial in front of a word: "geen kalk" reports no kalk at all.
DENIALS = ("geen", "zonder", "sans", "vrij van")
# The same denial carried as a suffix: "zandsteenvrij", "kalkloos", "glauconietarm". Without this
# the material stem won over everything and the report claimed a sandstone the layer says is
# absent - the very error DENIALS exists to prevent, spelled the other way round.
DENYING_SUFFIXES = ("vrij", "loos", "arm")
# Kleuren, en alles wat ervan gemaakt wordt. Een kleur zegt niets over wat een machine tegenkomt,
# en de klasse is productief: lichtbruine, bruinzwarte, roestkleurige, geelgroen. Als stam
# gematcht, dus de verbuigingen (-e, -en, -ig, -achtig) komen er gratis bij.
COLOUR_STEMS = ("bruin", "geel", "grijs", "grijze", "zwart", "groen", "rood", "rode", "blauw",
                "wit", "beige", "oranje", "paars", "roest", "oker", "creme", "crème", "kaki",
                "bleek", "donker", "licht", "kleurig", "kleurige", "gevlekt", "gespikkeld",
                "gemarmerd")
# Gewone stammen waarop een modificator gebouwd mag worden. Bewust NIET "steen": steenbrokken en
# silexkeien zijn juist wat een geotechnicus wil zien.
ORDINARY_STEMS = ("zand", "klei", "leem", "silt", "grind", "kalk", "kwarts", "schelp",
                  "schelpen", "plant", "planten", "wortel", "wortels", "glimmer", "mica",
                  "humus", "zavel", "loess", "löss", "slib", "detritus",
                  "oxidatie", "verwering", "gley")
# Achtervoegsels die van een gewone stam een gewone beschrijving maken: bijmenging, niet materiaal.
MODIFIER_SUFFIXES = ("houdend", "houdende", "rijk", "rijke", "achtig", "achtige", "ig", "ige",
                     "vlekken", "vlekjes", "brokjes", "brokken", "lenzen", "laagjes", "gruis",
                     "resten", "rest", "restjes", "fragment", "fragmenten", "fragmentjes",
                     "je", "jes", "stippen", "spikkels", "korrels", "sporen", "fractie",
                     "lens", "lensje", "lensjes")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_LENGTH = 3  # one- and two-letter tokens are units and coded shorthand, not observations
# "Num. planulatus", "(Ech.)", "Incl. 10", "enz. (aangevuld)": a short token cut off by its own
# full stop in the middle of a sentence is shorthand, and printing the stump ("num") in a client
# report looks like the bug it is. Both signals have to agree - short AND mid-sentence - so that
# "glauconiethoudend." at the end of a sentence stays the observation it is.
ABBREVIATION_MAX = 4
CODED = "gecodeerd"


@dataclass(frozen=True)
class NotableTerm:
    """One word a description used that is not ordinary, with where it stands and what it says."""
    word: str
    depth: str
    quote: str


def _abbreviated(text: str, match) -> bool:
    """Whether this token is shorthand cut off by its own full stop instead of a whole word.

    The full stop after the last word of a sentence is punctuation and belongs to the sentence;
    a full stop inside one belongs to the word in front of it, and a word that carries one is an
    abbreviation. Only short ones: the descriptions end sentences with "zand." and
    "glauconiethoudend." too, and those are words, not stumps.

    Where a description simply stops there is nothing left to recognise an abbreviation BY, so
    nothing is guessed: "gips.", "löss." and "grès." are four-letter observations and stay. The
    handful of stumps that end a description ("afw.", "situ.") are quietened through ORDINARY,
    the one knob this module allows.
    """
    rest = text[match.end():]
    if not rest.startswith(".") or len(match.group(0)) > ABBREVIATION_MAX:
        return False
    after = rest[1:].lstrip()
    return bool(after) and not after[:1].isupper()


def _denied(text: str, start: int) -> bool:
    """Whether a denial stands immediately in front of this word.

    The denial has to be a WHOLE word. Tested against raw text it also matched every word ending
    in one - "heterogeen puin" and "homogeen veen" denied nothing and yet lost their material,
    and "bijzonder veel baksteen" lost its baksteen through "zonder". Both adjectives are on the
    ordinary list themselves, so the two materials `ALWAYS_NOTABLE` exists to protect vanished
    without a trace: the one failure direction this module forbids.
    """
    before = text[max(0, start - 24):start].lower().rstrip()
    return any(before.endswith(denial)
               and (len(before) == len(denial) or not before[-len(denial) - 1].isalpha())
               for denial in DENIALS)


def _is_colour(word: str) -> bool:
    """A colour, or anything built out of one."""
    return any(stem in word for stem in COLOUR_STEMS)


def _is_modified_ordinary(word: str) -> bool:
    """An ordinary stem carrying a modifier: fijnzandhoudend, kleivlekken, schelpje, plantenresten.

    These describe HOW MUCH of the plain matrix is in the layer, which is ordinary ground however
    it is spelled, and the class is productive enough that listing the words is hopeless. The stem
    is what decides, so a material from `ALWAYS_NOTABLE` keeps flagging through the same shapes -
    veenhoudend, veenbrokjes, veenlaagje - because that check runs first.
    """
    for suffix in MODIFIER_SUFFIXES:
        if len(word) > len(suffix) and word.endswith(suffix):
            stem = word[:-len(suffix)].rstrip("-")
            # Only the named stems, never "any ordinary word": "steen" is an ordinary word on its
            # own and that would quietly turn steenbrokken into gewone grond, which is the one
            # thing a geotechnician asked to keep seeing.
            if stem.endswith(ORDINARY_STEMS):
                return True
    return False


def _is_compound_ordinary(word: str) -> bool:
    """Twee gewone stammen aan elkaar: zandleem, kleizand, leemzand.

    Vlaamse boorbeschrijvingen bouwen textuurnamen door ze te plakken, en het paar zegt niets meer
    dan elke helft apart. `ALWAYS_NOTABLE` gaat voor, dus veenzand en zandsteen blijven staan.
    """
    for stem in ORDINARY_STEMS:
        if len(word) > len(stem) and word.endswith(stem):
            if word[:-len(stem)].rstrip("-") in ORDINARY_STEMS:
                return True
    return False


def is_ordinary(word: str) -> bool:
    """Whether a single word belongs to the plain vocabulary of a soil description.

    The flagging rule itself is untouched: what is not ordinary still flags. What widened is the
    ordinary side, and by RULE rather than by a longer list - colours and their compounds, and an
    ordinary stem carrying a modifier - because a reader told us the remarks were drowning in
    adjectives ("kleuren niet vermelden, plantenresten ook niet roestkleurig ook niet").
    `ALWAYS_NOTABLE` is checked before all of it, so nothing he asked to see can be widened away.
    """
    lowered = word.lower()
    # A denial first of all: "zandsteenvrij" reports no sandstone, so it must not be caught by the
    # sandstone stem on the line below.
    if any(lowered.endswith(suffix) for suffix in DENYING_SUFFIXES):
        return True
    if any(stem in lowered for stem in ALWAYS_NOTABLE):
        return False
    if lowered in FOSSILS:
        return True
    if _is_colour(lowered) or _is_modified_ordinary(lowered):
        return True
    if _is_compound_ordinary(lowered):
        return True
    return len(lowered) < MIN_LENGTH or lowered in ORDINARY


def notable_terms(layers: Sequence[LithologyLayer]) -> List[NotableTerm]:
    """Every word in these layer descriptions that is not ordinary, once per word.

    The first layer that names a word wins its quote and its depth: a word repeated down twenty
    layers is one observation, not twenty, and what the reader needs is where it starts. Coded
    layers are skipped - they hold codes, not words.
    """
    found: List[NotableTerm] = []
    known = set()
    for layer in layers:
        if layer.kind == CODED:
            continue
        text = " ".join(str(layer.description).split())
        for match in WORD.finditer(text):
            lowered = match.group(0).lower()
            if lowered in known or is_ordinary(lowered) or _denied(text, match.start()):
                continue
            if _abbreviated(text, match):
                continue
            known.add(lowered)
            found.append(NotableTerm(lowered, f"{layer.top_m:.2f}-{layer.base_m:.2f} m", text))
    return found


def summarise(terms: Iterable[NotableTerm]) -> str:
    """The words of one borehole on one line, each with the depth it was first named at."""
    return "; ".join(f"{term.word} ({term.depth})" for term in terms)
