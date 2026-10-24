# 🍽️ Uniwersalny Scraper Menu (Glovo, Pyszne.pl & UpMenu)

Zestaw skryptów w języku Python automatycznie pobierających kompletne menu 1:1 z dowolnej restauracji lub sklepu na platformie **Glovo** (`glovoapp.com`), **Pyszne.pl** oraz **UpMenu** (np. Czar Sushi).

---

### 📋 Co pobiera scraper?
- **Kategorie i sekcje dań**
- **Wszystkie pozycje menu** (nazwy dań i pełne opisy)
- **Ceny bazowe** oraz sformatowane ("XX,XX zł")
- **Wykrywanie składników dań (`ingredients`)**
- **Warianty wyboru i rozmiary** (`variants`) z osobnymi cenami
- **Wszystkie grupy dodatków i modyfikatorów (`popup_details` / `groups`)** (np. stopień wysmażenia, dobór sosu, frytki, napoje) wraz z dopłatami i typem grupy (`single_choice_group` / `multi_choice_group`)
- **Zdjęcia w pełnej rozdzielczości HD** (oryginalne pliki bez kompresji i bez miniatur `?t=...`), zapisywane z nazwą odpowiadającą nazwie dania **1:1** (np. `Oklahoma Smash.jpg`)
- **Metadane lokalu**: nazwa, adres, rating, miasto, URL
- **Eksport do formatów**:
  - `menu.json` – słownik kategorii `{ "Kategoria": [ { danie } ] }` zgodnie z podanym schematem
  - `menu_flat.json` – płaska lista pozycji ze wszystkimi szczegółami
  - `menu.csv` – arkusz CSV ze średnikiem i znacznikiem UTF-8 BOM (otwiera się w polskim Excelu bez problemów z kodowaniem znaków)
  - `menu.xlsx` – sformatowany arkusz Excel z dopasowaną szerokością kolumn
  - `restaurant_info.json` – metadane lokalu
  - `zdjecia/` – folder z pobranymi plikami graficznymi wysokiej jakości o nazwach 1:1 z daniami

---

## 🎯 Format wyjściowy JSON (`menu.json`)

Struktura pliku odpowiada dokładnie podanemu formatowi:
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

## 🚀 Jak uruchomić?

### 1. Dedykowany Scraper Glovo (`glovo_scraper.py`)

Pobranie przykładowego lokalu Bella Ciao Burger:
```powershell
py glovo_scraper.py https://glovoapp.com/pl/pl/wroclaw/stores/bella-ciao-burger-wro
```

Możesz też uruchomić bez argumentów (zostanie użyty domyślny link lub możliwość podania własnego):
```powershell
py glovo_scraper.py
```

### 2. Uniwersalny Scraper Wieloplatformowy (`scraper.py`)

Skrypt automatycznie rozpoznaje platformę (Glovo, Pyszne.pl lub UpMenu) na podstawie podanego adresu URL:
```powershell
# Glovo
py scraper.py https://glovoapp.com/pl/pl/wroclaw/stores/bella-ciao-burger-wro

# Pyszne.pl
py scraper.py https://www.pyszne.pl/en/menu/mandala-mokotow-etiudy-rewolucyjnej

# UpMenu
py scraper.py https://www.czarsushi.pl/zamow-online
```

### 3. Pobieranie wielu lokali na raz

Możesz podać kilka linków w jednym wywołaniu lub wskazać plik tekstowy:
```powershell
py glovo_scraper.py https://glovoapp.com/.../store-1 https://glovoapp.com/.../store-2
py glovo_scraper.py --urls-file linki.txt
```

### 4. Opcjonalne parametry:

| Parametr | Opis | Przykład |
| :--- | :--- | :--- |
| `--output-dir` | Wskazanie katalogu wyjściowego (domyślnie bieżący) | `py glovo_scraper.py <URL> --output-dir ./dane` |
| `--images-dir` | Nazwa podfolderu na zdjęcia (domyślnie `zdjecia`) | `py glovo_scraper.py <URL> --images-dir photos` |
| `--no-images` | Pobiera tylko dane tekstowe (JSON/CSV/Excel) bez pobierania zdjęć | `py glovo_scraper.py <URL> --no-images` |
| `--workers` | Liczba równoległych wątków pobierania (domyślnie 10) | `py glovo_scraper.py <URL> --workers 15` |
| `--by-restaurant` | Zapisuje każdy lokal do podfolderu z nazwą/slugiem lokalu | `py glovo_scraper.py <URL> --by-restaurant` |
