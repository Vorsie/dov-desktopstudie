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

*A quarter of the descriptions are in French, and they are classified, not translated.* 874 of
the 3630 counted layers are French - "sable" 590, "gris" 342, "avec" 277, "argile" 230 - so
without them every pre-war borehole flags on every layer. The French side got the same treatment
the Dutch side had: the matrix and its modifiers, the colours and everything built on them, the
shells and the plant debris, and the narrative filler of a hand-written 1900s record are ordinary;
the materials stay flagged. What a flagged term is NOT is translated - "cailloux" reaches the
reader as "cailloux", never as "keien" - because the report quotes the description and does not
speak for it.

Two things the French corpus taught that the Dutch one could not. The same word is spelled with
and without its accents ("vegetale" beside "végétale", "gres" beside "grès", "debris"/"dèbris"
beside "débris"), so the comparison strips diacritics instead of listing both (`_plain`). And
French inflects where Dutch compounds - grise/grises, terre/terres, grisâtre for grijsachtig - so
the feminine, the plural and the "-âtre" family are ENDINGS taken off before the lookup
(`FRENCH_ENDINGS`), not thirty extra words.

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
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Sequence

from .model import LithologyLayer


def _plain(word: str) -> str:
    """The word with its diacritics taken off, for comparison only.

    The old records spell the same word both ways and DOV keeps what the clerk typed: "vegetale"
    beside "végétale", "gres" beside "grès", "tres"/"trés" beside "très", "debris"/"dèbris"
    beside "débris". Listing every spelling means guessing which accents a 1904 hand happened to
    set, and the guess is wrong the moment a new borehole is digitised. So the comparison runs on
    the accent-free form and one entry covers them all.

    Only the COMPARISON. The word that reaches the report keeps the spelling the description used
    - nothing here translates a French term or respells it.
    """
    return "".join(c for c in unicodedata.normalize("NFD", word)
                   if unicodedata.category(c) != "Mn")


def _folded(words: str) -> frozenset:
    """One of the word lists below, accent-free, so `_plain` can be looked up straight in it."""
    return frozenset(_plain(word) for word in words.split())


