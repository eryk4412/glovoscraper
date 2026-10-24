# 🍔 Uniwersalny Scraper Menu Glovo (glovoapp.com)

Nowoczesny, szybki scraper w języku Python do automatycznego pobierania kompletnego menu **1:1** z dowolnej restauracji lub sklepu na platformie **Glovo** (`glovoapp.com`).

---

### 📋 Co pobiera scraper?
- **Kategorie i sekcje lokalu** (np. *Promocje*, *Burgery*, *Dodatki*, *Napoje*, *Desery*)
- **Wszystkie pozycje menu** (nazwy dań oraz dokładne opisy)
- **Ceny bazowe** oraz sformatowane ("XX,XX zł")
- **Wykrywanie składników dań (`ingredients`)** z opisu pozycji
- **Warianty wyboru i rozmiary (`variants`)** wraz z dopłatami
- **Wszystkie grupy modyfikatorów i dodatków (`popup_details` / `groups`)**:
  - Wybór stopnia wysmażenia, sosów, napojów, dodatków
  - Rozróżnienie grup pojedynczego (`single_choice_group`) oraz wielokrotnego wyboru (`multi_choice_group`)
  - Oznaczenie pól wymaganych (`required: true / false`)
  - Ceny poszczególnych opcji
- **Zdjęcia w oryginalnej rozdzielczości HD** (oryginały bez kompresji i znaków wodnych)
- **Nazwy plików zdjęć zgodne z nazwami dań 1:1** (np. `Oklahoma Smash.jpg`, `Smash Baconator.jpg`)
- **Metadane lokalu**: nazwa, slug, ocena, miasto, URL
- **Eksport do wielu formatów**:
  - `menu.json` – słownik kategorii `{ "Kategoria": [ { danie } ] }` zgodnie ze specyfikacją
  - `menu_flat.json` – płaska lista wszystkich pozycji ze szczegółami technicznymi
  - `menu.csv` – arkusz CSV ze średnikami i kodowaniem UTF-8 BOM (gotowy do otwarcia w polskim Excelu)
  - `menu.xlsx` – sformatowany arkusz Excel (.xlsx) z dopasowaną szerokością kolumn
  - `restaurant_info.json` – metadane lokalu
  - `zdjecia/` – katalog z pobranymi zdjęciami o nazwach odpowiadających daniom 1:1

---

## 🎯 Format wyjściowy JSON (`menu.json`)

Wyjściowy plik JSON jest generowany w formacie:
```json
{
  "Pizza": [
    {
      "name": "Pizza Margherita",
      "price": 32.00,
      "description": "Klasyczna włoska pizza z sosem pomidorowym i mozzarellą fior di latte.",
      "ingredients": [
        "Sos pomidorowy",
        "Mozzarella fior di latte",
        "Świeża bazylia",
        "Oliwa z oliwek"
      ],
      "popup_details": {
        "variants": [
          {
            "label": "Mała (30 cm)",
            "price": 32.00,
            "groups": [
              {
                "group_name": "Dodatki do pizzy",
                "group": "multi_choice_group",
                "type": "multi",
                "required": false,
                "choices": [
                  { "name": "Podwójny ser", "price": 5.00 },
                  { "name": "Pieczarki", "price": 3.50 }
                ]
              },
              {
                "group_name": "Wybór sosu",
                "group": "single_choice_group",
                "type": "single",
                "required": true,
                "choices": [
                  { "name": "Sos czosnkowy", "price": 0.00 },
                  { "name": "Sos pomidorowy ostry", "price": 0.00 }
                ]
              }
            ]
          }
        ]
      }
    }
  ],
  "Burgery": [
    {
      "name": "Burger Klasyczny",
      "price": 38.00,
      "description": "200g wołowiny, sałata, pikle, czerwona cebula, sos autorski.",
      "popup_details": {
        "variants": [
          {
            "label": "Domyślny",
            "price": 38.00,
            "groups": [
              {
                "group_name": "Stopień wysmażenia",
                "group": "single_choice_group",
                "type": "single",
                "required": true,
                "choices": [
                  { "name": "Krwisty (Rare)", "price": 0.00 },
                  { "name": "Średnio wysmażony (Medium)", "price": 0.00 },
                  { "name": "Dobrze wysmażony (Well Done)", "price": 0.00 }
                ]
              }
            ]
          }
        ]
      }
    }
  ],
  "Napoje": [
    {
      "name": "Coca-Cola 0.33l",
      "price": 9.00,
      "description": "Puszka schłodzonej Coca-Coli."
    }
  ]
}
```

---

## ⚡ Instalacja

1. Sklonuj repozytorium:
```bash
git clone https://github.com/eryk4412/glovoscraper.git
cd glovoscraper
```

2. Zainstaluj wymagane pakiety:
```bash
pip install -r requirements.txt
```

---

## 🚀 Jak uruchomić?

### 1. Tryb interaktywny (wklejanie dowolnego linku)

Uruchom skrypt bez argumentów:
```bash
python glovo_scraper.py
```
Program wyświetli prompt, w którym możesz wkleić **dowolny link do lokalu na Glovo**:
```text
🔗 Wklej link do lokalu na Glovo:
(Naciśnij Enter, aby użyć przykładowego Bella Ciao Burger)
> 
```
Po pobraniu danych program zapyta, czy chcesz pobrać kolejny lokal – możesz wklejać kolejne adresy w jednej sesji.

---

### 2. Bezpośredni link w wierszu poleceń

Możesz podać link bezpośrednio jako argument:
```bash
python glovo_scraper.py https://glovoapp.com/pl/pl/wroclaw/stores/bella-ciao-burger-wro
```

Pobieranie wielu lokali na raz:
```bash
python glovo_scraper.py https://glovoapp.com/.../store-1 https://glovoapp.com/.../store-2
```

Lub z pliku tekstowego (jeden link na linię):
```bash
python glovo_scraper.py --urls-file linki.txt
```

---

### ⚙️ Dostępne parametry

| Parametr | Opis | Przykład |
| :--- | :--- | :--- |
| `--output-dir` | Wskazanie własnego folderu zapisu (domyślnie bieżący) | `python glovo_scraper.py <URL> --output-dir ./dane` |
| `--images-dir` | Własna nazwa folderu na zdjęcia (domyślnie `zdjecia`) | `python glovo_scraper.py <URL> --images-dir photos` |
| `--no-images` | Pobiera tylko dane tekstowe (JSON/CSV/Excel) bez pobierania plików zdjęć | `python glovo_scraper.py <URL> --no-images` |
| `--workers` | Liczba równoległych wątków pobierania zdjęć (domyślnie `10`) | `python glovo_scraper.py <URL> --workers 15` |
| `--by-restaurant` | Zapisuje każdy lokal do osobnego podfolderu z nazwą lokalu | `python glovo_scraper.py <URL> --by-restaurant` |

---

## 🛡️ Architektura i Ochrona Anty-Bot

1. **Szybkie bezpośrednie HTTP (Next.js App Router)**:
   Scraper dekoduje strumień React Server Components (`self.__next_f`), co pozwala na pobranie całego menu w ułamku sekundy bez konieczności uruchamiania przeglądarki.
2. **Automatyczny fallback Selenium (Headless Chrome)**:
   W razie wykrycia ochrony Cloudflare lub blokad IP, skrypt automatycznie uruchamia bezgłową przeglądarkę Chrome w tle, by pobrać wyrenderowane dane.
