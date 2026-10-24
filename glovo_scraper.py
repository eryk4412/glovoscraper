"""
Uniwersalny Scraper Menu dla platformy Glovo (glovoapp.com)
Pobiera:
- Pełną strukturę kategorii i dań
- Ceny bazowe oraz dokładne opisy
- Wykrywanie i wyodrębnianie składników (ingredients)
- Grupy dodatków, modyfikatorów, wyboru sosów, stopni wysmażenia (popup_details)
- Warianty rozmiarowe i wybory wielkości
- Zdjęcia dań w oryginalnej, pełnej rozdzielczości HD
- Zapis zdjęć z nazwami odpowiadającymi nazwom dań 1:1
- Eksport danych do formatów: JSON (słownik kategorii), CSV (Excel PL), Excel (.xlsx) oraz restaurant_info.json
- Wsparcie dla zapytań bezpośrednich HTTP z automatycznym fallbackiem Selenium (w razie blokad)
"""

import os
import sys
import re
import json
import time
import argparse
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# Poprawka kodowania znaków dla konsoli Windows
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

DEFAULT_GLOVO_URL = "https://glovoapp.com/pl/pl/wroclaw/stores/bella-ciao-burger-wro"

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'sec-ch-ua-platform': 'Windows',
    'upgrade-insecure-requests': '1',
}


def sanitize_filename(name: str) -> str:
    """
    Oczyszcza nazwę pliku z niedozwolonych znaków w systemie Windows (<>:"/\\|?*),
    zachowując polskie znaki diakrytyczne i oryginalną nazwę dania 1:1.
    """
    clean = re.sub(r'[<>:"/\\|?*]', '_', name)
    clean = re.sub(r'\s+', ' ', clean).strip()
    clean = clean.rstrip('. ')
    if not clean:
        clean = "danie"
    return clean[:120]


def extract_ingredients(desc: str) -> list[str] | None:
    """
    Wykrywa i wyodrębnia składniki z opisu dania, jeśli opis jest listą składników.
    """
    if not desc:
        return None
    cleaned = desc.strip()
    if cleaned.lower().startswith('składniki:'):
        cleaned = cleaned[len('składniki:'):].strip()
    elif cleaned.lower().startswith('skladniki:'):
        cleaned = cleaned[len('skladniki:'):].strip()

    parts = [p.strip().rstrip('.') for p in re.split(r'[,+;]', cleaned) if p.strip()]
    if len(parts) >= 2 and all(len(p) <= 40 for p in parts):
        first_lower = parts[0].lower()
        non_ingredient_starters = (
            'kawałki', 'aromatyczny', 'klasyczna', 'tradycyjne', 'intensywne',
            'pyszne', 'kremowy', 'gazowany', 'podwójny', 'delikatny', 'chrupiący',
            'wyjątkowy', 'soczysty', 'zamknięte', 'smash burger do wyboru', 'burger do wyboru'
        )
        if not any(first_lower.startswith(w) for w in non_ingredient_starters):
            return parts
    return None


def find_key_in_tree(obj, key):
    """
    Rekurencyjnie wyszukuje klucz w zagnieżdżonym drzewie słowników i list.
    """
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            res = find_key_in_tree(v, key)
            if res is not None:
                return res
    elif isinstance(obj, list):
        for item in obj:
            res = find_key_in_tree(item, key)
            if res is not None:
                return res
    return None