# The plain matrix, its modifiers, and everything a description says about how the sample looked,
# felt and was taken - in Dutch and in the French of the older records. Extend THIS list to quieten
# a word that turns out to be ordinary after all; that is the knob, never the flagging rule.
ORDINARY = _folded("""
aalter aan aangevuld aangevulde aantal abondamment abondantes abondants accident af affleure
affleurement afgerond afw afwisselend afwisselende afwisseling ailleurs ale allure alluviaal
alluvial alluviale alluvion alluvions als alsmede altéré alternance alternances alternant alterne
amas amorphe analogue ancienne andere apparaît apparence apparentes apparents après aquifère argile
argiles argileuse argileuses argileux argilo arguleux arm arrêtée arrondis aspect asse assez assze
atteindre au autour autre autres aux avais avec avex bande bas base basis basisklei beaucoup beetje
beige belle bepaalde berm beschrijving bevatten bewaarde bien bifurcation bigarré bigarrée
bigarrées bij bijna bijzonder bistre bistres bistrés blanc blanchâtre blanche blauw blauwachtige
blauwe blauwgrijs blauwgrijze blauwgroen blauwgroenwit bleek bleekgeel bleekgeelgroen bleekgrijs
bleekgrijsgroen bleekgrijze bleke blekere bleu bleuâtre bleue blijft blokken bombée boom
boorbeschrijving boormeester boring bosse bouleversé bouleversée bouleversées bouleversés bouwlaag
bouwvoor bouwzand boven bovenaan bovengrond bovenste brede breed brillants brisées brokje brokjes
brokkelig brokkelige brokken brokstukken brosse broyée bruin bruinachtig bruinachtige bruine
bruingeel bruingeelachtig bruingrijs bruingrijsachtig bruingrijze bruingroen bruingroenachtig brun
brunâtre brune brusquement buntsandstein caché calcaires calcareuse calcareuses calcareux
calcarifère caractéristiques carrière cas ce celle celui cependent certains ces cette ceux champ
chargé château chemin chocolat chocolaté citadel clacareuses clair claire clairement clairs cm
coherent cohérent coherente coin colen colline comme commence commencement compact compacte complex
composé composés concentratie concentraties constaté contact contenant contient coquiles
coquillages coquille coquilles coquillier coquillières coquilliers cotés couche couches couleur
coupe couronné créées cremebruin crétacé curage curieux daaronder dan dans dat de débris déchire
deels delen demi déposée dépôt dépression dernière des descend descendant descendu descendue
descendus desous dessous dessus determineerbare detritus deux développe devenant devenu devient
diameter dicht die diepte difficile diffues dik dikke diluvien diluviens diluvium dimensions
distance dit divers diverses dizaine dm doch doit donc donker donkerblauw donkerbruin donkerbruine
donkerder donkere donkergrijs donkergrijze donkergroen donkergroene donnant dont door doorheen
doorschijnend doute droite droog du duidelijk dun dunne dunner dur durcie durcies durcissement dure
dures dus eau éboulés ébouleux ech echantillon echantillons éclats edelmanboor een één eenige
effondrements einde elementen elle empêche employé en encavée encore englobée englobés enigszins
enigzins enkele ensuite entendu entre entrée environ épais épaisseur épars éparses er est et était
étangs état etc été être excavations excessivement exemplaren exploité exploitée extreem
extrêmement facies fait ferrugineuse ferrugineuses ferrugineux feuilleté fibreuse fibreux fijn
fijne fijner fijnste fijnzand fijnzandhoudende filets fin fine finement finit fins flammes
flandriaan flandrien fluide fluviatile fluvio focné fois foncé foncée fond fonds formatie forme
former fort fortement fouille fragmentaire fragmenten fragmentjes fragments friable gauche geboord
gebroken gedeelte gedeeltelijk gedeelten gedraaid geel geelachtig geelbruin geelbruinachtig
geelgrijs geelgroen geelgroenachtig geellichtgroen geelrode geen gegolfd gegolfde gehele gelaagd
gelaagdheid gele geleidelijk gelijke gelinden gemarmerd gemengd gemiddeld général geoprobe gepakt
geroerd gerold gerolde gesorteerd gespikkeld gestippeld gevlekt gewassen gijze gîte glad glaise
glaiseuse glauconie glimmer glimmerachtig glimmerhoudend glimmerplaatjes glimmerrijk glimmers goed
grains grand grande grandes gras graveleuse graveleuses graveleux gravir grens grenu grenue grenzen
grijs grijsachtig grijsachtige grijsbeige grijsblauw grijsbruin grijsbruine grijsgeel grijsgroen
grijsgroenachtig grijsgroene grijswit grijze grijzer grijzere grind grindboring grindje gris
grisâte grisâtre grisclair grise groen groenachtig groenachtige groenblauw groenbruin groene
groengeel groengrijs groengrijsachtig groengrijze groenig grof grofzand grond groot gros grosse
grosses grossier grossière grote grotere grove grover grovere gruis half halffijn halfstijve hard
harde hauptmuschelkalk haut hebben heeft heel helft henis hénis hesbayen het heterogeen heterogene
hétérogène heteromorf hettangien hier hoekig hoeveelheden hoger homogeen homogène hoofdzakelijk
horizontaal horizontale horizontalement horizontales hors houdend hsc humeus humeuze humide humique
humiques humus ici idem ieper ieperiaan iets immédiatement impossible impur impuretés in
inclinaison inclinaisons incliné inclinés indéterminables indiqué inf inférieur inférieure
insluitsel insluitsels intercalaties intercalation intercalations irrégulière is isolés jaunâtre
jaune jurassique jusqu kakikleurig kalk kalkarm kalkhoudend kalkhoudende kalkloos kalkrijk
kalkrijke keitjes kern kernboor kerniel keupérien kist klei kleiachtig kleiachtige kleibrokjes
kleibrokken kleigehalte kleihoudend kleihoudende kleiig kleiïg kleiige kleiiger kleiigere
kleilaagje kleilaagjes kleilagen kleilensjes kleilenzen klein kleine kleiner kleirijk kleur komen
korrel korrelgrootte korrelig korrels kwartair kwarts kwartsachtig kwartszand la laag laagje
laagjes laagsgewijs labours lagen lamellaire landenien landenienne lang latérales lavage le lediaan
leem leemachtig leemhoudend leemrijke légende légère légèrement lemig lemige lengte lensjes
lentille lentilles lenzen les lesquelles lesquels licht lichtbeige lichtbruin lichte lichtgrijs
lichtgroen lichtjes lid ligne lijkt limon limoneuse limoneuses limoneux limoniteux linéole linéoles
lit lithotheek lits locaux loin lokaal lokale long loodrecht lorsqu los losse losser lossere lui
luisants maar mais maldegem marbré marbrée mare marin marmoréen marmoréens massa masse massief
massive mate materiaal matières matig medium meer meerdere meestal mélange mélangé mêlé même met
meter meters mètres meuble mica micacé micacée micacées middelfijn middelgrof middelmatig
middelmatige min mince minces minder mm moderne modernes modifiée moins mois molle monster monsters
montée montre montrent mooi mooie morceaux mou mouches moucheté moulage mouvant moyen moyenne na
naar nat neerepen neerrepenien nesten nettement neutraal neutraalbruin neutraalgrijs niet niveau
niveau_onbekend nog nogal noir noirâtre noire noirs nombreuses nombreux non normaal normale
nouvelle nu nulle oblique ocreuse ocreuses ocreux of om omstreeks onbekend onder onderaan onderste
ondulé ondulée ondulées ongeveer ongle onregelmatig onregmatig ontbreekt ook ookpaniseliaan op
opnieuw oranje oranjebruin organisch organische over overgaat overgang overvloed overwegend paar
pailleté paillété pailletée paillettes pâle panaché paniseliaan paquet paquets par paraissant
paraît parfois parmi partie parties partout pas passant peine pense pente percé percer percés petit
petite petites petits peu peut peux pied pieds plaats plaatselijk plaatselijke plaatsen place
places plant plantaardig plantaardige planten plantje plaque plaques plasticité plastique plastisch
plastische plastischer plat plateau platte pleine pleistocène pliocène pliocènes plis plus poche
poches point pointillé pointillée points polder polderienne poldérienne polders polis polit pont
poreuse position pour pouvoir précédent premier première prendre près présentant presque prmière
produites profondeur prouve provenant provoqué puis puissance puits pulsboring pur pure quartair
quarts quartseux quartzeux quaternaire quaternaires que quelques qui quitté quoi racine racines
radicelle radicelles ramène ramkernsondering rapidement rare rarement rares ravinement rayant
recent recente recherches recueilli recueillir redevenir reeds remonte remplissage repose resten
restent retrouvent rijk rivières rode roestbruin roetzwart rond ronde rood roodachtig roodbruin
rose rosé röth rouge rougeâtre roulé roulées roulés route roux rude ruines rupeliaan rupélien sable
sables sableuse sableuses sableux sablière sablonneuse sablonneux sale samenhangend sans saturé
scaldisien scaldisiennes schelp schelpen schelpengruis schelpfragmenten schelpgruis schelphoudend
schelpjes schelpstukken scherp scherpe schijn schilferachtig schilferig schilferige schuin sec sein
semblable sens sensiblement séparées serait seulement siliceuse siliceux sillonnés silt silteus
silteuse silteux silteuze silthoudend silthoudende siltig siltrijk situ situé slap slappe slecht
smalle sol somme sommet sommige soms sondage sonde sondé sont sort sous souterraines souvent
spikkels spoelboring sporadisch sporadische sporen staal stabilisatiezand stalen steeds steekboor
steen steentjes stenen sterk stevig stevige stijf stijgt stijve stippels stippen stoffen
stratification stratifié stratifiés striée striés stuk stukje stukjes stukken substraat successifs
suite sup supérieur supérieure sur surfaces surmonté surmontée surtout taai taaie taches tacheté
talrijk talrijke tamelijk tapissées te teelaarde teeltaarde teinte teintes tendre tendres terrain
terrains terrasse terre terres tertiair tertiaire terug tiers toch toe tongres tongrien top tot
tournant tous tout toutefois toutes trace traces tranche tranchée traversé traversée traverser tres
très trés triturées trous tubulations tussen type typisch uit uiterst un une unes uns van vanaf
varient vase vaseuse vaseux vast vaste veel vegetale végétale végétales végétaux veine veinée
veines veinules vele verbrijzeld verbrijzelde verdâtre verdâtres verdieping vergruisde verhard
véritable véritables verkleurend verkleurende verkleuring vermengd vermiculations vermiculées
vermoedelijk vers verschillende verspreid verspreide vert verte verticaal verticale verweerd
verweerde verwering verzadigd vet vette vettig vient violacé visible visibles vite vlekjes vlekken
vochtig voici voisin voit vol volgens volledig voor vooral voorkomen voornamelijk voorwerk vormen
vrij waaronder waarschijnlijk was wat water waterzand weer weinig weke wellenkalk wemmeliaan werd
wit witachtig witachtige witgeel witgrijs witgrijze witte wordt wortel wortels worteltjes zacht
zachte zand zandachtig zandachtige zanden zandhoudend zandhoudende zandig zandige zandiger
zandigere zandlaagjes zandlagen zandleem zavel zavelgrond zeer zelfde zijn zoet zoetwater
zoetwaterschelpen zonaire zonder zone zoné zonée zones zônes zwak zwakke zware zwart zwartbruin
zwartdonkergroene zwarte zwartgrijs
""")

