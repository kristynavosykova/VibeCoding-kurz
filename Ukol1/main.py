"""
Ukázka volání LLM API (Claude) s použitím nástroje (tool use).

Jak to funguje krok za krokem:
  1. Pošleme modelu dotaz + seznam nástrojů, které smí použít.
  2. Model se rozhodne, že na odpověď potřebuje nástroj -> vrátí blok "tool_use"
     s názvem nástroje a vstupními parametry (a odpověď skončí se stop_reason="tool_use").
  3. My nástroj spustíme LOKÁLNĚ v Pythonu (model sám nic nespouští).
  4. Výsledek pošleme modelu zpět jako blok "tool_result".
  5. Model s výsledkem pokračuje a napíše finální odpověď.

Kroky 2-4 se mohou opakovat vícekrát (model si může vyžádat víc výpočtů za sebou),
proto je celé kolem toho smyčka `while`.
"""

import ast
import json
import math
import operator
import os

import anthropic
from dotenv import load_dotenv

# Načte proměnné ze souboru .env (hlavně ANTHROPIC_API_KEY).
# Soubor .env je v .gitignore, takže se klíč nikdy nedostane na GitHub.
load_dotenv()

# Model, který budeme používat. Claude Opus 5 je aktuální nejsilnější model
# pro běžné použití; pro levnější/rychlejší běh lze přepnout na "claude-sonnet-5".
MODEL = "claude-opus-5"


# ---------------------------------------------------------------------------
# 1) DEFINICE NÁSTROJE (co o něm ví model)
# ---------------------------------------------------------------------------
# Model vidí jen tenhle popis - nevidí náš Python kód. Proto musí být
# "description" co nejkonkrétnější: co nástroj dělá a KDY ho má model použít.
# "input_schema" je JSON Schema popisující vstupní parametry.

TOOLS = [
    {
        "name": "kalkulacka",
        "description": (
            "Spočítá matematický výraz a vrátí přesný číselný výsledek. "
            "Použij tento nástroj vždy, když je potřeba cokoliv spočítat - "
            "nepočítej z hlavy. Podporuje +, -, *, /, // (celočíselné dělení), "
            "% (zbytek), ** (mocnina), závorky a funkce sqrt, sin, cos, tan, "
            "log, log10, exp, abs, round, min, max a konstanty pi a e."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vyraz": {
                    "type": "string",
                    "description": (
                        "Matematický výraz v Python syntaxi, "
                        "například '(1500 * 1.21) / 3' nebo 'sqrt(2) ** 8'."
                    ),
                }
            },
            "required": ["vyraz"],
        },
    }
]


# ---------------------------------------------------------------------------
# 2) IMPLEMENTACE NÁSTROJE (co nástroj opravdu dělá)
# ---------------------------------------------------------------------------
# Pozor: výraz přichází od modelu, takže je to NEDŮVĚRYHODNÝ vstup.
# Nikdy nepoužíváme obyčejné eval() - to by umožnilo spustit libovolný kód.
# Místo toho výraz rozparsujeme do stromu (ast) a povolíme jen bezpečné uzly.

# Povolené matematické operace
_OPERACE = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,  # unární mínus, např. -5
    ast.UAdd: operator.pos,  # unární plus, např. +5
}

# Povolené funkce a konstanty
_FUNKCE = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}
_KONSTANTY = {"pi": math.pi, "e": math.e}


def _vyhodnot_uzel(uzel):
    """Rekurzivně vyhodnotí jeden uzel syntaktického stromu."""
    if isinstance(uzel, ast.Constant):  # číslo, např. 42
        if isinstance(uzel.value, (int, float)):
            return uzel.value
        raise ValueError("Povolena jsou pouze čísla.")

    if isinstance(uzel, ast.BinOp):  # binární operace, např. a + b
        operace = _OPERACE.get(type(uzel.op))
        if operace is None:
            raise ValueError("Nepodporovaná operace.")
        return operace(_vyhodnot_uzel(uzel.left), _vyhodnot_uzel(uzel.right))

    if isinstance(uzel, ast.UnaryOp):  # unární operace, např. -a
        operace = _OPERACE.get(type(uzel.op))
        if operace is None:
            raise ValueError("Nepodporovaná operace.")
        return operace(_vyhodnot_uzel(uzel.operand))

    if isinstance(uzel, ast.Name):  # konstanta pi / e
        if uzel.id in _KONSTANTY:
            return _KONSTANTY[uzel.id]
        raise ValueError(f"Neznámý název: {uzel.id}")

    if isinstance(uzel, ast.Call):  # volání funkce, např. sqrt(2)
        if not isinstance(uzel.func, ast.Name) or uzel.func.id not in _FUNKCE:
            raise ValueError("Povolené jsou pouze vyjmenované matematické funkce.")
        argumenty = [_vyhodnot_uzel(arg) for arg in uzel.args]
        return _FUNKCE[uzel.func.id](*argumenty)

    raise ValueError("Výraz obsahuje nepovolenou konstrukci.")