def fetch_page_html(url: str) -> tuple[str, str]:
    """
    Pobiera kod HTML strony lokalu na Glovo.
    W pierwszej kolejności używa szybkiego requests.Session() z nagłówkami przeglądarki.
    Jeśli wykryje blokadę Cloudflare lub błąd, automatycznie uruchamia Selenium z bezgłowym Chrome.
    """
    print(f"[*] Pobieranie strony: {url}")
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    try:
        resp = session.get(url, timeout=15)
        # Glovo używa Next.js App Router streaming (__next_f lub initialStoreContent)
        if resp.status_code == 200 and ('__next_f' in resp.text or 'initialStoreContent' in resp.text):
            print(f"[+] Pomyślnie pobrano stronę przez bezpośrednie HTTP (rozmiar: {len(resp.text):,} bajtów).")
            # Zwracamy zdekodowany tekst w UTF-8
            return resp.content.decode('utf-8', errors='replace'), url
    except Exception as e:
        print(f"[!] Bezpośrednie zapytanie HTTP nie powiodło się: {e}")

    # Fallback Selenium (np. ochrona Cloudflare / JS challenge)
    print("[*] Uruchamianie Selenium (Headless Chrome)...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument(f"user-agent={BROWSER_HEADERS['User-Agent']}")

        driver = webdriver.Chrome(options=chrome_options)
        try:
            driver.get(url)
            time.sleep(3)
            html = driver.page_source
            print(f"[+] Selenium pomyślnie pobrało wyrenderowaną stronę (rozmiar: {len(html):,} bajtów).")
            return html, url
        finally:
            driver.quit()
    except Exception as e:
        print(f"[!] Błąd Selenium: {e}")
        raise RuntimeError(f"Nie udało się pobrać strony {url} ani przez requests, ani przez Selenium.")


def extract_rsc_stream_from_html(html: str) -> str:
    """
    Wyciąga i łączy wszystkie strumienie Next.js RSC z wywołań self.__next_f.push.
    Używa dekodera JSON dla zachowania pełnej poprawności i braku problemów z uciekaniem znaków.
    """
    pushes = []
    for m in re.finditer(r'self\.__next_f\.push\(', html):
        start = m.end()
        bracket_start = html.find('[', start)
        if bracket_start != -1 and bracket_start - start < 5:
            try:
                arr, _ = json.JSONDecoder().raw_decode(html, bracket_start)
                if isinstance(arr, list) and len(arr) == 2 and arr[0] == 1 and isinstance(arr[1], str):
                    pushes.append(arr[1])
            except Exception:
                pass

    if pushes:
        return "".join(pushes)

    # Fallback regex, gdyby struktura HTML była niestandardowa
    matches = re.findall(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)', html, re.DOTALL)
    full_stream = ""
    for m in matches:
        try:
            full_stream += json.loads(f'"{m}"')
        except Exception:
            full_stream += m.replace(r'\"', '"').replace(r'\n', '\n').replace(r'\\', '\\')
    return full_stream


def parse_glovo_menu(html: str, url: str = "") -> tuple[dict, list[dict], dict[str, list[dict]]]:
    """
    Parsuje stronę lokalu Glovo i generuje:
    - restaurant_meta: słownik z metadanymi lokalu (nazwa, adres, rating, banner, itp.)
    - flat_items: płaską listę dań z informacjami do tabeli i pobierania zdjęć
    - menu_dict: słownik kategorii { "Kategoria": [ { danie } ] } zgodnie z wymaganym schematem JSON
    """
    full_stream = extract_rsc_stream_from_html(html)
    if not full_stream:
        raise ValueError("Nie znaleziono danych strumienia Next.js (__next_f) w kodzie strony Glovo.")

    lines = full_stream.split('\n')
    target_line = None
    for l in lines:
        if 'initialStoreContent' in l:
            target_line = l
            break

    if not target_line:
        raise ValueError("Nie znaleziono obiektu initialStoreContent w strumieniu RSC strony Glovo.")

    colon_idx = target_line.find(':')
    if colon_idx == -1:
        raise ValueError("Niepoprawny format linii RSC w stronie Glovo.")

    data = json.loads(target_line[colon_idx + 1:])

    store_info = find_key_in_tree(data, "store") or {}
    restaurant_meta = {
        'name': store_info.get('name', 'Glovo Store'),
        'slug': store_info.get('slug', ''),
        'address': store_info.get('address'),
        'rating': store_info.get('rating'),
        'image': store_info.get('image'),
        'cityCode': store_info.get('cityCode'),
        'url': url
    }

    store_content = find_key_in_tree(data, "initialStoreContent") or {}
    body = store_content.get('data', {}).get('body', [])

    flat_items = []
    menu_dict = {}
    item_counter = 1

    for sec in body:
        sec_data = sec.get('data', {})
        cat_name = (sec_data.get('title') or 'Inne').strip()
        elements = sec_data.get('elements', [])
        if not elements:
            continue

        for el in elements:
            p_data = el.get('data', {}) or el
            name = (p_data.get('name') or p_data.get('title') or f"Danie {item_counter}").strip()
            desc = (p_data.get('description') or '').strip()

            # Pobieranie ceny numerycznej
            raw_price = p_data.get('price')
            if raw_price is None and isinstance(p_data.get('priceInfo'), dict):
                raw_price = p_data['priceInfo'].get('amount')
            try:
                base_price = round(float(raw_price), 2) if raw_price is not None else 0.0
            except (ValueError, TypeError):
                base_price = 0.0

            # Czysty URL zdjęcia HD w pełnej rozdzielczości (odcięcie parametrów ?t=... zmniejszających jakość)
            raw_img_url = p_data.get('imageUrl') or ''
            hd_img_url = raw_img_url.split('?')[0] if raw_img_url else ''

            attr_groups = p_data.get('attributeGroups', []) or []

            # Sprawdzamy czy istnieje dedykowana grupa wyboru rozmiaru (wariantów wielkości)
            size_group = None
            other_groups = []
            size_keywords = ('rozmiar', 'wielkość', 'wielkosc', 'size', 'średnica', 'srednica')
            for g in attr_groups:
                g_name_lower = (g.get('name') or '').lower()
                is_single = (g.get('max') == 1)
                is_req = (g.get('min', 0) >= 1)
                if is_single and is_req and any(kw in g_name_lower for kw in size_keywords) and len(g.get('attributes', [])) > 1:
                    size_group = g
                else:
                    other_groups.append(g)

            # Pomocnicza funkcja do budowania grup opcji
            def build_groups(groups_list):
                formatted_groups = []
                for g in groups_list:
                    g_name = (g.get('name') or 'Dodatki').strip()
                    max_c = g.get('max', 1)
                    min_c = g.get('min', 0)
                    is_single = (max_c == 1)
                    is_req = (min_c >= 1)

                    choices = []
                    for a in g.get('attributes', []) or []:
                        a_name = (a.get('name') or '').strip()
                        impact = a.get('priceImpact')
                        try:
                            a_price = round(float(impact), 2) if impact is not None else 0.0
                        except (ValueError, TypeError):
                            a_price = 0.0
                        choices.append({
                            'name': a_name,
                            'price': a_price
                        })

                    formatted_groups.append({
                        'group_name': g_name,
                        'group': 'single_choice_group' if is_single else 'multi_choice_group',
                        'type': 'single' if is_single else 'multi',
                        'required': is_req,
                        'choices': choices
                    })
                return formatted_groups

            # Budowanie obiektu dania do słownika menu_dict
            dish = {
                'name': name,
                'price': base_price,
                'description': desc
            }

            ingredients = extract_ingredients(desc)
            if ingredients:
                dish['ingredients'] = ingredients

            if size_group:
                variants_list = []
                base_formatted_groups = build_groups(other_groups)
                for a in size_group.get('attributes', []):
                    v_label = (a.get('name') or '').strip()
                    impact = a.get('priceImpact', 0.0) or 0.0
                    v_price = round(base_price + float(impact), 2)
                    variants_list.append({
                        'label': v_label,
                        'price': v_price,
                        'groups': base_formatted_groups
                    })
                dish['popup_details'] = {
                    'variants': variants_list
                }
            elif attr_groups:
                dish['popup_details'] = {
                    'variants': [
                        {
                            'label': 'Domyślny',
                            'price': base_price,
                            'groups': build_groups(attr_groups)
                        }
                    ]
                }

            # Dodajemy pozycję do menu_dict z zachowaniem podziału na kategorie
            cat_list = menu_dict.setdefault(cat_name, [])
            # Unikamy duplikowania identycznych dań wewnątrz tej samej sekcji
            if not any(d['name'] == dish['name'] and d['price'] == dish['price'] for d in cat_list):
                cat_list.append(dish)

            # Informacje dla płaskiej listy
            variants_info = []
            if size_group:
                for a in size_group.get('attributes', []):
                    impact = float(a.get('priceImpact', 0.0) or 0.0)
                    variants_info.append({
                        'name': a.get('name'),
                        'price': round(base_price + impact, 2)
                    })

            addons_info = []
            addons_by_group = {}
            for g in (other_groups if size_group else attr_groups):
                g_name = (g.get('name') or 'Dodatki').strip()
                for a in g.get('attributes', []):
                    a_name = a.get('name')
                    a_price = round(float(a.get('priceImpact', 0.0) or 0.0), 2)
                    addons_info.append({
                        'group': g_name,
                        'name': a_name,
                        'price': a_price
                    })
                    addons_by_group.setdefault(g_name, []).append((a_name, a_price))

            addons_raw_parts = []
            for gname, m_list in addons_by_group.items():
                opts_str = ", ".join([f"{m[0]} (+{m[1]:.2f} zł)" if m[1] > 0 else m[0] for m in m_list])
                addons_raw_parts.append(f"{gname}: {opts_str}")
            addons_raw = "; ".join(addons_raw_parts)

            clean_filename = f"{sanitize_filename(name)}.jpg" if hd_img_url else ""

            flat_items.append({
                'id': p_data.get('id') or str(item_counter),
                'category': cat_name,
                'name': name,
                'description': desc,
                'price_raw': f"{base_price:,.2f} zł".replace('.', ','),
                'price': base_price,
                'badges': [t.get('name') for t in p_data.get('tags', []) if isinstance(t, dict) and t.get('name')],
                'image_url': hd_img_url,
                'variants': variants_info,
                'addons': addons_info,
                'addons_raw': addons_raw,
                'image_filename': clean_filename
            })

            item_counter += 1

    print(f"[+] Pomyślnie sparsowano menu Glovo: {len(menu_dict)} kategorii, {len(flat_items)} pozycji.")
    return restaurant_meta, flat_items, menu_dict


# ==============================================================================
#                      POBIERANIE ZDJĘĆ I EKSPORT WYNIKÓW
# ==============================================================================

def download_single_image(item: dict, output_dir: str, session: requests.Session, url_cache: dict) -> str:
    """
    Pobiera pojedyncze zdjęcie w pełnej jakości HD i zapisuje je w folderze output_dir.
    Nazwa pliku odpowiada 1:1 nazwie dania (np. 'Oklahoma Smash.jpg').
    Używa pamięci podręcznej pobranych bajtów, aby nie odpytywać sieci wielokrotnie dla tego samego URL.
    """
    img_url = item.get('image_url')
    if not img_url:
        return ""

    clean_name = sanitize_filename(item['name'])

    # Ustalenie domyślnego rozszerzenia z URL
    ext = ".jpg"
    lower_url = img_url.lower()
    if ".webp" in lower_url:
        ext = ".webp"
    elif ".png" in lower_url:
        ext = ".png"

    filename = f"{clean_name}{ext}"
    filepath = os.path.join(output_dir, filename)

    # Jeśli już pobrano ten URL dla innego dania lub ten plik już istnieje
    if img_url in url_cache:
        content, real_ext = url_cache[img_url]
        filename = f"{clean_name}{real_ext}"
        filepath = os.path.join(output_dir, filename)
        if not os.path.exists(filepath):
            with open(filepath, 'wb') as f:
                f.write(content)
        item['image_filename'] = filename
        return filename

    try:
        r = session.get(img_url, timeout=25)
        if r.status_code == 200:
            ctype = r.headers.get('content-type', '').lower()
            if 'png' in ctype:
                ext = '.png'
            elif 'webp' in ctype:
                ext = '.webp'
            else:
                ext = '.jpg'

            filename = f"{clean_name}{ext}"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(r.content)

            url_cache[img_url] = (r.content, ext)
            item['image_filename'] = filename
            return filename
    except Exception as e:
        print(f"[!] Błąd pobierania zdjęcia dla '{item['name']}' ({img_url}): {e}")

    return ""


def download_all_images(items: list[dict], output_dir: str, max_workers: int = 10):
    """
    Pobiera wszystkie zdjęcia dań równolegle za pomocą puli wątków.
    Każde zdjęcie otrzymuje nazwę odpowiadającą nazwie dania 1:1.
    """
    items_with_images = [item for item in items if item.get('image_url')]
    total_imgs = len(items_with_images)
    print(f"[*] Pobieranie {total_imgs} zdjęć w pełnej rozdzielczości HD do folderu '{output_dir}' (wątki: {max_workers})...")

    os.makedirs(output_dir, exist_ok=True)
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    url_cache = {}

    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_single_image, item, output_dir, session, url_cache): item for item in items_with_images}
        for f in as_completed(futures):
            f.result()
            completed += 1
            if completed % 10 == 0 or completed == total_imgs:
                print(f"    Pobrano zdjęć: {completed}/{total_imgs}")

    saved_count = sum(1 for item in items if item.get('image_filename'))
    print(f"[+] Zakończono pobieranie zdjęć: przypisano {saved_count}/{total_imgs} plików 1:1.")