# Words that surface whatever else the sentence says, because a geotechnician asked for them by
# name: a concretion of any kind, sandstone, glauconite, peat and man-made debris. They live here
# rather than merely outside ORDINARY so that widening ORDINARY can never silence them. Matched as
# a stem, so "glauconiethoudend" and "glauconietrijk" both count.
# The French names stand beside the Dutch ones rather than being translated into them: a flagged
# term is quoted from the description, so "cailloux" reaches the reader as "cailloux". `grès` is
# NOT here - as a stem it also sits inside "tongres" and "progrès" - it flags the ordinary way, by
# not being on the list of plain words.
ALWAYS_NOTABLE = ("concreti", "konkreti", "zandsteen", "glauconi", "veen", "turf",
                  "tourbe", "lignit", "baksteen", "briqu", "beton", "asfalt", "puin", "houtskool",
                  "kolengruis", "koolas", "keramiek", "metaal", "glashoudend", "kassei",
                  "straatsteen", "geremanieerd", "remani", "talus", "slak", "sintel",
                  "caillou", "silex", "gravier")
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
FOSSILS = _folded("""
ammonites angulatus annelides annélides anoplo arca astarte belemnieten bivalve bivalves bryozoa
bryozoaires bryozoen buccinum cardita cardium cerithes cerithium charmassei concho coquiller
coquillière coquillières corbicula corbula corbules corbulla corneus crino crinoiden cymbula
cyprina cyprines cyrène cyrènes cythère cythérées dentalium dents ditrupa donax ecaille écaille
ecailles écailles echinodermen edita edule elegans foraminifera foraminiferen fossiel fossielen
fossielenen fossielfragmenten fossielhoudend fossielhoudende fossielrijk fossiles fossilifère
gastropoden gastropodes gebrokenschelpjes gibba glycimeris haaietand haaietanden helix hispida
huspida incrassata laevigatus lingula lucina macrofossielen mactra meerfossielhoudend moll
myabivalves mytilus natica nucula nucules nummulieten nummulites nummulitesplanulatus orbignyi
ossements ostrea pecten pectunculus petoncles phora pilosus planicosta planulata planulatus poisson
poissons porulosum roggetanden rustica schelpbrokjes schelpdelen schelpenbrokjes schelpenbrokken
schelpenfragmenten schelpenhoudend schelpenpuin schelpenresten schelpenrijke schelpensporen
schelpfragmentjes schelpresten schelprestjes schelpstukjes schlottheimia serpula striata
stukkenfossielen subtroncata tellina tenuissima terebratula turbinolia turbonilla turitella
turritella variolaria variolarius venericardia vijverschelpen vistanden weissenbachi wemmelensis
zoetwaterschelpjes
""")
# A denial in front of a word: "geen kalk" reports no kalk at all.
DENIALS = ("geen", "zonder", "sans", "vrij van")
# The same denial carried as a suffix: "zandsteenvrij", "kalkloos", "glauconietarm". Without this
# the material stem won over everything and the report claimed a sandstone the layer says is
# absent - the very error DENIALS exists to prevent, spelled the other way round.
DENYING_SUFFIXES = ("vrij", "loos", "arm")
# Colours, and everything built out of them. A colour says nothing about what a machine will meet,
# and the class is productive: lichtbruine, bruinzwarte, roestkleurige, geelgroen. Matched as a
# stem, so the inflections (-e, -en, -ig, -achtig) come along for free.
COLOUR_STEMS = ("bruin", "geel", "grijs", "grijze", "zwart", "groen", "rood", "rode", "blauw",
                "wit", "beige", "oranje", "paars", "roest", "oker", "creme", "kaki",
                "bleek", "donker", "licht", "kleurig", "kleurige", "gevlekt", "gespikkeld",
                "gemarmerd")
