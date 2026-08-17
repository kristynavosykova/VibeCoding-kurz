# Úkol 1 — LLM API s voláním nástroje (tool use)

Python skript, který zavolá Claude API, model si vyžádá spuštění nástroje
(bezpečné kalkulačky), skript nástroj spustí lokálně a výsledek pošle modelu
zpět, aby mohl dokončit odpověď.

## Jak to funguje

```
uživatel → [ dotaz + seznam nástrojů ] → model
model    → "chci spustit kalkulacka('1499 * 1.21')"   (stop_reason = tool_use)
skript   → spustí funkci v Pythonu → 1813.79
skript   → [ tool_result: 1813.79 ] → model
model    → finální odpověď v češtině
```

Kroky se mohou opakovat — model si může vyžádat i několik výpočtů za sebou.
Celá logika je ve funkci `zeptej_se()` v `main.py`.

## Spuštění

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

Nastavení API klíče:

```bash
copy .env.example .env        # Windows (macOS/Linux: cp .env.example .env)
```

Do souboru `.env` doplň svůj klíč z <https://console.anthropic.com/settings/keys>.

```bash
python main.py
```

> Pokud se v konzoli na Windows rozsypou české znaky, přepni terminál na UTF-8
> příkazem `chcp 65001`.

## Soubory

| Soubor             | K čemu je                                                   |
| ------------------ | ----------------------------------------------------------- |
| `main.py`          | Celý skript — definice nástroje, jeho implementace a smyčka  |
| `.env.example`     | Šablona pro API klíč (tuhle verzi commitovat lze)            |
| `.env`             | Skutečný klíč — **necommitovat**, je v `.gitignore`          |
| `.gitignore`       | Ignoruje `.env`, `__pycache__`, virtuální prostředí…         |
| `requirements.txt` | Závislosti (`anthropic`, `python-dotenv`)                    |

## Bezpečnost

Výraz pro kalkulačku přichází od modelu, tedy z nedůvěryhodného zdroje.
Proto se **nepoužívá `eval()`** — výraz se rozparsuje pomocí `ast` a povolí se
jen matematické operace a vyjmenované funkce. Cokoliv jiného skončí chybou,
kterou skript pošle modelu zpět jako `is_error: true`.

## Jak přidat vlastní nástroj

1. Přidej popis do seznamu `TOOLS` (název, `description`, `input_schema`).
2. Napiš Python funkci, která nástroj provede.
3. Zaregistruj ji do slovníku `IMPLEMENTACE`.

Zbytek (smyčka, předávání výsledků) funguje beze změny.
