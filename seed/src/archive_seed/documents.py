"""The documents of the fictional fleet: original Swedish texts, written for this archive.

Each is rendered as a typed scan (see render.py), so the text on the page is known exactly and a machine
reading can be measured against it. No person is named, as the archive models none (ADR 0002): letters are
between firms and say "befälhavaren" for the master.
"""

from dataclasses import dataclass

from archive_seed.fleet import Period


@dataclass(frozen=True)
class DocumentSeed:
    key: str
    title: str
    kind: str
    date: Period
    pages: tuple[str, ...]
    font: str  # serif or mono
    quality: str  # clean, faded, skewed or speckled
    format: str  # png, jpeg or tiff
    state: str  # verified, partial (the first page only) or machine
    ships: tuple[str, ...] = ()
    organisations: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)


DOCUMENTS = (
    DocumentSeed(
        key="doc-kontrakt-1889",
        title="Byggnadskontrakt för barken Nordstjärnan",
        kind="contract",
        date=Period("14 januari 1889", "1889-01-14", "1889-01-14"),
        pages=(
            "BYGGNADSKONTRAKT\n"
            "Mellan Älvsborgs Skeppsvarv i Göteborg och Rederi AB Nordsjö har denna dag överenskommits "
            "om byggande av en bark av järn, omkring 920 registerton, till en köpesumma av 212 000 kronor. "
            "Fartyget skall vara färdigt för leverans den 1 maj 1889. Betalning sker i fyra rater: vid "
            "kontraktets undertecknande, vid kölsträckning, vid sjösättning samt vid leverans. Varvet "
            "svarar för material och arbete. Redaren utser besiktningsman vid kölsträckningen. "
            "Göteborg den 14 januari 1889.",
        ),
        font="serif", quality="clean", format="png", state="verified",
        ships=("ship-nordstjarnan",), organisations=("org-alvsborg", "org-nordsjo"),
    ),
    DocumentSeed(
        key="doc-kvitto-1889",
        title="Kvitto på andra betalningen för Nordstjärnan",
        kind="receipt",
        date=Period("2 april 1889", "1889-04-02", "1889-04-02"),
        pages=(
            "KVITTO nr 417\n"
            "Härmed intygas att Rederi AB Nordsjö denna dag erlagt 53 000 kronor, avseende andra "
            "ratan för barken Nordstjärnan. Beloppet är mottaget kontant. Göteborg den 2 april 1889. "
            "Älvsborgs Skeppsvarv, kassan.",
        ),
        font="mono", quality="faded", format="jpeg", state="machine",
        ships=("ship-nordstjarnan",), organisations=("org-alvsborg", "org-nordsjo"),
    ),
    DocumentSeed(
        key="doc-leverans-1889",
        title="Brev om leverans av Nordstjärnan",
        kind="letter",
        date=Period("2 maj 1889", "1889-05-02", "1889-05-02"),
        pages=(
            "Göteborg den 2 maj 1889\n"
            "Till Rederi AB Nordsjö.\n"
            "Barken Nordstjärnan överlämnades i går vid Klippans kaj efter en lyckad provtur utanför "
            "Vinga. Fartyget gick som bäst 9,5 knop i frisk bris och lydde rodret väl. Rigg och "
            "tackling är nytt och fullständigt enligt kontraktet. Vi önskar fartyget en god lycka på "
            "kommande resor. Med utmärkt högaktning, Älvsborgs Skeppsvarv.",
        ),
        font="serif", quality="skewed", format="png", state="verified",
        ships=("ship-nordstjarnan",), organisations=("org-alvsborg", "org-nordsjo"),
    ),
    DocumentSeed(
        key="doc-matbrev-1889",
        title="Mätbrev för barken Nordstjärnan",
        kind="certificate",
        date=Period("maj 1889", "1889-05-01", "1889-05-31"),
        pages=(
            "MÄTBREV\n"
            "för barken Nordstjärnan av Göteborg. Längd 62,4 meter, bredd 10,8 meter, djupgående "
            "5,6 meter. Nettodräktighet 871 registerton, bruttodräktighet 1 024 registerton. "
            "Byggd av järn vid Älvsborgs Skeppsvarv år 1889. Hemort Göteborg.",
        ),
        font="mono", quality="speckled", format="tiff", state="machine",
        ships=("ship-nordstjarnan",), organisations=("org-alvsborg",),
    ),
    DocumentSeed(
        key="doc-linnea-order-1900",
        title="Brev om beställning av skonaren Linnea",
        kind="letter",
        date=Period("3 november 1900", "1900-11-03", "1900-11-03"),
        pages=(
            "Göteborg den 3 november 1900\n"
            "Till Älvsborgs Skeppsvarv.\n"
            "Vi beställer härmed en skonare av trä om omkring 140 registerton, avsedd för kusttrafik "
            "mellan Göteborg och Västerhavets hamnar. Fartyget skall få namnet Linnea. Vi önskar "
            "leverans före midsommar nästa år och ber om offert samt ritning snarast. "
            "Rederi AB Nordsjö.",
        ),
        font="mono", quality="clean", format="png", state="verified",
        ships=("ship-linnea",), organisations=("org-alvsborg", "org-nordsjo"),
    ),
    DocumentSeed(
        key="doc-linnea-faktura-1901",
        title="Faktura för skonaren Linnea",
        kind="invoice",
        date=Period("1 augusti 1901", "1901-08-01", "1901-08-01"),
        pages=(
            "FAKTURA nr 88\n"
            "Skonaren Linnea, byggd av ek och furu, levererad i dag. Pris enligt offert 38 500 kronor. "
            "Därutöver tillkommer segel och tackling för 4 200 kronor samt ankare och kätting för "
            "1 350 kronor. Summa att betala 44 050 kronor, förfallodag den 1 september 1901.",
        ),
        font="serif", quality="faded", format="jpeg", state="machine",
        ships=("ship-linnea",), organisations=("org-alvsborg", "org-nordsjo"),
    ),
    DocumentSeed(
        key="doc-kopebrev-1903",
        title="Köpebrev för barken Nordstjärnan",
        kind="contract",
        date=Period("15 april 1903", "1903-04-15", "1903-04-15"),
        pages=(
            "KÖPEBREV\n"
            "Rederi AB Nordsjö säljer härmed barken Nordstjärnan av Göteborg, med allt tillbehör "
            "som finnes ombord, till Rederi AB Sund i Stockholm för en köpesumma av 118 000 kronor. "
            "Fartyget övertas i det skick det befinner sig i Göteborgs hamn och är fritt från "
            "inteckning. Äganderätten övergår denna dag. Göteborg den 15 april 1903.",
        ),
        font="serif", quality="clean", format="jpeg", state="verified",
        ships=("ship-nordstjarnan",), organisations=("org-nordsjo", "org-sund"),
    ),
    DocumentSeed(
        key="doc-namnbyte-1903",
        title="Anmälan om namnbyte till Sofia",
        kind="letter",
        date=Period("20 maj 1903", "1903-05-20", "1903-05-20"),
        pages=(
            "Stockholm den 20 maj 1903\n"
            "Rederi AB Sund anmäler att barken Nordstjärnan av Göteborg, som övertogs den 15 april "
            "detta år, från och med samma dag skall föra namnet Sofia. Fartygets hemort är oförändrad. "
            "Vi ber att namnbytet måtte antecknas i registret.",
        ),
        font="mono", quality="faded", format="png", state="machine",
        ships=("ship-nordstjarnan",), organisations=("org-sund",),
    ),
    DocumentSeed(
        key="doc-svalan-telegram-1912",
        title="Telegram om ångaren Svalan",
        kind="telegram",
        date=Period("ca 1912", "1912-01-01", "1912-12-31"),
        pages=(
            "TELEGRAM\n"
            "ÅNGAREN SVALAN FÖRSENAD TILL FÖLJD AV DIMMA I SUNDET. BERÄKNAS ANLÖPA STOCKHOLM "
            "ONSDAG KVÄLL. LASTEN OSKADAD. VÄNTAR BESKED OM KAJPLATS. REDERI AB SUND.",
        ),
        font="mono", quality="skewed", format="png", state="machine",
        ships=("ship-svalan",), organisations=("org-sund",),
    ),
    DocumentSeed(
        key="doc-inventarium-1912",
        title="Inventarium för barken Sofia",
        kind="inventory",
        date=Period("ca 1912", "1911-01-01", "1913-12-31"),
        pages=(
            "INVENTARIUM, FÖRSTA BLADET\n"
            "Barken Sofia. Segel: fem råsegel av bomullsduk, två stagsegel, ett gaffelsegel samt "
            "reservsegel i förrådet. Rigg: fyra vantar på var sida av grovt hampgarn, tre ankartåg och "
            "två trossar om sextio famnar. Allt i brukbart skick utom det främre märssegelet, som "
            "behöver lagas.",
            "INVENTARIUM, ANDRA BLADET\n"
            "Ankare: två bogankare och ett varpankare. Båtar: en livbåt och en jolle, båda målade och "
            "tätade i höstas. Kompass: två, varav en reserv. Lanternor: sex stycken med nya glas. "
            "Övrigt: ett lod med lina, en logg samt sjökort över Östersjön och Bottenhavet.",
        ),
        font="serif", quality="speckled", format="png", state="partial",
        ships=("ship-nordstjarnan",), organisations=("org-sund",),
    ),
    DocumentSeed(
        key="doc-dagbok-1915",
        title="Dagboksblad från barken Sofia",
        kind="logbook page",
        date=Period("3 mars 1915", "1915-03-03", "1915-03-03"),
        pages=(
            "DAGBOK, den 3 mars 1915\n"
            "Vind sydväst, styv bris, sjögång måttlig. Från morgonen gick fartyget för reducerad "
            "segelföring, och vid middagstid revades märsseglen. Ingen skada på rigg eller last. "
            "Klockan sex på kvällen siktades fyren på Utklippan på ett avstånd av tre sjömil. "
            "Kursen hölls öster om fyren under natten.",
        ),
        font="mono", quality="faded", format="jpeg", state="machine",
        ships=("ship-nordstjarnan",), organisations=("org-sund",),
    ),
    DocumentSeed(
        key="doc-havsornen-1921",
        title="Anmälan om namnbyte till Havsörnen",
        kind="certificate",
        date=Period("8 mars 1921", "1921-03-08", "1921-03-08"),
        pages=(
            "ANMÄLAN OM NAMNBYTE\n"
            "Fartyget, som tidigare hetat Nordstjärnan och därefter Sofia, skall från och med den "
            "1 mars 1921 föra namnet Havsörnen. Fartyget är en bark av järn, byggd i Göteborg år 1889, "
            "med hemort Göteborg. Registret har ändrats i enlighet med detta. Stockholm den 8 mars 1921.",
        ),
        font="serif", quality="clean", format="tiff", state="verified",
        ships=("ship-nordstjarnan",), organisations=("org-sund",),
    ),
    DocumentSeed(
        key="doc-ombyggnad-1933",
        title="Överenskommelse om ombyggnad av skrovet efter Havsörnen",
        kind="contract",
        date=Period("5 september 1933", "1933-09-05", "1933-09-05"),
        pages=(
            "ÖVERENSKOMMELSE OM OMBYGGNAD\n"
            "Älvsborgs Skeppsvarv åtar sig att bygga om skrovet efter barken Havsörnen till ett "
            "motorfartyg om omkring 640 registerton. Rigg och master tas bort, nytt maskineri och "
            "ny däcksinredning byggs in. Det ombyggda fartyget skall betraktas som ett nytt fartyg "
            "och få namnet Älvdrottningen. Överenskommet i Göteborg den 5 september 1933.",
        ),
        font="serif", quality="clean", format="png", state="verified",
        ships=("ship-nordstjarnan", "ship-alvdrottningen"), organisations=("org-alvsborg", "org-nordsjo"),
    ),
)