# The same class in French, where the colours are a closed set and the spellings are not: French
# INFLECTS (grise, grises, bruns, vertes) where Dutch compounds, and "-âtre" is French's
# "-achtig" - grisâtre is grijsachtig, verdâtre groenachtig. Both are ENDINGS, so they are taken
# off the word before the stem is looked up instead of being written out as thirty spellings.
#
# Two details the corpus settled. "-âtre" clips the stem it hangs on (vert -> verd, roux -> rouss,
# blanc -> blanch, jaune -> jaun), so those shortened forms stand beside the plain ones. And the
# lookup is an exact one on the stem, not the substring match the Dutch stems use: French words
# are short enough that "bleu" sits inside "sableuse" and "vert" inside "couvert", and a colour
# rule that swallowed those would be saying something untrue about why they are plain.
FRENCH_ENDINGS = ("atres", "atre", "es", "s", "e")
FRENCH_COLOUR_STEMS = frozenset("""
beige bistre blanc blanch bleu brun gris jaun jaune noir ocre roug rouge rouss roux verd vert
""".split())
# Plain stems a modifier may be built on. Deliberately NOT "steen": steenbrokken and silexkeien
# are exactly what a geotechnician wants to see.
ORDINARY_STEMS = ("zand", "klei", "leem", "silt", "grind", "kalk", "kwarts", "schelp",
                  "schelpen", "plant", "planten", "wortel", "wortels", "glimmer", "mica",
                  "humus", "zavel", "loess", "loss", "slib", "detritus",
                  "oxidatie", "verwering", "gley")