def export_to_files(items: list[dict], menu_dict: dict, restaurant_meta: dict, base_dir: str):
    """
    Eksportuje dane menu do formatów:
    1. menu.json – słownik { "Kategoria": [ { danie } ] } zgodnie ze schematem użytkownika
    2. menu_flat.json – płaska lista pozycji
    3. menu.csv – arkusz CSV ze średnikami i kodowaniem UTF-8 BOM
    4. menu.xlsx – sformatowany arkusz Excel (.xlsx)
    5. restaurant_info.json – metadane lokalu
    """
    print(f"[*] Eksport danych do plików wynikowych w katalogu: {base_dir}")
    os.makedirs(base_dir, exist_ok=True)

    # 1. Metadane lokalu (restaurant_info.json)
    if restaurant_meta:
        meta_path = os.path.join(base_dir, "restaurant_info.json")
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(restaurant_meta, f, indent=2, ensure_ascii=False)
        print(f"[+] Zapisano metadane lokalu: {meta_path}")

    # 2. Główny plik menu (menu.json) – słownik { "Kategoria": [ { danie } ] }
    json_path = os.path.join(base_dir, "menu.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(menu_dict, f, indent=2, ensure_ascii=False)
    print(f"[+] Zapisano (słownik kategorii JSON 1:1): {json_path}")

    # Płaska lista JSON (menu_flat.json)
    flat_json_path = os.path.join(base_dir, "menu_flat.json")
    with open(flat_json_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    # Przygotowanie wierszy tabelarycznych dla CSV/Excel
    rows = []
    for item in items:
        variants_str = "; ".join([f"{v['name']} ({v['price']:.2f} zł)" if v.get('price') else v['name'] for v in item.get('variants', [])])
        badges_str = ", ".join(item.get('badges', []))

        rows.append({
            'Kategoria': item['category'],
            'Nazwa dania': item['name'],
            'Cena': item['price_raw'],
            'Cena numeryczna (PLN)': item['price'],
            'Opis': item['description'],
            'Dodatki': item['addons_raw'],
            'Warianty wyboru': variants_str,
            'Cechy / Tagi': badges_str,
            'Plik zdjęcia': item['image_filename'],
            'URL zdjęcia': item['image_url'],
            'ID produktu': item['id']
        })

    # 3. CSV (Excel PL - średnik jako separator, kodowanie UTF-8 z BOM)
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        csv_path = os.path.join(base_dir, "menu.csv")
        df.to_csv(csv_path, index=False, encoding='utf-8-sig', sep=';')
        print(f"[+] Zapisano: {csv_path}")

        # 4. Excel (.xlsx)
        xlsx_path = os.path.join(base_dir, "menu.xlsx")
        sheet_title = (restaurant_meta.get('name') or 'Menu')[:31]
        with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_title)
            worksheet = writer.sheets[sheet_title]
            for col in worksheet.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = col[0].column_letter
                worksheet.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 60)
        print(f"[+] Zapisano: {xlsx_path}")
    except Exception as e:
        print(f"[!] Błąd przy generowaniu arkuszy CSV/Excel: {e}")


