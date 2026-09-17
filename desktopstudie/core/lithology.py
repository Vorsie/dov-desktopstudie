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

*A bed is a rarity, an admixture is not.* Shells are named 400+ times in the sample and almost all
of them are admixtures ("zeer weinig schelpgruis", "met schelpen", "resten schelpen", "avec
coquilles"); the beds read "laag van verbrijzelde schelpen" or "coherente bank". There is no
"schelpenbank" compound anywhere in the sample. So the shell words themselves are ordinary and the
bed is caught by the word that marks it - `bank`, `niveau` - while `laag`/`lagen`/`laagje` stay
ordinary, because they are used constantly for ordinary clay laminae in sand.

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
aalter aan aangevuld aangevulde aantal abondants af affleure affleurement afgerond afwisselend
afwisseling ale alluviaal alluvial alluviale als alsmede altéré amas andere aquifère argile
argiles argileuse argileuses argileux argilo arm asse assez au aux avec bas base basis basisklei
beaucoup beige bepaalde berm beschrijving bevatten bewaarde bien bigarré bij bijna blanc blanche
blanchâtre blauw blauwachtige blauwe blauwgrijs blauwgrijze blauwgroen blauwgroenwit bleek
bleekgeel bleekgeelgroen bleekgrijs bleekgrijsgroen bleekgrijze bleke blekere bleu bleue bleuâtre
blijft blokken boom boorbeschrijving boormeester boring bouwvoor bouwzand boven bovenaan
bovengrond brisées brokjes brokken brokstukken bruin bruinachtig bruinachtige bruine bruingeel
bruingeelachtig bruingrijs bruingrijsachtig bruingrijze bruingroen bruingroenachtig brun brune
brunâtre calcaires calcarifère ce cette chemin chocolaté clair claire cm coherent coherente
cohérent compact compacte complex contact contient coquillages coquille coquilles coquillier
couche couches coupe cremebruin daaronder dan dans dat de deels delen demi des dessus
determineerbare devenant devient diameter dicht die diepte dik dikke divers dm doch donker
donkerblauw donkerbruin donkerbruine donkerder donkere donkergrijs donkergrijze donkergroen
donkergroene door doorheen droog du duidelijk dunne dunner dur dure débris eau ech edelmanboor een
eenige einde elementen elle en enigszins enigzins enkele entre environ er est et exemplaren
extreem facies fijn fijne fijner fijnste fijnzand fijnzandhoudende fin fine finement foncé foncée
fond formatie fragmenten fragmentjes fragments friable gauche geboord gebroken gedeeltelijk geel
geelachtig geelbruin geelbruinachtig geelgrijs geelgroen geelgroenachtig geellichtgroen geelrode
geen gegolfd gegolfde gehele gelaagd gele geleidelijk gelijke gemarmerd gemengd gemiddeld geoprobe
gepakt geroerd gerold gerolde gesorteerd gespikkeld gestippeld gevlekt gewassen gijze glaise
glaiseuse glauconie glauconietarm glauconietkorrels glimmer glimmerachtig glimmerhoudend
glimmerplaatjes glimmerrijk glimmers goed grains grand grandes gras grens grenzen grijs
grijsachtig grijsachtige grijsbeige grijsblauw grijsbruin grijsbruine grijsgeel grijsgroen
grijsgroenachtig grijsgroene grijswit grijze grijzer grijzere grindboring gris grise grisâtre
groen groenachtig groenachtige groenblauw groenbruin groene groengeel groengrijs groengrijsachtig
groengrijze groenig grof grofzand grond groot gros grosse grosses grossier grossière grote grotere
grove grover grovere gruis half halffijn halfstijve hard harde haut hebben heeft heel helft het
heterogeen heterogene heteromorf hoekig hoeveelheden hoger homogeen homogène hoofdzakelijk
horizontaal houdend hsc humeus humeuze humide humiques humus hétérogène ici idem ieperiaan iets in
inférieur inférieure intercalaties is jaune jaunâtre jusqu kakikleurig kalk kalkarm kalkhoudend
kalkhoudende kalkloos kalkrijk kalkrijke keitjes kern kernboor kist klei kleiachtig kleiachtige
kleibrokjes kleibrokken kleigehalte kleihoudend kleihoudende kleiig kleiige kleiiger kleiigere
kleilaagje kleilaagjes kleilagen kleilensjes kleilenzen klein kleine kleirijk kleiïg kleur komen
korrel korrelgrootte korrelig korrels kwartair kwarts kwartsachtig kwartszand la laag laagje
laagjes laagsgewijs lagen lang le lediaan leem leemachtig leemhoudend leemrijke lemig lemige
lengte lensjes lentilles lenzen les licht lichtbeige lichtbruin lichte lichtgrijs lichtgroen
lichtjes lid lijkt limon limoneuse limoneuses limoneux linéoles lit lithotheek lits loodrecht los
losse légèrement maar mais maldegem massa massief materiaal matig matières medium meer meestal met
meter meters meuble micacé micacée micacées middelmatig min mince minder mm modernes moins molle
monster monsters morceaux mou même na naar nat nesten neutraal neutraalbruin neutraalgrijs niet
niveau niveau_onbekend nog noir noire noirs noirâtre nombreuses nombreux non nu of om omstreeks
onbekend onder onderaan ongeveer onregelmatig onregmatig ontbreekt ook ookpaniseliaan op opnieuw
oranje oranjebruin over overgaat overgang overvloed paillettes pailletée paillété paniseliaan par
parfois partie parties pas passant percé percés petit petite petites petits peu plaatselijk place
plastique plastisch plastische platte plus pointillé pointillée polders pour profondeur puis
pulsboring pur pure pâle quartair quarts quartseux quartzeux quaternaire que quelques qui
ramkernsondering rares recente reeds resten rijk rode roestbruin roetzwart rond ronde rood
roodachtig roodbruin rouge rougeâtre roulé roulés route roux rude rupeliaan sable sables sableuse
sableuses sableux sablière sablonneux sale samenhangend sans saturé schelp schelpen schelpengruis
schelpfragmenten schelpgruis schelphoudend schelpjes schelpstukken scherp schijn schilferachtig
schilferig schilferige schuin sec silt silteus silteuse silteux silteuze silthoudend silthoudende
siltig siltrijk situé slap slappe slecht sol sommet sommige soms sont sous spikkels spoelboring
sporadisch sporen staal stabilisatiezand stalen steeds steekboor steen steentjes stenen sterk
stevig stijf stijgt stijve stippels stippen stoffen stratification stratifié stukjes stukken suite
supérieur supérieure sur taches talrijk talrijke tamelijk te terre tertiair terug toch toe top tot
tout traces tres très trés tussen type typisch uit uiterst un une van vanaf vase vast vaste veel
vele verbrijzeld verbrijzelde verdieping verdâtre verdâtres vergruisde verhard vermengd
vermoedelijk vers verspreid verspreide vert verte verticaal verweerd verzadigd vet vette vettig
visible vlekjes vlekken vochtig vol volgens volledig voor vooral voorkomen voorwerk vormen vrij
waaronder waarschijnlijk was wat water waterzand weinig wemmeliaan werd wit witachtig witachtige
witgeel witgrijs witgrijze witte wordt zacht zachte zand zandachtig zandachtige zanden zandhoudend
zandhoudende zandig zandige zandiger zandigere zandlaagjes zandlagen zandsteenvrij zavelgrond zeer
zelfde zijn zoet zoetwater zoetwaterschelpen zonder zone zones zwak zware zwart zwartbruin
zwartdonkergroene zwarte zwartgrijs één
""".split())

# Words that surface whatever else the sentence says, because a geotechnician asked for them by
# name: a concretion of any kind, sandstone, glauconite, peat and man-made debris. They live here
# rather than merely outside ORDINARY so that widening ORDINARY can never silence them. Matched as
# a stem, so "glauconiethoudend" and "glauconietrijk" both count.
ALWAYS_NOTABLE = ("concreti", "konkreti", "zandsteen", "glauconiet", "glauconif", "veen", "turf",
                  "tourbe", "ligniet", "baksteen", "beton", "asfalt", "puin", "houtskool",
                  "kolengruis", "koolas", "keramiek", "metaal", "glashoudend", "kassei",
                  "straatsteen", "geremanieerd", "talus", "slak", "sintel")
# A denial in front of a word: "geen kalk" reports no kalk at all.
DENIALS = ("geen", "zonder", "sans", "vrij van")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_LENGTH = 3  # one- and two-letter tokens are units and coded shorthand, not observations
CODED = "gecodeerd"


@dataclass(frozen=True)
class NotableTerm:
    """One word a description used that is not ordinary, with where it stands and what it says."""
    word: str
    depth: str
    quote: str


def _denied(text: str, start: int) -> bool:
    before = text[max(0, start - 24):start].lower()
    return any(before.rstrip().endswith(denial) for denial in DENIALS)


def is_ordinary(word: str) -> bool:
    """Whether a single word belongs to the plain vocabulary of a soil description."""
    lowered = word.lower()
    if any(stem in lowered for stem in ALWAYS_NOTABLE):
        return False
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
            known.add(lowered)
            found.append(NotableTerm(lowered, f"{layer.top_m:.2f}-{layer.base_m:.2f} m", text))
    return found


def summarise(terms: Iterable[NotableTerm]) -> str:
    """The words of one borehole on one line, each with the depth it was first named at."""
    return "; ".join(f"{term.word} ({term.depth})" for term in terms)
