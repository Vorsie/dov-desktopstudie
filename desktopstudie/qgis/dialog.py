"""The dialog: three tabs - Locatie, Instellingen, Rapport - and a Start button.

Built in code, no .ui file: one file format less, and the Qt5/Qt6 differences stay in one place.
The dialog is a form and nothing more. What it computes goes through `zone_input` (pure functions,
tested without a GUI) and what it starts goes through `StudyRunner`; the widgets only hold values.
It is non-modal, because two of the input modes are clicks on the canvas.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from qgis.core import Qgis, QgsApplication, QgsProject, QgsTask, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import catalogue
from ..core.geometry import Point
from ..core.logging_util import Log
from ..core.model import StudyZone
from ..core.report_content import ReportMeta
from ..core.services.geocoder import GeocodeHit, geocode
from ..core.services.http import CACHE_MODES, HttpClient
from ..core.study import Settings
from . import map_tools, zone_input
from .layers import CRS_AUTHID
from .settings import PluginSettings
from .task import PLUGIN_NAME, StudyRequest, StudyRunner, plugin_log

MODE_ADDRESS, MODE_POINT, MODE_RING, MODE_LAYER = range(4)
SECTION_AUTO, SECTION_DRAW, SECTION_LAYER = range(3)
SECTION_CHOICES = ("Automatisch (langste as van de zone)", "Tekenen op de kaart",
                   "Uit laag (eerste geselecteerde lijn)")
CACHE_LABELS = {"use": "Schijfcache gebruiken", "refresh": "Opnieuw ophalen (cache verversen)",
                "off": "Geen cache"}
CHAPTER_LABELS = {"ligging": "Ligging", "historisch": "Historisch", "geologie": "Geologie"}
LAMBERT_MAX_M = 400000.0
DEFAULT_BUFFER_M = 50.0
NO_HITS = "Geen kandidaat gevonden."
NOTHING_DRAWN = "Nog niets getekend."
# Wat een laag bijdraagt, in de woorden van de laag zelf: een vlaklaag heeft vlakken, een lijnlaag
# lijnen. Een enkel object heeft geen selectie nodig; pas bij meerdere is er iets te kiezen, en dan
# zegt de weigering hoeveel het er zijn en wat de gebruiker moet doen.
NOTE_ONLY_FEATURE = {
    "polygon": "Geen selectie; het enige vlak in de laag {layer} is gebruikt.",
    "line": "Geen selectie; de enige lijn in de laag {layer} is gebruikt.",
}
NO_CHOICE = {
    "polygon": ("De laag {layer} heeft {count} vlakken. Selecteer er een met het "
                "selectiegereedschap en start opnieuw."),
    "line": ("De laag {layer} heeft {count} lijnen. Selecteer er een met het "
             "selectiegereedschap en start opnieuw."),
}
NO_LAYER_CHOSEN = "Nog geen laag gekozen."
LAYER_STATE_SELECTED = {
    "polygon": "{count} vlakken, {selected} geselecteerd; het eerste geselecteerde wordt gebruikt.",
    "line": "{count} lijnen, {selected} geselecteerd; de eerste geselecteerde wordt gebruikt.",
}
LAYER_STATE_ONLY = {
    "polygon": "1 vlak, geen selectie; dat ene vlak wordt gebruikt.",
    "line": "1 lijn, geen selectie; die ene lijn wordt gebruikt.",
}
LAYER_STATE_CHOOSE = {
    "polygon": "{count} vlakken, geen selectie; selecteer er een met het selectiegereedschap.",
    "line": "{count} lijnen, geen selectie; selecteer er een met het selectiegereedschap.",
}
DRAW_RING_HINT = "Klik de hoekpunten op de kaart; rechtsklik sluit af."
DRAW_LINE_HINT = "Klik begin- en eindpunt op de kaart; rechtsklik sluit af."
LEGENDS_TIP = ("Elke kaart met een legenda krijgt een eigen legendapagina achter het kaartblad. Uit "
               "tenzij u ze aanvinkt: de klassen die in de zone liggen staan al onder hun eigen "
               "kaart. In de layout zelf schakelt de variabele 'legendas' die pagina's bij het "
               "exporteren.")
COMPACT_TIP = ("Zet zoveel korte tabellen en figuren op een blad als erop passen. Uit levert de "
               "voorspelbare opmaak: hoogstens twee stukken per blad, en kaartbladen blijven "
               "altijd alleen.")
CACHE_DIR_NAME = "cache"  # under the output folder, shared by every run written there
# A user is waiting at the address box: one try, and not the client's minute.
GEOCODE_TIMEOUT_S = 15.0


def _spin(low: float, high: float, value: float, decimals: int = 0, suffix: str = " m") -> QDoubleSpinBox:
    """A number box. Distances carry their unit; a coordinate does not, so X and Y ask for
    `suffix=""` - "104326 m" reads as a length where a Lambert 72 easting belongs."""
    spin = QDoubleSpinBox()
    spin.setRange(low, high)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setSuffix(suffix)
    return spin


def _count(value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 50)
    spin.setValue(value)
    return spin


class StudyDialog(QDialog):
    def __init__(self, iface, runner: StudyRunner, parent=None, log: Optional[Log] = None,
                 settings: Optional[PluginSettings] = None):
        super().__init__(parent)
        self.iface, self.runner = iface, runner
        self.log = log or plugin_log("dialoog")
        self.settings = settings if settings is not None else PluginSettings()
        self._hits: List[GeocodeHit] = []
        self._ring: Optional[List[Point]] = None  # drawn, already in Lambert 72
        self._section: Optional[Tuple[Point, Point]] = None
        # What the drawn ring and line ACTUALLY are, so switching modes can restore the truth
        # instead of leaving a complaint from an abandoned attempt standing (or wiping a result).
        self._ring_text = ""
        self._section_text = ""
        # What the run did on the user's behalf that he did not ask for by hand, collected while
        # the request is built and pushed to the message bar once it actually starts.
        self._notes: List[str] = []
        # The layers whose selection we are listening to, per hint label: reconnecting without
        # dropping the previous one leaves every layer ever chosen writing into the same label.
        self._watched: Dict[object, QgsVectorLayer] = {}
        self._tool = None
        self._previous_tool = None
        self._geocode_task = None  # kept: a QgsTask without a Python reference is collected mid-run
        self._geocode_token = None  # set while a search runs; only an answer carrying it counts
        self._geocode_query = ""
        self.setWindowTitle(PLUGIN_NAME)
        self.setMinimumWidth(560)
        tabs = QTabWidget()
        tabs.addTab(self._location_tab(), "Locatie")
        tabs.addTab(self._settings_tab(), "Instellingen")
        tabs.addTab(self._report_tab(), "Rapport")
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.start_button)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(buttons)
        self.runner.finished.connect(self._run_finished)
        self.start_button.setEnabled(not self.runner.running)
        # The layer lists follow the project: a layer added while the dialog is open is offered
        # without reopening it, a removed one disappears.
        QgsProject.instance().layersAdded.connect(self._refresh_layers)
        QgsProject.instance().layersRemoved.connect(self._refresh_layers)

    # --- the three tabs ---------------------------------------------------------------------------

    def _location_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.mode_address = QRadioButton("Adres")
        self.mode_address.setChecked(True)
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("Kortrijksesteenweg 100, Gent")
        self.address_edit.returnPressed.connect(self.search_address)
        self.search_button = QPushButton("Zoek")
        self.search_button.clicked.connect(self.search_address)
        self.hits_list = QListWidget()
        self.hits_list.setMaximumHeight(90)
        row = QHBoxLayout()
        row.addWidget(self.address_edit, 1)
        row.addWidget(self.search_button)
        layout.addWidget(self.mode_address)
        layout.addLayout(row)
        layout.addWidget(self.hits_list)

        self.mode_point = QRadioButton("X/Y in Lambert 72 (EPSG:31370)")
        self.x_spin = _spin(0.0, LAMBERT_MAX_M, 0.0, decimals=1, suffix="")
        self.y_spin = _spin(0.0, LAMBERT_MAX_M, 0.0, decimals=1, suffix="")
        row = QHBoxLayout()
        for label, spin in (("X", self.x_spin), ("Y", self.y_spin)):
            row.addWidget(QLabel(label))
            row.addWidget(spin, 1)
        layout.addWidget(self.mode_point)
        layout.addLayout(row)
        self.buffer_spin = _spin(1.0, 5000.0, DEFAULT_BUFFER_M)
        form = QFormLayout()
        form.addRow("Buffer rond het punt (adres of X/Y)", self.buffer_spin)
        layout.addLayout(form)

        self.mode_ring = QRadioButton("Polygoon tekenen op de kaart")
        self.draw_button = QPushButton("Tekenen")
        self.draw_button.clicked.connect(self.draw_ring)
        self.ring_label = QLabel(NOTHING_DRAWN)
        row = QHBoxLayout()
        row.addWidget(self.draw_button)
        row.addWidget(self.ring_label, 1)
        layout.addWidget(self.mode_ring)
        layout.addLayout(row)

        self.mode_layer = QRadioButton("Uit laag")
        self.layer_combo = QComboBox()
        self.layer_hint = QLabel(NO_LAYER_CHOSEN)
        layout.addWidget(self.mode_layer)
        layout.addWidget(self.layer_combo)
        layout.addWidget(self.layer_hint)
        layout.addStretch(1)
        self.layer_combo.currentIndexChanged.connect(self._zone_layer_changed)
        for button, _mode in ((self.mode_address, 0), (self.mode_point, 0), (self.mode_ring, 0),
                              (self.mode_layer, 0)):
            button.toggled.connect(self._zone_mode_changed)
        self._mode_buttons = ((self.mode_address, MODE_ADDRESS), (self.mode_point, MODE_POINT),
                              (self.mode_ring, MODE_RING), (self.mode_layer, MODE_LAYER))
        return tab

    def _settings_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        defaults = Settings()
        self.radius_spin = _spin(50.0, 5000.0, self.settings.radius_m)
        form.addRow("Zoekstraal", self.radius_spin)
        self.cpt_spin = _count(defaults.n_cpt_figures)
        self.borehole_spin = _count(defaults.n_borehole_figures)
        form.addRow("Sonderingen met figuur", self.cpt_spin)
        form.addRow("Boringen met figuur", self.borehole_spin)
        self.section_combo = QComboBox()
        self.section_combo.addItems(list(SECTION_CHOICES))
        self.section_combo.currentIndexChanged.connect(self._section_mode_changed)
        self.section_button = QPushButton("Tekenen")
        self.section_button.clicked.connect(self.draw_section)
        self.section_label = QLabel("")
        self.section_layer_combo = QComboBox()
        row = QHBoxLayout()
        row.addWidget(self.section_combo, 1)
        row.addWidget(self.section_button)
        form.addRow("Doorsnedelijn", row)
        form.addRow("", self.section_label)
        form.addRow("Lijnlaag", self.section_layer_combo)
        self.section_layer_hint = QLabel(NO_LAYER_CHOSEN)
        form.addRow("", self.section_layer_hint)
        self.section_layer_combo.currentIndexChanged.connect(self._section_layer_changed)
        self.extension_spin = _spin(0.0, 2000.0, defaults.section_extension_m)
        form.addRow("Verlenging doorsnedelijn", self.extension_spin)
        self.maps_list = QListWidget()
        self._fill_maps()
        form.addRow("Kaarten", self.maps_list)
        self.cache_combo = QComboBox()
        for mode in CACHE_MODES:
            self.cache_combo.addItem(CACHE_LABELS[mode], mode)
        self.cache_combo.setCurrentIndex(max(0, self.cache_combo.findData(self.settings.cache_mode)))
        form.addRow("Cache", self.cache_combo)
        self.legends_check = QCheckBox("Legenda's op aparte pagina's")
        self.legends_check.setChecked(self.settings.legends)
        self.legends_check.setToolTip(LEGENDS_TIP)
        form.addRow("", self.legends_check)
        self.compact_check = QCheckBox("Compacte opmaak (meer op een blad)")
        self.compact_check.setChecked(self.settings.compact)
        self.compact_check.setToolTip(COMPACT_TIP)
        form.addRow("", self.compact_check)
        self._section_mode_changed(SECTION_AUTO)
        return tab

    def _report_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.project_edit = QLineEdit(zone_input.DEFAULT_PROJECT_NAME)
        self.number_edit = QLineEdit()
        self.author_edit = QLineEdit(self.settings.author)
        self.company_edit = QLineEdit(self.settings.company)
        self.logo_edit = QLineEdit(self.settings.logo)
        self.output_edit = QLineEdit(self.settings.output_dir)
        form.addRow("Project", self.project_edit)
        form.addRow("Projectnummer", self.number_edit)
        form.addRow("Auteur", self.author_edit)
        form.addRow("Bedrijf", self.company_edit)
        form.addRow("Logo", self._browse_row(self.logo_edit, self._pick_logo))
        form.addRow("Uitvoermap", self._browse_row(self.output_edit, self._pick_output_dir))
        return tab

    def _browse_row(self, edit: QLineEdit, pick) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("...")
        button.clicked.connect(pick)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return row

    def _fill_maps(self) -> None:
        """Every catalogue entry, the disabled ones greyed and unchecked with their note as tooltip:
        the reader sees that the NGI series and the bommenkaart exist and why they are not here."""
        for entry in catalogue.entries(enabled_only=False):
            item = QListWidgetItem(f"{entry.title} ({CHAPTER_LABELS.get(entry.chapter, entry.chapter)})")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            if entry.enabled:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setToolTip(entry.note)
            self.maps_list.addItem(item)

    # --- reading the form -------------------------------------------------------------------------

    @property
    def hits(self) -> List[GeocodeHit]:
        """The geocoder's candidates, in the order the list shows them."""
        return list(self._hits)

    def mode(self) -> int:
        return next(mode for button, mode in self._mode_buttons if button.isChecked())

    def showEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        super().showEvent(event)
        self._refresh_layers()

    def _refresh_layers(self, *_layers) -> None:
        self._fill_layer_combo(self.layer_combo, Qgis.GeometryType.Polygon)
        self._fill_layer_combo(self.section_layer_combo, Qgis.GeometryType.Line)
        self._zone_layer_changed()
        self._section_layer_changed()

    @staticmethod
    def _fill_layer_combo(combo: QComboBox, geometry_type) -> None:
        current = combo.currentData()
        combo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.geometryType() == geometry_type:
                combo.addItem(layer.name(), layer.id())
        if current is not None:
            combo.setCurrentIndex(max(0, combo.findData(current)))

    def _zone_layer_changed(self, *_args) -> None:
        self._watch_layer(self.layer_combo, "polygon", self.layer_hint)

    def _section_layer_changed(self, *_args) -> None:
        self._watch_layer(self.section_layer_combo, "line", self.section_layer_hint)

    def _zone_mode_changed(self, *_args) -> None:
        """A hint belongs to its own mode.

        "een zone heeft minstens drie hoekpunten nodig (1 gegeven)" sat beside the Tekenen button
        while the user was already working in the layer mode - left over from an abandoned draw.
        """
        self.ring_label.setText(self._ring_text or NOTHING_DRAWN)
        self._layer_states()

    def _section_mode_changed(self, index: int) -> None:
        self.section_label.setText(self._section_text)
        self.section_button.setEnabled(index == SECTION_DRAW)
        self.section_layer_combo.setEnabled(index == SECTION_LAYER)
        # The extension belongs to the line the core lays itself; a drawn or chosen line is what it is.
        self.extension_spin.setEnabled(index == SECTION_AUTO)

    def zone(self) -> StudyZone:
        """The zone the form describes, or a ValueError that says what is still missing."""
        mode, radius, buffer = self.mode(), self.radius_spin.value(), self.buffer_spin.value()
        if mode == MODE_ADDRESS:
            row = self.hits_list.currentRow()
            if not self._hits or not 0 <= row < len(self._hits):
                raise ValueError("Zoek eerst een adres en kies een kandidaat uit de lijst.")
            return zone_input.zone_from_address_hit(self._hits[row], buffer, radius)
        if mode == MODE_POINT:
            x, y = self.x_spin.value(), self.y_spin.value()
            if x <= 0.0 or y <= 0.0:
                raise ValueError("Geef X en Y in Lambert 72 op.")
            return zone_input.zone_from_point(x, y, buffer, radius)
        if mode == MODE_RING:
            if not self._ring:
                raise ValueError("Teken eerst een polygoon op de kaart.")
            return zone_input.zone_from_ring(self._ring, CRS_AUTHID, radius)
        layer = self._chosen_layer(self.layer_combo)
        feature = self._chosen_feature(layer, "polygon")
        return zone_input.zone_from_feature(feature, layer.crs(), radius, name=f"{layer.name()} #{feature.id()}",
                                            context=self._transform_context())

    def section_line(self) -> Optional[Tuple[Point, Point]]:
        choice = self.section_combo.currentIndex()
        if choice == SECTION_AUTO:
            return None
        if choice == SECTION_DRAW:
            if self._section is None:
                raise ValueError("Teken eerst een doorsnedelijn op de kaart.")
            return self._section
        layer = self._chosen_layer(self.section_layer_combo)
        return zone_input.section_from_feature(self._chosen_feature(layer, "line"), layer.crs(),
                                               context=self._transform_context())

    @staticmethod
    def _transform_context():
        """The project's own datum transforms, so a drawn ring lands where the project would put it."""
        return QgsProject.instance().transformContext()

    @staticmethod
    def _chosen_layer(combo: QComboBox) -> QgsVectorLayer:
        layer = QgsProject.instance().mapLayer(combo.currentData() or "")
        if layer is None:
            raise ValueError("Kies een laag in het project.")
        return layer

    def _chosen_feature(self, layer: QgsVectorLayer, kind: str):
        """The feature this layer contributes: the selection, or the only one it holds.

        Drawing your site boundary into a scratch layer and pointing the plugin at it is the
        natural way to work, and demanding a separate selection step on a layer that holds exactly
        one feature is pedantry - "een vlak in de laag, dan is dat het vlak". It never happens
        silently: the note goes to the message bar after the run starts, so the reader knows which
        feature was taken. Only with several features and no selection is there a real question,
        and then the refusal says how many there are and what to do about it.
        """
        selected = layer.selectedFeatures()
        if selected:
            return selected[0]
        count = layer.featureCount()
        if count == 1:
            self._notes.append(NOTE_ONLY_FEATURE[kind].format(layer=layer.name()))
            return next(layer.getFeatures())
        raise ValueError(NO_CHOICE[kind].format(layer=layer.name(), count=count))

    def _layer_state(self, combo: QComboBox, kind: str) -> str:
        """What the chosen layer would contribute right now, for the line beside the combo."""
        layer = QgsProject.instance().mapLayer(combo.currentData() or "")
        if layer is None:
            return NO_LAYER_CHOSEN
        count, selected = layer.featureCount(), layer.selectedFeatureCount()
        if selected:
            return LAYER_STATE_SELECTED[kind].format(count=count, selected=selected)
        if count == 1:
            return LAYER_STATE_ONLY[kind]
        return LAYER_STATE_CHOOSE[kind].format(count=count)

    def _watch_layer(self, combo: QComboBox, kind: str, label: QLabel) -> None:
        """Keep that line true while the dialog stands open.

        The dialog is not modal: the user selects on the canvas and presses Start without touching
        it, so the line has to follow the layer's own `selectionChanged` rather than only the combo.
        The previous layer's signal is dropped first, otherwise every layer ever chosen keeps
        writing into the same label.
        """
        previous = self._watched.pop(label.objectName() or id(label), None)
        if previous is not None:
            try:
                previous.selectionChanged.disconnect(self._layer_states)
            except (TypeError, RuntimeError):  # already gone, or the layer was deleted
                pass
        layer = QgsProject.instance().mapLayer(combo.currentData() or "")
        if layer is not None:
            layer.selectionChanged.connect(self._layer_states)
            self._watched[label.objectName() or id(label)] = layer
        label.setText(self._layer_state(combo, kind))

    def _layer_states(self, *_args) -> None:
        """Both state lines, re-read from the project."""
        self.layer_hint.setText(self._layer_state(self.layer_combo, "polygon"))
        self.section_layer_hint.setText(self._layer_state(self.section_layer_combo, "line"))

    def map_ids(self) -> Optional[List[str]]:
        """None when every enabled map is checked - the core's default - else the checked ids."""
        checked = [self.maps_list.item(i).data(Qt.ItemDataRole.UserRole)
                   for i in range(self.maps_list.count())
                   if self.maps_list.item(i).checkState() == Qt.CheckState.Checked]
        return None if checked == [entry.id for entry in catalogue.entries()] else checked

    def build_request(self) -> StudyRequest:
        self._notes = []  # filled by `_chosen_feature`; `start` pushes them once the run is under way
        zone = self.zone()
        zone.section_line = self.section_line()
        settings = Settings(radius_m=self.radius_spin.value(), n_cpt_figures=self.cpt_spin.value(),
                            n_borehole_figures=self.borehole_spin.value(),
                            section_extension_m=self.extension_spin.value(), map_ids=self.map_ids(),
                            compact=self.compact_check.isChecked())
        meta = ReportMeta(project=self.project_edit.text().strip() or zone_input.DEFAULT_PROJECT_NAME,
                          author=self.author_edit.text().strip(), company=self.company_edit.text().strip(),
                          project_number=self.number_edit.text().strip(),
                          logo_path=self.logo_edit.text().strip())
        if meta.logo_path and not Path(meta.logo_path).is_file():
            raise ValueError(f"Logo niet gevonden: {meta.logo_path}")
        base = self.output_edit.text().strip()
        if not base:
            raise ValueError("Geef een uitvoermap op.")
        return StudyRequest(zone, settings, meta, zone_input.run_folder(Path(base), meta.project),
                            self.cache_combo.currentData(), self.legends_check.isChecked(),
                            cache_dir=Path(base) / CACHE_DIR_NAME)

    def save_settings(self) -> None:
        settings = self.settings
        settings.company = self.company_edit.text().strip()
        settings.author = self.author_edit.text().strip()
        settings.logo = self.logo_edit.text().strip()
        settings.radius_m = self.radius_spin.value()
        settings.output_dir = self.output_edit.text().strip()
        settings.cache_mode = self.cache_combo.currentData()
        settings.legends = self.legends_check.isChecked()
        settings.compact = self.compact_check.isChecked()
        settings.sync()

    # --- the address -------------------------------------------------------------------------------

    def search_address(self) -> None:
        """Geocode on a task of its own: a geopunt call takes a second, and a second of frozen
        dialog is one too many. One search at a time: a second Enter while one runs is ignored,
        and an answer to an older search is dropped - otherwise the row the user clicks maps to a
        different address than the one it shows."""
        query = self.address_edit.text().strip()
        if not query:
            self._warn("Geef een adres op.")
            return
        if self._geocode_token is not None:
            self.log.info(f"adres zoeken loopt al ({self._geocode_query!r}); nieuwe zoekopdracht genegeerd")
            return
        self.hits_list.clear()
        self._hits = []
        self.search_button.setEnabled(False)
        token = object()
        self._geocode_token, self._geocode_query = token, query
        self.log.info(f"adres zoeken: {query!r}")
        self._geocode_task = self._start_geocode(query, token)

    def _start_geocode(self, query: str, token: object):
        """The geocoder on a QgsTask; the answer comes back through `_address_found` with `token`."""
        client = HttpClient(cache_dir=None, timeout=GEOCODE_TIMEOUT_S, retries=0, log=self.log.child("http"))
        log = self.log.child("geocoder")
        task = QgsTask.fromFunction(
            "Adres zoeken", lambda task: geocode(client, query, log=log),
            on_finished=lambda exception, hits=None: self._address_found(token, exception, hits))
        QgsApplication.taskManager().addTask(task)
        return task

    def _address_found(self, token, exception, hits=None) -> None:
        """`QgsTask.fromFunction` hands the result only when it is truthy, hence the default."""
        if token is not self._geocode_token:
            self.log.debug("verouderd antwoord van de geocoder genegeerd")
            return
        self._geocode_token, self._geocode_task = None, None
        self.search_button.setEnabled(True)
        if exception is not None:
            self._warn(f"Adres zoeken mislukt: {exception}")
            return
        self._hits = list(hits or [])
        self.log.info(f"adres {self._geocode_query!r}: {len(self._hits)} kandidaten")
        for hit in self._hits:
            self.hits_list.addItem(hit.address if hit.is_precise else f"{hit.address} (niet op huisnummer)")
        if self._hits:
            self.hits_list.setCurrentRow(0)
            self.mode_address.setChecked(True)
        else:
            self.hits_list.addItem(NO_HITS)

    # --- drawing on the canvas ---------------------------------------------------------------------

    def draw_ring(self) -> None:
        self._start_tool(map_tools.polygon_tool, self._ring_drawn, self.ring_label, DRAW_RING_HINT)

    def draw_section(self) -> None:
        self._start_tool(map_tools.line_tool, self._section_drawn, self.section_label, DRAW_LINE_HINT)

    def _start_tool(self, factory, on_done, label: QLabel, hint: str) -> None:
        canvas = self.iface.mapCanvas()
        self._stop_tool()
        self._previous_tool = canvas.mapTool()
        self._tool = factory(canvas, on_done)
        canvas.setMapTool(self._tool)
        label.setText(hint)

    def _stop_tool(self) -> None:
        if self._tool is None:
            return
        canvas = self.iface.mapCanvas()
        canvas.unsetMapTool(self._tool)
        if self._previous_tool is not None:
            canvas.setMapTool(self._previous_tool)
        self._tool.deleteLater()  # the canvas does not own it; Python would drop it whenever
        self._tool, self._previous_tool = None, None

    def _canvas_crs(self):
        return self.iface.mapCanvas().mapSettings().destinationCrs()

    def _ring_drawn(self, points: List[Point]) -> None:
        self._stop_tool()
        try:
            zone = zone_input.zone_from_ring(points, self._canvas_crs(), self.radius_spin.value(),
                                             context=self._transform_context())
        except ValueError as exc:
            self._ring, self._ring_text = None, ""
            self.ring_label.setText(str(exc))
            return
        self._ring = zone.ring
        self._ring_text = f"Polygoon met {len(zone.ring)} hoekpunten, {zone.area_m2:.0f} m²."
        self.ring_label.setText(self._ring_text)
        self.mode_ring.setChecked(True)

    def _section_drawn(self, points: List[Point]) -> None:
        self._stop_tool()
        try:
            self._section = zone_input.section_from_points(points, self._canvas_crs(),
                                                           context=self._transform_context())
        except ValueError as exc:
            self._section, self._section_text = None, ""
            self.section_label.setText(str(exc))
            return
        (ax, ay), (bx, by) = self._section
        self._section_text = f"Lijn van {ax:.0f}/{ay:.0f} naar {bx:.0f}/{by:.0f}."
        self.section_label.setText(self._section_text)

    # --- files -------------------------------------------------------------------------------------

    def _pick_logo(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Logo", self.logo_edit.text(),
                                                    "Afbeeldingen (*.png *.jpg *.jpeg *.svg);;Alle bestanden (*)")
        if path:
            self.logo_edit.setText(path)

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Uitvoermap", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    # --- start -------------------------------------------------------------------------------------

    def start(self) -> None:
        if self.runner.running:
            self._warn("Er loopt al een studie; wacht tot ze klaar is of breek ze af.")
            return
        try:
            request = self.build_request()
        except (ValueError, RuntimeError) as exc:  # RuntimeError: a layer deleted under the combo
            self._warn(str(exc))
            return
        self.save_settings()
        for note in self._notes:
            self._inform(note)
        self.start_button.setEnabled(False)
        try:
            self.runner.start(request)
        except Exception as exc:  # noqa: BLE001 - said to the user, never swallowed
            self.start_button.setEnabled(True)
            self.log.error(f"studie kon niet starten: {type(exc).__name__}: {exc}")
            self._warn(f"Studie kon niet starten: {exc}")

    def _run_finished(self, _result) -> None:
        self.start_button.setEnabled(True)

    def _warn(self, text: str) -> None:
        self.log.warning(text)
        self.iface.messageBar().pushWarning(PLUGIN_NAME, text)

    def _inform(self, text: str) -> None:
        """Something the study did on the user's behalf that he did not ask for by hand."""
        self.log.info(text)
        self.iface.messageBar().pushInfo(PLUGIN_NAME, text)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        """Close is not goodbye: the plugin keeps this dialog and shows it again. So a search that
        is still running is forgotten here - its answer would otherwise fill the list of a dialog
        the user had closed - and the Zoek button is handed back, because `_address_found` drops
        the answer on the token and would never re-enable it."""
        self._stop_tool()
        if self._geocode_token is not None:
            self.log.info(f"adres zoeken losgelaten bij het sluiten ({self._geocode_query!r})")
            self._geocode_token, self._geocode_task = None, None
            self.search_button.setEnabled(True)
        super().closeEvent(event)