def scrape_glovo_store(url: str, output_dir: str, images_dir_name: str = "zdjecia", download_imgs: bool = True, workers: int = 10):
    """
    Główna funkcja wykonująca pobieranie dla lokalu Glovo.
    """
    url = url.strip()
    if not url:
        return

    print("\n" + "=" * 65)
    print(f"Rozpoczynanie pobierania menu Glovo: {url}")
    print("=" * 65)

    images_dir = os.path.join(output_dir, images_dir_name)

    html, final_url = fetch_page_html(url)
    restaurant_meta, items, menu_dict = parse_glovo_menu(html, final_url)
    if not items:
        print("[!] Nie znaleziono pozycji w menu dla tego linku.")
        return

    if download_imgs:
        download_all_images(items, images_dir, max_workers=workers)
    else:
        print("[*] Pominięto pobieranie plików graficznych (--no-images).")

    export_to_files(items, menu_dict, restaurant_meta, output_dir)
    print(f"[✓] Gotowe! Zapisano dane dla lokalu: {restaurant_meta.get('name', url)}")


def normalize_url(raw_url: str) -> str:
    """
    Oczyszcza i normalizuje podany URL (usuwa cudzysłowy, spacje, dodaje https:// jeśli brak).
    """
    if not raw_url:
        return ""
    clean = raw_url.strip().strip('"\'')
    if not clean:
        return ""
    clean = clean.split()[0]
    if not clean.startswith(('http://', 'https://')):
        clean = 'https://' + clean
    return clean


