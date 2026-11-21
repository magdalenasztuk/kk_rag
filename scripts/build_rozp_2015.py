"""Buduje data/legal_json/rozp_2015_pierwsza_ocena.json z PDF Dziennika Ustaw (Dz.U. 2015 poz. 1144).

Usage: python -m scripts.build_rozp_2015 "<ścieżka do PDF rozporządzenia z 2015 r.>"
Część normatywna (§ 1–14) jest parsowana z PDF; załączniki są przepisane z tego samego PDF ręcznie.
"""
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

OUT = Path(__file__).resolve().parents[1] / "data" / "legal_json" / "rozp_2015_pierwsza_ocena.json"

# Paragrafy bez ustępów, których punkty indeksujemy osobno (cytowania typu „§ 3 pkt 4”).
SPLIT_PKT_PARAGRAPHS = {"2", "3", "7"}
# Ustępy, których punkty indeksujemy osobno (warunki pozytywnej oceny, zwolnienia z egzaminu).
SPLIT_PKT_UST = {("10", "1"), ("10", "3")}

ANNEX_UNITS = [
    {"citation": "zał. nr 1 – Opisy elementów oceny", "chunk_type": "section", "page": 4,
     "text": "Załącznik nr 1 – Opisy elementów pierwszej oceny: 1. Rzetelność; 2. Wykorzystywanie wiedzy i doskonalenie "
             "zawodowe; 3. Organizacja pracy i orientacja na osiąganie celów; 4. Komunikacja; 5. Współpraca."},
    {"citation": "zał. nr 1 pkt 1 – Rzetelność", "parent": "zał. nr 1 – Opisy elementów oceny", "page": 4,
     "text": "Element oceny RZETELNOŚĆ: wykonywanie zadań zgodnie z obowiązującymi standardami (przepisami, zasadami, "
             "procedurami) oraz dbałość o jakość rezultatów; dotrzymywanie zobowiązań (realizacja zadań) w wyznaczonym czasie."},
    {"citation": "zał. nr 1 pkt 2 – Wykorzystywanie wiedzy i doskonalenie zawodowe", "parent": "zał. nr 1 – Opisy elementów oceny", "page": 4,
     "text": "Element oceny WYKORZYSTYWANIE WIEDZY I DOSKONALENIE ZAWODOWE: wykorzystywanie wiedzy przy realizacji zadań na "
             "zajmowanym stanowisku pracy; doskonalenie wiedzy i umiejętności niezbędnych do wykonywania zadań na zajmowanym "
             "stanowisku pracy, w szczególności wyszukiwanie i pozyskiwanie wiedzy, korzystanie z dobrych praktyk i doświadczeń "
             "innych; korzystanie z dostępnych źródeł informacji, rozwiązań i technologii."},
    {"citation": "zał. nr 1 pkt 3 – Organizacja pracy i orientacja na osiąganie celów", "parent": "zał. nr 1 – Opisy elementów oceny", "page": 4,
     "text": "Element oceny ORGANIZACJA PRACY I ORIENTACJA NA OSIĄGANIE CELÓW: określanie sposobu realizacji zadań/celów; "
             "realizowanie zadań/celów w kolejności uwzględniającej ich wagę i pilność (ustalanie priorytetów działania); "
             "dobieranie niezbędnych zasobów umożliwiających realizację zadań/celów; dostosowywanie się do zmieniających się "
             "okoliczności; wytrwałość i zaangażowanie w realizację zadań/celów."},
    {"citation": "zał. nr 1 pkt 4 – Komunikacja", "parent": "zał. nr 1 – Opisy elementów oceny", "page": 4,
     "text": "Element oceny KOMUNIKACJA: koncentrowanie się na wypowiedzi rozmówcy i dbanie o wzajemne zrozumienie; "
             "wypowiadanie się w sposób jasny i precyzyjny, dostosowany do sytuacji i rozmówcy (dobieranie stylu, języka i treści); "
             "formułowanie jasnych i precyzyjnych wypowiedzi pisemnych dostosowanych do sytuacji i odbiorcy; przedstawianie "
             "przekonujących argumentów odpowiednio do sytuacji."},
    {"citation": "zał. nr 1 pkt 5 – Współpraca", "parent": "zał. nr 1 – Opisy elementów oceny", "page": 4,
     "text": "Element oceny WSPÓŁPRACA: włączanie się w działania realizowane razem z innymi osobami, jeśli istnieje taka "
             "możliwość; dbanie o przepływ informacji; dbanie o dobrą atmosferę i otwartość we współpracy; dostrzeganie wkładu "
             "pracy innych osób; branie pod uwagę zdania innych osób; dzielenie się wiedzą i doświadczeniem."},
    {"citation": "zał. nr 2 – Arkusz pierwszej oceny, części I–II", "chunk_type": "section", "page": 5,
     "text": "Arkusz pierwszej oceny w służbie cywilnej (załącznik nr 2). Część I – część ogólna: nazwa urzędu, dane ocenianego "
             "(w tym data nawiązania stosunku pracy), dane bezpośredniego przełożonego i kierującego komórką organizacyjną. "
             "Część II – rozmowa wstępna: data przeprowadzenia rozmowy wstępnej, termin wyznaczony na złożenie sprawozdania "
             "(od–do), okres, w którym powinna zostać dokonana pierwsza ocena (od–do); podpisy bezpośredniego przełożonego "
             "i ocenianego potwierdzające rozmowę wstępną i zapoznanie z terminem sprawozdania."},
    {"citation": "zał. nr 2 – Arkusz pierwszej oceny, części III–IV", "chunk_type": "section", "page": 6,
     "text": "Arkusz pierwszej oceny, część III – rozmowa oceniająca: data rozmowy i podpisy potwierdzające omówienie wszystkich "
             "wymaganych zagadnień. Część IV – ocena postawy ocenianego, jego zaangażowania i postępów w pracy, relacji ze "
             "współpracownikami oraz terminowości wykonywania zadań: oceny cząstkowe pięciu elementów (rzetelność; "
             "wykorzystywanie wiedzy i doskonalenie zawodowe; organizacja pracy i orientacja na osiąganie celów; komunikacja; "
             "współpraca) w skali 3 punkty – poniżej oczekiwań, 5 punktów – na poziomie oczekiwań, 7 punktów – powyżej "
             "oczekiwań, oraz ocena łączna, będąca średnią arytmetyczną ze wszystkich ocen cząstkowych."},
    {"citation": "zał. nr 2 – Arkusz pierwszej oceny, część V", "chunk_type": "section", "page": 6,
     "text": "Arkusz pierwszej oceny, część V – pierwsza ocena w służbie cywilnej: czy oceniany zaliczył egzamin ze służby "
             "przygotowawczej (tak / nie / nie dotyczy), czy sprawozdanie zostało złożone w wyznaczonym terminie (tak / nie), "
             "pierwsza ocena pozytywna albo negatywna, uzasadnienie przyznanej oceny."},
    {"citation": "zał. nr 2 – Arkusz pierwszej oceny, przypis 2: zakres rozmowy oceniającej", "parent": "zał. nr 2 – Arkusz pierwszej oceny, części III–IV",
     "chunk_type": "przypis", "page": 6,
     "text": "Przypis do arkusza pierwszej oceny: w trakcie rozmowy oceniającej omawiane są postawa ocenianego, jego "
             "zaangażowanie i postępy w pracy, relacje ze współpracownikami oraz terminowość wykonywania zadań, oceniane za "
             "pomocą elementów oceny, wynik egzaminu ze służby przygotowawczej, jeżeli oceniany był obowiązany do przystąpienia "
             "do tego egzaminu, oraz sprawozdanie sporządzone przez ocenianego. Można również omówić kierunki dalszego rozwoju "
             "zawodowego i potrzeby ocenianego."},
    {"citation": "zał. nr 2 – Arkusz pierwszej oceny, przypis 6: warunki oceny pozytywnej", "parent": "zał. nr 2 – Arkusz pierwszej oceny, część V",
     "chunk_type": "przypis", "page": 6,
     "text": "Przypis do arkusza pierwszej oceny: pozytywną pierwszą ocenę należy przyznać ocenianemu, który łącznie spełnił "
             "warunki: zaliczył egzamin ze służby przygotowawczej, chyba że nie dotyczył go obowiązek przystąpienia do tego "
             "egzaminu; złożył sprawozdanie w wyznaczonym terminie; uzyskał nie więcej niż jedną ocenę cząstkową w wysokości "
             "3 punktów; uzyskał ocenę łączną nie niższą niż 5 punktów."},
    {"citation": "zał. nr 2 – Arkusz pierwszej oceny, przypis 7: uzasadnienie oceny", "parent": "zał. nr 2 – Arkusz pierwszej oceny, część V",
     "chunk_type": "przypis", "page": 7,
     "text": "Przypis do arkusza pierwszej oceny: w przypadku przyznania negatywnej pierwszej oceny uzasadnienie przyznanej "
             "oceny jest obowiązkowe, a w przypadku przyznania pozytywnej pierwszej oceny – fakultatywne. Uzasadnienie może "
             "polegać na ogólnym omówieniu oceny lub na szczegółowym odniesieniu się do wszystkich ocen cząstkowych albo tylko "
             "do niektórych z nich."},
    {"citation": "zał. nr 2 – Arkusz pierwszej oceny, część VI i przypis 8: wnioski rozwojowe", "chunk_type": "section", "page": 7,
     "text": "Arkusz pierwszej oceny, część VI – wnioski dotyczące rozwoju zawodowego ocenianego. Wnioski sporządza się "
             "fakultatywnie – tylko w przypadku przyznania pozytywnej pierwszej oceny. Określa się m.in. zakres wiedzy, która "
             "powinna być poszerzona, zakres umiejętności, które wymagają doskonalenia, oraz proponowane formy rozwoju "
             "zawodowego ocenianego. Arkusz zawiera potwierdzenie dokonania pierwszej oceny podpisami bezpośredniego "
             "przełożonego i kierującego komórką organizacyjną oraz oświadczenie ocenianego o zapoznaniu się z pierwszą oceną."},
    {"citation": "zał. nr 3 – Formularz sprawozdania", "chunk_type": "section", "page": 8,
     "text": "Formularz sprawozdania dotyczącego zadań realizowanych przez ocenianego w trakcie przepracowanego okresu "
             "(załącznik nr 3): dane ocenianego, termin wyznaczony na złożenie sprawozdania (od–do). Należy opisać zadania "
             "z opisu stanowiska pracy i ewentualnie inne istotne zadania wykonywane w trakcie przepracowanego okresu, "
             "problemy napotkane przy wykonywaniu zadań i sposób ich rozwiązania, zdobyte nowe umiejętności i wiedzę oraz "
             "wnioski dotyczące usprawnienia sposobu wykonywania zadań."},
]


