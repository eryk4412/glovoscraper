"""
Uniwersalny Scraper Menu dla Pyszne.pl oraz UpMenu (Czar Sushi)
Pobiera:
- Nazwy dań i kategorie
- Dokładne opisy oraz alergeny / tagi
- Ceny bazowe oraz wszystkie warianty i rozmiary
- Grupy dodatków, modyfikatory i wybory z cenami
- Zdjęcia dań w pełnej, oryginalnej rozdzielczości
- Eksport danych do formatów: JSON, CSV (Excel PL) oraz Excel (.xlsx)
- Obsługę wielu linków, automatyczny fallback Selenium (Cloudflare bypass)
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

DEFAULT_PYSZNE_URL = "https://www.pyszne.pl/en/menu/mandala-mokotow-etiudy-rewolucyjnej"
DEFAULT_CZAR_SUSHI_URL = "https://www.czarsushi.pl/zamow-online"

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'sec-ch-ua-platform': 'Windows',
    'upgrade-insecure-requests': '1',
}


def sanitize_filename(name: str) -> str:
    """
    Oczyszcza nazwę pliku z niedozwolonych znaków w systemie Windows.
    """
    clean = re.sub(r'[<>:"/\\|?*]', '_', name)
    clean = re.sub(r'\s+', ' ', clean).strip()
    clean = clean.rstrip('. ')
    if not clean:
        clean = "danie"
    return clean[:120]


def adjust_url_language(url: str, lang: str) -> str:
    """
    Dopasowuje język w URL Pyszne.pl:
    - 'pl': usuwa /en/ z adresu
    - 'en': dodaje /en/ do adresu
    - 'auto': pozostawia oryginalny adres
    """
    if lang == 'pl':
        return url.replace('pyszne.pl/en/menu/', 'pyszne.pl/menu/')
    elif lang == 'en':
        if 'pyszne.pl/menu/' in url and 'pyszne.pl/en/menu/' not in url:
            return url.replace('pyszne.pl/menu/', 'pyszne.pl/en/menu/')
    return url


def fetch_page_html(url: str, lang: str = 'auto') -> tuple[str, str]:
    """
    Pobiera kod HTML strony.
    W pierwszej kolejności używa szybkiego requests.Session() z nagłówkami przeglądarki.
    Jeśli wykryje blokadę Cloudflare (kod 403 lub brak __NEXT_DATA__),
    automatycznie uruchamia Selenium z bezgłowym Chrome.
    """
    url = adjust_url_language(url, lang)
    print(f"[*] Pobieranie strony: {url}")

    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    try:
        resp = session.get(url, timeout=15)
        if resp.status_code == 200 and ('__NEXT_DATA__' in resp.text or 'theme-product' in resp.text or '__next_f' in resp.text or 'initialStoreContent' in resp.text):
            print(f"[+] Pomyślnie pobrano stronę przez bezpośrednie HTTP (rozmiar: {len(resp.text):,} bajtów).")
            return resp.content.decode('utf-8', errors='replace'), url
    except Exception as e:
        print(f"[!] Bezpośrednie zapytanie HTTP nie powiodło się: {e}")

    # Fallback Selenium (np. ochrona Cloudflare)
    print("[*] Wykryto ochronę Cloudflare lub błąd HTTP. Uruchamianie Selenium (Headless Chrome)...")
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


# ==============================================================================
#                      PARSER DLA PYSZNE.PL (JUST EAT TAKEAWAY)
# ==============================================================================

def parse_pyszne_menu(html: str) -> tuple[dict, list[dict]]:
    """
    Parsuje kod HTML ze strony restauracji Pyszne.pl i wyciąga pełne dane menu 1:1.
    """
    soup = BeautifulSoup(html, 'html.parser')
    tag = soup.find('script', id='__NEXT_DATA__')
    if not tag or not tag.text:
        raise ValueError("Nie znaleziono danych __NEXT_DATA__ w kodzie strony Pyszne.pl!")

    data = json.loads(tag.text)
    try:
        cdn = data['props']['appProps']['preloadedState']['menu']['restaurant']['cdn']
    except KeyError:
        raise ValueError("Struktura JSON strony Pyszne.pl różni się od oczekiwanej (brak klucza cdn w preloadedState).")

    # Metadane restauracji
    rest_data = cdn.get('restaurant', {})
    rest_info = rest_data.get('restaurantInfo', {})
    restaurant_meta = {
        'name': rest_info.get('name', ''),
        'seoName': rest_info.get('seoName', ''),
        'email': rest_info.get('email', ''),
        'phone': rest_info.get('allergenPhoneNumber', ''),
        'location': rest_info.get('location', {}),
        'logoUrl': rest_info.get('logoUrl', ''),
        'bannerUrl': rest_info.get('bannerUrl', '')
    }

    items_map = cdn.get('items', {})
    mod_groups = {mg['id']: mg for mg in cdn.get('modifierGroups', []) if isinstance(mg, dict) and 'id' in mg}
    mod_sets = {ms['id']: ms['modifier'] for ms in cdn.get('modifierSets', []) if isinstance(ms, dict) and 'id' in ms and 'modifier' in ms}

    menus = rest_data.get('menus', [])
    if not menus:
        print("[!] Brak menu w danych CDN.")
        return restaurant_meta, []

    # Używamy pierwszego dostępnego menu (zazwyczaj dostawa lub główne menu)
    menu = menus[0]
    categories = menu.get('categories', [])
    print(f"[+] Znaleziono {len(categories)} kategorii w menu restauracji '{restaurant_meta['name']}'.")

    items_out = []
    item_counter = 1

    for cat in categories:
        cat_name = cat.get('name', 'Inne')
        cat_desc = cat.get('description', '')
        item_ids = cat.get('itemIds', [])

        for item_id in item_ids:
            it = items_map.get(item_id)
            if not it:
                continue

            name = it.get('name', f'Danie {item_counter}').strip()
            desc = (it.get('description', '') or '').strip()

            variations = it.get('variations', [])
            prices = [float(v['basePrice']) for v in variations if v.get('basePrice') is not None]

            if len(prices) > 1 and max(prices) != min(prices):
                price_val = min(prices)
                price_raw = f"od {price_val:,.2f} zł".replace('.', ',')
            elif len(prices) >= 1:
                price_val = prices[0]
                price_raw = f"{price_val:,.2f} zł".replace('.', ',')
            else:
                price_val = None
                price_raw = ""

            # Warianty wyboru (np. rozmiary Regular 350 ml, Large 500 ml)
            variants_list = []
            if len(variations) > 1 or (len(variations) == 1 and variations[0].get('type') != 'NoVariation' and variations[0].get('name') != name):
                for v in variations:
                    v_name = v.get('name', '').strip()
                    v_price = float(v.get('basePrice', 0.0))
                    variants_list.append({
                        'name': v_name,
                        'price': v_price
                    })

            # Dodatki i opcje modyfikatorów
            addons_list = []
            seen_mod = set()
            addons_by_group = {}

            for v in variations:
                for mg_id in v.get('modifierGroupsIds', []) or []:
                    mg = mod_groups.get(mg_id)
                    if not mg:
                        continue
                    gname = mg.get('name', 'Dodatki').strip()
                    min_ch = mg.get('minChoices', 0)
                    max_ch = mg.get('maxChoices', 0)

                    for m_ref in mg.get('modifiers', []) or []:
                        m = mod_sets.get(m_ref)
                        if not m:
                            continue
                        mod_name = m.get('name', '').strip()
                        mod_price = float(m.get('additionPrice', 0.0))
                        key = (gname, mod_name)

                        if key not in seen_mod:
                            seen_mod.add(key)
                            addons_list.append({
                                'group': gname,
                                'name': mod_name,
                                'price': mod_price,
                                'min_choices': min_ch,
                                'max_choices': max_ch
                            })
                            addons_by_group.setdefault(gname, []).append((mod_name, mod_price))

            # Przyjazna tekstowa reprezentacja dodatków
            addons_raw_parts = []
            for gname, m_list in addons_by_group.items():
                opts_str = ", ".join([f"{m[0]} (+{m[1]:.2f} zł)" if m[1] > 0 else m[0] for m in m_list])
                addons_raw_parts.append(f"{gname}: {opts_str}")
            addons_raw = "; ".join(addons_raw_parts)

            # Cechy / Tagi / Badges
            badges = []
            if 'bestseller' in cat_name.lower():
                badges.append('Bestseller')
            for l in it.get('labels', []) or []:
                if l and str(l) not in badges:
                    badges.append(str(l))

            # Oryginalny link do zdjęcia w pełnej rozdzielczości
            img_url = ""
            img_sources = it.get('imageSources', []) or []
            if img_sources and isinstance(img_sources, list) and len(img_sources) > 0:
                raw_path = img_sources[0].get('path', '')
                if raw_path:
                    # Usunięcie {transformations} zwraca oryginalne, nieskompresowane zdjęcie HD z Cloudinary
                    img_url = raw_path.replace('/{transformations}', '')
            elif it.get('imageUrl'):
                img_url = it.get('imageUrl')

            items_out.append({
                'id': item_id,
                'category': cat_name,
                'category_description': cat_desc,
                'name': name,
                'description': desc,
                'price_raw': price_raw,
                'price': price_val,
                'badges': badges,
                'image_url': img_url,
                'variants': variants_list,
                'addons': addons_list,
                'addons_raw': addons_raw,
                'image_filename': ""
            })
            item_counter += 1

    # Budowanie ustrukturyzowanego słownika {Kategoria: [Dania...]} wymaganego przez importer
    menu_dict = build_pyszne_menu_dict(categories, items_map, mod_groups, mod_sets)

    print(f"[+] Pomyślnie sparsowano łącznie {len(items_out)} pozycji menu z Pyszne.pl.")
    return restaurant_meta, items_out, menu_dict


def build_pyszne_menu_dict(categories: list[dict], items_map: dict, mod_groups: dict, mod_sets: dict) -> dict[str, list[dict]]:
    """
    Tworzy słownik menu w formacie { "Kategoria": [ { danie } ] } zgodnie ze specyfikacją importera.
    Obsługuje name, price, description, opcjonalne ingredients oraz popup_details z variants i groups.
    """
    menu_dict = {}

    for cat in categories:
        cat_name = cat.get('name', 'Inne')
        cat_items = []

        for item_id in cat.get('itemIds', []):
            it = items_map.get(item_id)
            if not it:
                continue

            name = it.get('name', '').strip()
            desc = (it.get('description', '') or '').strip()

            variations = it.get('variations', []) or []
            prices = [float(v['basePrice']) for v in variations if v.get('basePrice') is not None]
            base_price = round(min(prices), 2) if prices else 0.0

            dish = {
                'name': name,
                'price': base_price,
                'description': desc
            }

            # Składniki (jeśli występują w opisie w postaci krótkich elementów po przecinku lub plusie)
            if desc:
                parts = [p.strip().rstrip('.') for p in re.split(r'[,+;]', desc) if p.strip()]
                # Sprawdzamy czy to lista składników (krótkie elementy bez zdań opisowych)
                if len(parts) >= 2 and all(len(p) <= 35 for p in parts) and not any(p.lower().startswith(('kawałki', 'aromatyczny', 'klasyczna', 'tradycyjne', 'intensywne', 'pyszne', 'kremowy', 'gazowany')) for p in parts[:1]):
                    dish['ingredients'] = parts

            has_multi_variations = len(variations) > 1 or (
                len(variations) == 1 and variations[0].get('type') != 'NoVariation' and variations[0].get('name') != name
            )

            has_any_groups = any(bool(v.get('modifierGroupsIds')) for v in variations)

            if has_multi_variations or has_any_groups:
                variants_list = []

                if has_multi_variations:
                    for v in variations:
                        v_label = v.get('name', '').strip()
                        v_price = round(float(v.get('basePrice', base_price)), 2)
                        v_groups = []

                        for mg_id in v.get('modifierGroupsIds', []) or []:
                            mg = mod_groups.get(mg_id)
                            if not mg:
                                continue
                            max_c = mg.get('maxChoices', 1)
                            min_c = mg.get('minChoices', 0)
                            is_single = (max_c == 1)
                            is_req = (min_c >= 1)

                            choices = []
                            for m_ref in mg.get('modifiers', []) or []:
                                m = mod_sets.get(m_ref)
                                if not m:
                                    continue
                                choices.append({
                                    'name': m.get('name', '').strip(),
                                    'price': round(float(m.get('additionPrice', 0.0)), 2)
                                })

                            v_groups.append({
                                'group_name': mg.get('name', 'Dodatki').strip(),
                                'group': 'single_choice_group' if is_single else 'multi_choice_group',
                                'type': 'single' if is_single else 'multi',
                                'required': is_req,
                                'choices': choices
                            })

                        variants_list.append({
                            'label': v_label,
                            'price': v_price,
                            'groups': v_groups
                        })
                else:
                    # Pojedynczy wariant z grupami modyfikatorów -> label: "Domyślny"
                    v = variations[0] if variations else {}
                    v_price = round(float(v.get('basePrice', base_price)), 2)
                    v_groups = []

                    for mg_id in v.get('modifierGroupsIds', []) or []:
                        mg = mod_groups.get(mg_id)
                        if not mg:
                            continue
                        max_c = mg.get('maxChoices', 1)
                        min_c = mg.get('minChoices', 0)
                        is_single = (max_c == 1)
                        is_req = (min_c >= 1)

                        choices = []
                        for m_ref in mg.get('modifiers', []) or []:
                            m = mod_sets.get(m_ref)
                            if not m:
                                continue
                            choices.append({
                                'name': m.get('name', '').strip(),
                                'price': round(float(m.get('additionPrice', 0.0)), 2)
                            })

                        v_groups.append({
                            'group_name': mg.get('name', 'Dodatki').strip(),
                            'group': 'single_choice_group' if is_single else 'multi_choice_group',
                            'type': 'single' if is_single else 'multi',
                            'required': is_req,
                            'choices': choices
                        })

                    variants_list.append({
                        'label': 'Domyślny',
                        'price': v_price,
                        'groups': v_groups
                    })

                dish['popup_details'] = {
                    'variants': variants_list
                }

            cat_items.append(dish)

        menu_dict[cat_name] = cat_items

    return menu_dict


# ==============================================================================
#                      PARSER DLA UPMENU (CZAR SUSHI)
# ==============================================================================

def parse_price(price_str: str) -> float | None:
    if not price_str:
        return None
    cleaned = price_str.replace('\xa0', ' ').replace('zł', '').replace('od', '').strip()
    cleaned = cleaned.replace(',', '.')
    match = re.search(r'([0-9]+\.?[0-9]*)', cleaned)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def fetch_upmenu_site_config(url: str) -> tuple[str, str]:
    default_site_id = "bae30429-f8ce-11ee-8fee-525400080621"
    default_rest_id = "baf3dba1-f8ce-11ee-8fee-525400080621"
    try:
        resp = requests.get(url, headers={'User-Agent': BROWSER_HEADERS['User-Agent']}, timeout=15)
        resp.raise_for_status()
        html = resp.text
        site_id_m = re.search(r"siteId\s*=\s*['\"]([a-f0-9\-]+)['\"]", html)
        rest_id_m = re.search(r"restaurantId\s*=\s*['\"]([a-f0-9\-]+)['\"]", html)
        site_id = site_id_m.group(1) if site_id_m else default_site_id
        rest_id = rest_id_m.group(1) if rest_id_m else default_rest_id
        return site_id, rest_id
    except Exception:
        return default_site_id, default_rest_id


def parse_upmenu_structure(html: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    groups = soup.select('.theme-product-group')
    items = []
    item_counter = 1

    for group in groups:
        group_id = group.get('id', '')
        uuid = group_id.replace('pg-', '')
        group_name_el = group.select_one('.theme-product-group-name')
        category_name = group_name_el.get_text(strip=True) if group_name_el else "Inne"

        prod_list = soup.select_one(f'#product-list-{uuid}')
        if not prod_list:
            continue

        products = prod_list.select('.single-product')
        for prod in products:
            theme_prod = prod.select_one('.theme-product')
            product_id = ""
            if theme_prod:
                product_id = theme_prod.get('data-id', '')
                if not product_id and theme_prod.get('id', '').startswith('p-'):
                    product_id = theme_prod.get('id')[2:]

            name_el = prod.select_one('.theme-product-name')
            name = name_el.get_text(strip=True) if name_el else f"Danie {item_counter}"
            desc_el = prod.select_one('.theme-product-desc')
            desc = desc_el.get_text(strip=True) if desc_el else ""
            price_el = prod.select_one('.theme-price')
            price_raw = price_el.get_text(strip=True) if price_el else ""
            price_val = parse_price(price_raw)

            badges = [b.get_text(strip=True) for b in prod.select('.theme-product-attribute, .badge, .label') if b.get_text(strip=True)]

            img_container = prod.select_one('.product-list-image, .lazy-image, [data-src]')
            img_url = ""
            if img_container and img_container.get('data-src'):
                img_url = img_container.get('data-src').strip()
            else:
                img_tag = prod.select_one('img')
                if img_tag and 'spinner.svg' not in img_tag.get('src', ''):
                    img_url = img_tag.get('src', '').strip()

            items.append({
                'id': product_id,
                'category': category_name,
                'category_description': '',
                'name': name,
                'description': desc,
                'price_raw': price_raw,
                'price': price_val,
                'badges': badges,
                'image_url': img_url,
                'variants': [],
                'addons': [],
                'addons_raw': "",
                'image_filename': ""
            })
            item_counter += 1

    return items


def fetch_upmenu_addons(items: list[dict], site_id: str, rest_id: str, max_workers: int = 10) -> list[dict]:
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    def fetch_item_addons(item: dict) -> dict:
        pid = item.get('id')
        if not pid:
            return item
        url = f"https://www.czarsushi.pl/restapi/buyingFlow/startByProduct/{site_id}/{rest_id}/{pid}?cartId="
        try:
            resp = session.post(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                variants_list = [{'name': t.get('name'), 'price': t.get('price')} for t in data.get('types', []) if t.get('name')]
                item['variants'] = variants_list

                addons_list = []
                for s in data.get('steps', []):
                    for sg in s.get('stepGroups', []):
                        gname = sg.get('name', 'Dodatek')
                        for p in sg.get('products', []):
                            if p.get('name'):
                                addons_list.append({
                                    'group': gname,
                                    'name': p.get('name'),
                                    'price': float(p.get('price', 0.0))
                                })
                item['addons'] = addons_list
                if addons_list:
                    item['addons_raw'] = "; ".join([f"{a['name']} (+{a['price']:.2f} zł)" if a['price'] > 0 else a['name'] for a in addons_list])
        except Exception:
            pass
        return item

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_item_addons, item) for item in items]
        for f in as_completed(futures):
            f.result()
    return items


# ==============================================================================
#                      PARSER DLA GLOVO (GLOVOAPP.COM)
# ==============================================================================

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


def extract_rsc_stream_from_html(html: str) -> str:
    """
    Wyciąga i łączy wszystkie strumienie Next.js RSC z wywołań self.__next_f.push.
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
    Parsuje kod strony lokalu na Glovo i wyciąga pełną strukturę menu 1:1, metadane oraz listę dań.
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

            raw_price = p_data.get('price')
            if raw_price is None and isinstance(p_data.get('priceInfo'), dict):
                raw_price = p_data['priceInfo'].get('amount')
            try:
                base_price = round(float(raw_price), 2) if raw_price is not None else 0.0
            except (ValueError, TypeError):
                base_price = 0.0

            raw_img_url = p_data.get('imageUrl') or ''
            hd_img_url = raw_img_url.split('?')[0] if raw_img_url else ''

            attr_groups = p_data.get('attributeGroups', []) or []

            # Weryfikacja grupy wyboru rozmiaru
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

            dish = {
                'name': name,
                'price': base_price,
                'description': desc
            }

            if desc:
                parts = [p.strip().rstrip('.') for p in re.split(r'[,+;]', desc) if p.strip()]
                if len(parts) >= 2 and all(len(p) <= 40 for p in parts) and not any(parts[0].lower().startswith(w) for w in ('kawałki', 'aromatyczny', 'klasyczna', 'tradycyjne', 'intensywne', 'pyszne', 'kremowy', 'gazowany', 'podwójny', 'delikatny', 'chrupiący', 'zamknięte')):
                    dish['ingredients'] = parts

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

            cat_list = menu_dict.setdefault(cat_name, [])
            if not any(d['name'] == dish['name'] and d['price'] == dish['price'] for d in cat_list):
                cat_list.append(dish)

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
    Pobiera pojedyncze zdjęcie i zapisuje je w folderze output_dir z nazwą dania 1:1.
    Używa pamięci podręcznej pobranych bajtów, dzięki czemu różne pozycje z tym samym zdjęciem
    otrzymują własne pliki graficzne bez powielania zapytań sieciowych.
    """
    img_url = item.get('image_url')
    if not img_url:
        return ""

    clean_name = sanitize_filename(item['name'])

    ext = ".jpg"
    lower_url = img_url.lower()
    if ".webp" in lower_url:
        ext = ".webp"
    elif ".png" in lower_url:
        ext = ".png"

    filename = f"{clean_name}{ext}"
    filepath = os.path.join(output_dir, filename)

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
        print(f"[!] Błąd pobierania zdjęcia {img_url} ({e})")

    return ""


def download_all_images(items: list[dict], output_dir: str, max_workers: int = 10):
    """
    Pobiera wszystkie zdjęcia dań równolegle za pomocą puli wątków.
    """
    items_with_images = [item for item in items if item.get('image_url')]
    total_imgs = len(items_with_images)
    print(f"[*] Pobieranie {total_imgs} zdjęć do folderu '{output_dir}' (wątki: {max_workers})...")

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
            if completed % 20 == 0 or completed == total_imgs:
                print(f"    Pobrano zdjęć: {completed}/{total_imgs}")

    saved_count = sum(1 for item in items if item.get('image_filename'))
    print(f"[+] Pobieranie zdjęć zakończone: przypisano {saved_count}/{total_imgs} plików.")


def build_upmenu_menu_dict(items: list[dict]) -> dict[str, list[dict]]:
    """
    Tworzy słownik menu dla UpMenu w formacie { "Kategoria": [ { danie } ] } zgodnie ze specyfikacją importera.
    """
    menu_dict = {}
    for it in items:
        cat_name = it.get('category', 'Inne')
        name = it.get('name', '')
        desc = it.get('description', '')
        price = it.get('price', 0.0) or 0.0

        dish = {
            'name': name,
            'price': price,
            'description': desc
        }
        variants = it.get('variants', [])
        addons = it.get('addons', [])

        if variants or addons:
            variants_list = []
            if variants:
                for v in variants:
                    v_name = v.get('name', 'Domyślny')
                    v_price = float(v.get('price') or price)
                    groups = []
                    if addons:
                        addons_by_g = {}
                        for a in addons:
                            addons_by_g.setdefault(a.get('group', 'Dodatki'), []).append(a)
                        for gname, alist in addons_by_g.items():
                            groups.append({
                                'group_name': gname,
                                'group': 'multi_choice_group',
                                'type': 'multi',
                                'required': False,
                                'choices': [{'name': a['name'], 'price': float(a.get('price', 0.0))} for a in alist]
                            })
                    variants_list.append({
                        'label': v_name,
                        'price': v_price,
                        'groups': groups
                    })
            else:
                groups = []
                addons_by_g = {}
                for a in addons:
                    addons_by_g.setdefault(a.get('group', 'Dodatki'), []).append(a)
                for gname, alist in addons_by_g.items():
                    groups.append({
                        'group_name': gname,
                        'group': 'multi_choice_group',
                        'type': 'multi',
                        'required': False,
                        'choices': [{'name': a['name'], 'price': float(a.get('price', 0.0))} for a in alist]
                    })
                variants_list.append({
                    'label': 'Domyślny',
                    'price': price,
                    'groups': groups
                })

            dish['popup_details'] = {
                'variants': variants_list
            }

        menu_dict.setdefault(cat_name, []).append(dish)
    return menu_dict


def export_to_files(items: list[dict], menu_dict: dict, restaurant_meta: dict, base_dir: str):
    """
    Eksportuje dane menu do formatów: JSON (słownik kategorii), CSV oraz Excel (.xlsx).
    Zapisuje także plik restaurant_info.json z metadanymi lokalu.
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
    print(f"[+] Zapisano (słownik kategorii JSON): {json_path}")

    # Opcjonalny plik menu_flat.json z płaską listą
    flat_json_path = os.path.join(base_dir, "menu_flat.json")
    with open(flat_json_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    # Przygotowanie wierszy tabelarycznych
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


def scrape_restaurant(url: str, output_dir: str, images_dir_name: str, download_imgs: bool, workers: int, lang: str):
    """
    Główna funkcja wykonująca scraping dla podanego adresu URL.
    """
    url = url.strip()
    if not url:
        return

    is_pyszne = 'pyszne.pl' in url or 'takeaway.com' in url or 'just-eat' in url
    is_glovo = 'glovoapp.com' in url or 'glovo' in url
    if is_pyszne:
        platform_name = 'Pyszne.pl'
    elif is_glovo:
        platform_name = 'Glovo'
    else:
        platform_name = 'UpMenu / Czar Sushi'

    print("\n" + "=" * 65)
    print(f"Rozpoczynanie pobierania: {url}")
    print(f"Platforma: {platform_name}")
    print("=" * 65)

    images_dir = os.path.join(output_dir, images_dir_name)

    if is_pyszne:
        html, final_url = fetch_page_html(url, lang=lang)
        restaurant_meta, items, menu_dict = parse_pyszne_menu(html)
        if not items:
            print("[!] Nie znaleziono pozycji w menu dla tego linku.")
            return
    elif is_glovo:
        html, final_url = fetch_page_html(url, lang=lang)
        restaurant_meta, items, menu_dict = parse_glovo_menu(html, final_url)
        if not items:
            print("[!] Nie znaleziono pozycji w menu dla tego linku.")
            return
    else:
        site_id, rest_id = fetch_upmenu_site_config(url)
        menu_api_url = f"https://www.czarsushi.pl/api/v2/menu/{site_id}/{rest_id}"
        resp = requests.get(menu_api_url, headers=BROWSER_HEADERS, timeout=20)
        resp.raise_for_status()
        items = parse_upmenu_structure(resp.text)
        items = fetch_upmenu_addons(items, site_id, rest_id, max_workers=workers)
        menu_dict = build_upmenu_menu_dict(items)
        restaurant_meta = {'name': 'Czar Sushi', 'url': url}

    if download_imgs:
        download_all_images(items, images_dir, max_workers=workers)
    else:
        print("[*] Pominięto pobieranie plików graficznych (--no-images).")

    export_to_files(items, menu_dict, restaurant_meta, output_dir)
    print(f"[✓] Gotowe! Zapisano dane dla: {restaurant_meta.get('name', url)}")


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


def extract_slug_from_url(url: str, default_prefix: str = "restauracja") -> str:
    """
    Wyciąga czytelny slug / nazwę lokalu z adresu URL (dla Glovo, Pyszne.pl i UpMenu).
    """
    slug_match = re.search(r'/(?:menu|stores|store)/([a-zA-Z0-9_\-]+)', url)
    if slug_match:
        return slug_match.group(1)
    clean_path = url.split('?')[0].rstrip('/')
    parts = [p for p in clean_path.split('/') if p]
    if parts:
        return parts[-1]
    return f"{default_prefix}_{int(time.time())}"


def main():
    parser = argparse.ArgumentParser(description="Uniwersalny scraper menu Pyszne.pl, Glovo oraz Czar Sushi")
    parser.add_argument('urls', nargs='*', help="Jeden lub więcej linków do menu restauracji")
    parser.add_argument('--url', action='append', help="Dodatkowy link do menu (można podać wielokrotnie)")
    parser.add_argument('--urls-file', help="Ścieżka do pliku tekstowego z linkami (jeden URL na linię)")
    parser.add_argument('--output-dir', default='.', help="Katalog wyjściowy dla pobranych danych (domyślnie bieżący)")
    parser.add_argument('--images-dir', default='zdjecia', help="Nazwa podfolderu na zdjęcia (domyślnie 'zdjecia')")
    parser.add_argument('--no-images', action='store_true', help="Pomiń pobieranie plików graficznych")
    parser.add_argument('--workers', type=int, default=10, help="Liczba równoległych wątków pobierania (domyślnie 10)")
    parser.add_argument('--lang', choices=['auto', 'pl', 'en'], default='auto', help="Wybór języka menu na Pyszne.pl (domyślnie 'auto')")
    parser.add_argument('--by-restaurant', action='store_true', help="Zapisuj każdy lokal do osobnego podfolderu z nazwą lokalu")
    args = parser.parse_args()

    # Zbieranie linków
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

    # Jeśli nie podano żadnego linku w argumentach, pytamy użytkownika interaktywnie
    if not urls_to_scrape:
        is_interactive = True
        print("\n" + "=" * 65)
        print("        SCRAPER MENU RESTAURACJI (GLOVO / PYSZNE.PL / UPMENU)")
        print("=" * 65)
        print("Wskazówka: Możesz wkleić dowolny link do lokalu (Glovo, Pyszne.pl lub UpMenu).")
        print("=" * 65)

        while True:
            try:
                user_input = input("\n🔗 Wklej link do restauracji:\n(Naciśnij Enter, aby użyć domyślnego linku Pyszne.pl)\n> ").strip()
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
                print(f"[*] Wybrano domyślny link: {DEFAULT_PYSZNE_URL}")
                urls_to_scrape.append(DEFAULT_PYSZNE_URL)
                break

    print("\n" + "=" * 65)
    print("        SCRAPER MENU RESTAURACJI (PYSZNE.PL / GLOVO / UPMENU)")
    print(f" Liczba linków do przetworzenia: {len(urls_to_scrape)}")
    print("=" * 65)

    base_output_dir = os.path.abspath(args.output_dir)

    for i, url in enumerate(urls_to_scrape, 1):
        if len(urls_to_scrape) > 1 or args.by_restaurant:
            sub_name = extract_slug_from_url(url, f"restauracja_{i}")
            curr_output_dir = os.path.join(base_output_dir, sub_name)
        else:
            curr_output_dir = base_output_dir

        scrape_restaurant(
            url=url,
            output_dir=curr_output_dir,
            images_dir_name=args.images_dir,
            download_imgs=not args.no_images,
            workers=args.workers,
            lang=args.lang
        )

    # W trybie interaktywnym pytamy o kolejne lokale
    if is_interactive:
        while True:
            try:
                next_input = input("\n🔗 Wklej kolejny link do lokalu (lub naciśnij Enter, aby zakończyć):\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not next_input:
                break

            next_url = normalize_url(next_input)
            if next_url:
                sub_name = extract_slug_from_url(next_url, f"restauracja_{int(time.time())}")
                curr_output_dir = os.path.join(base_output_dir, sub_name)

                scrape_restaurant(
                    url=next_url,
                    output_dir=curr_output_dir,
                    images_dir_name=args.images_dir,
                    download_imgs=not args.no_images,
                    workers=args.workers,
                    lang=args.lang
                )

    print("\n" + "=" * 65)
    print("[✓] Wszystkie wskazane restauracje zostały pomyślnie przetworzone!")
    print("=" * 65)


if __name__ == '__main__':
    main()