def kalkulacka(vyraz: str) -> str:
    """Bezpečně spočítá matematický výraz a vrátí výsledek jako text."""
    strom = ast.parse(vyraz, mode="eval")
    vysledek = _vyhodnot_uzel(strom.body)
    return str(vysledek)


# Mapa: název nástroje (jak ho zná model) -> Python funkce, která ho provede.
# Když přidáš další nástroj, stačí ho dopsat do TOOLS a sem.
IMPLEMENTACE = {
    "kalkulacka": kalkulacka,
}


def spust_nastroj(nazev: str, vstup: dict) -> tuple[str, bool]:
    """
    Spustí nástroj podle jeho názvu.

    Vrací dvojici (text_vysledku, je_chyba).
    Když nástroj spadne, chybu NEZAMLČÍME - pošleme ji modelu jako výsledek
    s příznakem is_error=True. Model pak může zkusit jiný postup.
    """
    funkce = IMPLEMENTACE.get(nazev)
    if funkce is None:
        return f"Neznámý nástroj: {nazev}", True

    try:
        return funkce(**vstup), False
    except Exception as chyba:  # noqa: BLE001 - chceme zachytit cokoliv
        return f"Chyba při spuštění nástroje: {chyba}", True


# ---------------------------------------------------------------------------
# 3) HLAVNÍ SMYČKA - konverzace s modelem
# ---------------------------------------------------------------------------


def zeptej_se(client: anthropic.Anthropic, dotaz: str, max_kol: int = 10) -> str:
    """
    Pošle dotaz modelu a dokola obsluhuje volání nástrojů,
    dokud model nevrátí finální textovou odpověď.

    `max_kol` je pojistka proti nekonečné smyčce.
    """
    # Historie konverzace. API je bezstavové - při každém volání posíláme
    # celou historii znovu.
    zpravy = [{"role": "user", "content": dotaz}]

    for _ in range(max_kol):
        odpoved = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=(
                "Jsi pečlivý asistent. Pro jakýkoliv výpočet vždy použij nástroj "
                "kalkulacka, nikdy nepočítej zpaměti. Odpovídej česky a stručně."
            ),
            tools=TOOLS,
            messages=zpravy,
        )

        # Model si vyžádal nástroj? Pak stop_reason == "tool_use".
        if odpoved.stop_reason != "tool_use":
            # Žádný nástroj -> tohle je finální odpověď.
            # Obsah je seznam bloků, vytáhneme z něj jen textové části.
            return "\n".join(
                blok.text for blok in odpoved.content if blok.type == "text"
            )

        # Celou odpověď modelu (včetně bloků tool_use) přidáme do historie.
        # Důležité: musíme přidat CELÝ obsah, ne jen text - jinak by se
        # blok tool_use ztratil a API by následný tool_result odmítlo.
        zpravy.append({"role": "assistant", "content": odpoved.content})

        # V jedné odpovědi může být i více požadavků na nástroje najednou.
        # Všechny výsledky musíme poslat zpět v JEDNÉ zprávě role "user".
        vysledky = []
        for blok in odpoved.content:
            if blok.type != "tool_use":
                continue

            print(f"  [nástroj] {blok.name}({json.dumps(blok.input, ensure_ascii=False)})")
            text, je_chyba = spust_nastroj(blok.name, blok.input)
            print(f"  [výsledek] {text}")

            vysledky.append(
                {
                    "type": "tool_result",
                    # tool_use_id musí přesně odpovídat id z bloku tool_use,
                    # aby model věděl, ke kterému požadavku výsledek patří.
                    "tool_use_id": blok.id,
                    "content": text,
                    "is_error": je_chyba,
                }
            )

        zpravy.append({"role": "user", "content": vysledky})

    return "Model nedokončil odpověď ani po maximálním počtu kol."


def main() -> None:
    # Kontrola API klíče hned na začátku - ať uživatel nedostane
    # nesrozumitelnou chybu až uprostřed volání.
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "Chybí API klíč. Zkopíruj .env.example do .env "
            "a doplň svůj ANTHROPIC_API_KEY."
        )

    # Klient si klíč sám načte z proměnné prostředí ANTHROPIC_API_KEY.
    # Klíč tedy NIKDY nepíšeme přímo do kódu.
    client = anthropic.Anthropic()

    dotaz = (
        "Kolik je 1499 Kč bez DPH s 21% DPH? "
        "A kolik je odmocnina z toho výsledku zaokrouhlená na 2 desetinná místa?"
    )

    print(f"Dotaz: {dotaz}\n")
    print(f"Odpověď:\n{zeptej_se(client, dotaz)}")


if __name__ == "__main__":
    main()