# Suffixes that turn a plain stem into a plain description: an admixture, not a material.
MODIFIER_SUFFIXES = ("houdend", "houdende", "rijk", "rijke", "achtig", "achtige", "ig", "ige",
                     "vlekken", "vlekjes", "brokjes", "brokken", "lenzen", "laagje", "laagjes", "gruis",
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


def _french_stems(word: str) -> Iterator[str]:
    """The word itself, and what is left of it when one French ending comes off.

    One ending, never two: the endings overlap ("grises" gives back both "grise" and "gris") and
    peeling further would start eating stems.

    Nothing shorter than four letters comes back. A three-letter stem is as likely to be a short
    Dutch word as a French base, and the corpus proved it: "löss" folds to "loss", which is "los"
    plus an -s, and "los" is on the list of plain words - so loess quietly stopped being a
    material. The cost of the floor is one word ("fins"), and that one is on the list by name.
    """
    yield word
    for ending in FRENCH_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) > MIN_LENGTH:
            yield word[:-len(ending)]


def _is_colour(word: str) -> bool:
    """A colour, or anything built out of one, in either language."""
    if any(stem in word for stem in COLOUR_STEMS):
        return True
    return any(stem in FRENCH_COLOUR_STEMS for stem in _french_stems(word))


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
    """Two plain stems stuck together: zandleem, kleizand, leemzand.

    Flemish borehole descriptions build texture names by gluing them, and the pair says nothing
    more than either half on its own. `ALWAYS_NOTABLE` comes first, so veenzand and zandsteen
    keep flagging.
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
    # Accent-free from here on: every list below is folded the same way, so "végétale" and
    # "vegetale" are one word and "grès" and "gres" are one word. See `_plain`.
    lowered = _plain(word.lower())
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
    # The plain word, or the plain word with one French ending on it. French inflects where Dutch
    # compounds - terre/terres, grossier/grossiers, ancienne/anciennes, altéré/altérée - and
    # listing both halves of every pair is the same losing game as listing both spellings of an
    # accent. The base has to be ordinary ALREADY, so this can only ever add an inflection to the
    # ordinary side and never turn a material into one: "graviers" is not "gravier" plus an
    # ending, because "gravier" is not a plain word, and neither is "dolomie" or "bancs".
    return len(lowered) < MIN_LENGTH or any(stem in ORDINARY
                                            for stem in _french_stems(lowered))


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