def _clean(text: str) -> str:
    text = re.sub(r"Dziennik Ustaw\s*–\s*\d+\s*–\s*Poz\. 1144", " ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _split(pattern: str, text: str) -> list[tuple[str, str]]:
    parts = re.split(pattern, text)
    return [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


def _pkt_units(prefix: str, citation: str, body: str, page: int) -> list[dict]:
    lead, *_ = re.split(r"\s1\)\s", body, maxsplit=1)
    points = _split(r"\s(\d+)\)\s", " " + body)
    return [{"citation": f"{citation} pkt {no}", "parent": prefix, "page": page,
             "text": f"{lead.strip()} {no}) {text.rstrip(';.')}." if not text.endswith(":") else f"{lead.strip()} {no}) {text}"}
            for no, text in points]


def build(pdf: Path) -> dict:
    pages = [p.extract_text() for p in PdfReader(str(pdf)).pages[:3]]
    page_of: list[tuple[int, str]] = []
    for no, raw in enumerate(pages, start=1):
        page_of.append((no, _clean(raw)))
    full = " ".join(text for _, text in page_of)
    body = full[full.index("§ 1."):full.index("Prezes Rady Ministrów: E. Kopacz")]

    def page_for(snippet: str) -> int:
        return next((no for no, text in page_of if snippet[:40] in text), 1)

    units = []
    for par, content in _split(r"§ (\d+)\.\s", " " + body):
        citation = f"§ {par}"
        if re.match(r"^1\.\s", content):
            for ust, text in _split(r"(?:^|\s)(\d+)\.\s(?=[A-ZŁŚŻŹĆĄĘÓŃ])", " " + content):
                ust_citation = f"{citation} ust. {ust}"
                if (par, ust) in SPLIT_PKT_UST:
                    units += _pkt_units(citation, ust_citation, text, page_for(text))
                else:
                    units.append({"citation": ust_citation, "parent": citation, "page": page_for(text), "text": text})
        elif par in SPLIT_PKT_PARAGRAPHS:
            units += _pkt_units(citation, citation, content, page_for(content))
        else:
            units.append({"citation": citation, "page": page_for(content), "text": content})
    return {
        "source_id": "rozp_2015",
        "source_title": "Rozporządzenie Prezesa Rady Ministrów z dnia 23 lipca 2015 r. w sprawie szczegółowych warunków "
                        "i sposobu dokonywania pierwszej oceny w służbie cywilnej (Dz. U. poz. 1144)",
        "short_title": "Rozporządzenie PRM z 23.07.2015 r. w sprawie pierwszej oceny (Dz. U. poz. 1144)",
        "process": "pierwsza",
        "units": units + ANNEX_UNITS,
    }


if __name__ == "__main__":
    doc = build(Path(sys.argv[1]))
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for u in doc["units"]:
        print(f"{u['citation']:<70} {u['text'][:90]}")