def extract_slug_from_url(url: str, default_prefix: str = "glovo_lokal") -> str:
    """
    Wyciąga czytelny slug / nazwę lokalu z adresu URL do utworzenia podkatalogu.
    """
    slug_match = re.search(r'/(?:stores|store)/([a-zA-Z0-9_\-]+)', url)
    if slug_match:
        return slug_match.group(1)
    clean_path = url.split('?')[0].rstrip('/')
    parts = [p for p in clean_path.split('/') if p]
    if parts:
        return parts[-1]
    return f"{default_prefix}_{int(time.time())}"


def main():
    parser = argparse.ArgumentParser(description="Uniwersalny scraper menu Glovo (glovoapp.com)")
    parser.add_argument('urls', nargs='*', help="Jeden lub więcej linków do restauracji/sklepów na Glovo")
    parser.add_argument('--url', action='append', help="Dodatkowy link do lokalu (można podać wielokrotnie)")
    parser.add_argument('--urls-file', help="Ścieżka do pliku tekstowego z linkami (jeden URL na linię)")
    parser.add_argument('--output-dir', default='.', help="Katalog wyjściowy dla pobranych danych (domyślnie bieżący)")
    parser.add_argument('--images-dir', default='zdjecia', help="Nazwa podfolderu na zdjęcia (domyślnie 'zdjecia')")
    parser.add_argument('--no-images', action='store_true', help="Pomiń pobieranie plików graficznych")
    parser.add_argument('--workers', type=int, default=10, help="Liczba równoległych wątków pobierania (domyślnie 10)")
    parser.add_argument('--by-restaurant', action='store_true', help="Zapisuj każdy lokal do osobnego podfolderu z nazwą lokalu")
    args = parser.parse_args()

    # Zbieranie linków przekazanych w argumentach
    urls_to_scrape = []
    if args.urls:
        for u in args.urls:
            cleaned = normalize_url(u)
            if cleaned:
                urls_to_scrape.append(cleaned)
    if args.url:
        for u in args.url:
            cleaned = normalize_url(u)
            if cleaned:
                urls_to_scrape.append(cleaned)
    if args.urls_file and os.path.exists(args.urls_file):
        with open(args.urls_file, 'r', encoding='utf-8') as f:
            for line in f:
                l = normalize_url(line)
                if l and not l.startswith('#'):
                    urls_to_scrape.append(l)

    is_interactive = False

    # Jeśli nie podano linków w argumentach CLI ani pliku, pytamy użytkownika interaktywnie
    if not urls_to_scrape:
        is_interactive = True
        print("\n" + "=" * 65)
        print("                 SCRAPER MENU GLOVO (GLOVOAPP.COM)")
        print("=" * 65)
        print("Wskazówka: Możesz wkleić dowolny link do wybranego lokalu na Glovo.")
        print(f"Przykładowy: {DEFAULT_GLOVO_URL}")
        print("=" * 65)

        while True:
            try:
                user_input = input("\n🔗 Wklej link do lokalu na Glovo:\n(Naciśnij Enter, aby użyć przykładowego Bella Ciao Burger)\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[!] Przerwano działanie programu.")
                return

            if user_input:
                clean_url = normalize_url(user_input)
                if clean_url:
                    urls_to_scrape.append(clean_url)
                    break
                else:
                    print("[!] Podano niepoprawny adres URL. Spróbuj ponownie.")
            else:
                print(f"[*] Wybrano przykładowy lokal: {DEFAULT_GLOVO_URL}")
                urls_to_scrape.append(DEFAULT_GLOVO_URL)
                break

    print("\n" + "=" * 65)
    print("                SCRAPER MENU GLOVO (GLOVOAPP.COM)")
    print(f" Liczba linków do przetworzenia: {len(urls_to_scrape)}")
    print("=" * 65)

    base_output_dir = os.path.abspath(args.output_dir)

    for i, url in enumerate(urls_to_scrape, 1):
        if len(urls_to_scrape) > 1 or args.by_restaurant:
            sub_name = extract_slug_from_url(url, f"glovo_lokal_{i}")
            curr_output_dir = os.path.join(base_output_dir, sub_name)
        else:
            curr_output_dir = base_output_dir

        scrape_glovo_store(
            url=url,
            output_dir=curr_output_dir,
            images_dir_name=args.images_dir,
            download_imgs=not args.no_images,
            workers=args.workers
        )

    # W trybie interaktywnym pytamy o kolejne lokale
    if is_interactive:
        while True:
            try:
                next_input = input("\n🔗 Wklej kolejny link do lokalu na Glovo (lub naciśnij Enter, aby zakończyć):\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not next_input:
                break

            next_url = normalize_url(next_input)
            if next_url:
                sub_name = extract_slug_from_url(next_url, f"glovo_lokal_{int(time.time())}")
                curr_output_dir = os.path.join(base_output_dir, sub_name)

                scrape_glovo_store(
                    url=next_url,
                    output_dir=curr_output_dir,
                    images_dir_name=args.images_dir,
                    download_imgs=not args.no_images,
                    workers=args.workers
                )

    print("\n" + "=" * 65)
    print("[✓] Wszystkie zadania zostały pomyślnie zakończone!")
    print("=" * 65)


if __name__ == '__main__':
    main()
