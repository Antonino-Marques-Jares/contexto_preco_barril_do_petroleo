# -*- coding: utf-8 -*-
"""
etl_atualizar_contexto_preco_barril_do_petroleo_no_site.py

ETL que lê a página:
    https://www.areadetrampo.com.br/fatores-geopoliticos-e-o-preco-do-petroleo/
e gera o arquivo:
    JSON/contexto_preco_barril_do_petroleo.json

Estrutura de saída:
{
  "metadados": {
    "data_de_atualizacao": "YYYY-MM-DD",
    "responsavel": "Antonino Marques Jares",
    "nome_programa": "etl_atualizar_contexto_preco_barril_do_petroleo_no_site.py"
  },
  "dados_contexto_barril_do_petroleo": [
    {
      "title": "E1",
      "mes-ano": "10/1973",
      "evento": "...",
      "tipo": "...",
      "impacto_no_preco": "...",
      "contexto": "..."
    },
    ...
  ]
}
"""

import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Configurações
# --------------------------------------------------------------------------- #
URL = "https://www.areadetrampo.com.br/fatores-geopoliticos-e-o-preco-do-petroleo/"
PASTA_SAIDA = "JSON"
ARQUIVO_SAIDA = "contexto_preco_barril_do_petroleo.json"
RESPONSAVEL = "Antonino Marques Jares"
NOME_PROGRAMA = "etl_atualizar_contexto_preco_barril_do_petroleo_no_site.py"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def normalizar_texto(txt: str) -> str:
    if txt is None:
        return ""
    txt = txt.replace("\xa0", " ")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt)
    return txt.strip()


def remover_acentos(txt: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", txt)
        if unicodedata.category(c) != "Mn"
    ).lower()


def chave_cabecalho(txt: str) -> str:
    t = remover_acentos(normalizar_texto(txt))
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# --------------------------------------------------------------------------- #
# Download da página
# --------------------------------------------------------------------------- #
def baixar_pagina(url: str) -> str:
    print(f"[INFO] Baixando página: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


# --------------------------------------------------------------------------- #
# Parsing da tabela
# --------------------------------------------------------------------------- #
COLUNAS_ESPERADAS = ["mes-ano", "evento", "tipo", "impacto no preco", "contexto"]

# Aliases: cabeçalho HTML normalizado -> chave interna
ALIASES_CABECALHO = {
    "mes ano": "mes-ano",
    "mes-ano": "mes-ano",
    "ano": "mes-ano",           # compatibilidade retroativa
    "evento": "evento",
    "tipo": "tipo",
    "impacto no preco": "impacto no preco",
    "contexto": "contexto",
}


def mapear_colunas(cabecalhos):
    mapa = {}
    for idx, cab in enumerate(cabecalhos):
        chave = chave_cabecalho(cab)
        if chave in ALIASES_CABECALHO:
            mapa[idx] = ALIASES_CABECALHO[chave]
            continue
        for alias, campo in ALIASES_CABECALHO.items():
            if alias in chave or chave in alias:
                mapa[idx] = campo
                break
    return mapa


def extrair_tabela_eventos(html: str):
    soup = BeautifulSoup(html, "lxml")

    melhor_tabela = None
    melhor_mapa = None
    melhor_corpo = []
    melhor_header_idx = None

    for tabela in soup.find_all("table"):
        linhas = tabela.find_all("tr")
        if not linhas:
            continue

        # Procura a linha de cabeçalho em QUALQUER linha da tabela
        # (o site não usa <thead>/<th> de forma consistente).
        for h_idx, tr in enumerate(linhas):
            celulas_cab = tr.find_all(["th", "td"])
            if not celulas_cab:
                continue
            cabecalhos = [c.get_text(" ", strip=True) for c in celulas_cab]
            mapa = mapear_colunas(cabecalhos)
            if len(mapa) >= 4:
                # Encontrou cabeçalho válido: dados são as linhas seguintes
                corpo = linhas[h_idx + 1:]
                if len(corpo) > len(melhor_corpo):
                    melhor_tabela = tabela
                    melhor_mapa = mapa
                    melhor_corpo = corpo
                    melhor_header_idx = h_idx
                break  # já achou cabeçalho desta tabela

    if melhor_tabela is None or melhor_header_idx is None:
        raise RuntimeError(
            "Não foi possível localizar a tabela de eventos na página. "
            "Verifique a estrutura HTML do site."
        )

    print(f"[DEBUG] Tabela escolhida: {len(melhor_corpo)} linha(s) de dados, "
          f"cabeçalho na linha {melhor_header_idx}, mapa={melhor_mapa}")

    registros = []
    for tr in melhor_corpo:
        celulas = tr.find_all(["td", "th"])
        if not celulas:
            continue

        registro = {campo: "" for campo in COLUNAS_ESPERADAS}

        for idx, campo in melhor_mapa.items():
            if idx < len(celulas):
                texto = normalizar_texto(celulas[idx].get_text("\n", strip=True))
                registro[campo] = texto

        # Ignora linhas totalmente vazias
        if not any(registro.values()):
            continue

        registros.append({
            "mes-ano": registro.get("mes-ano", ""),
            "evento": registro.get("evento", ""),
            "tipo": registro.get("tipo", ""),
            "impacto_no_preco": registro.get("impacto no preco", ""),
            "contexto": registro.get("contexto", ""),
        })

    # >>> AQUI está o campo "title": E1, E2, E3, ...
    for i, reg in enumerate(registros, start=1):
        reg["title"] = f"E{i}"

    # Coloca "title" como PRIMEIRA chave de cada registro
    registros = [
        {"title": r["title"], **{k: v for k, v in r.items() if k != "title"}}
        for r in registros
    ]

    print(f"[DEBUG] Total de registros com title: {len(registros)}")
    if registros:
        print(f"[DEBUG] Primeiro registro: {registros[0]}")
        print(f"[DEBUG] Último registro:  {registros[-1]}")

    return registros


# --------------------------------------------------------------------------- #
# Montagem e gravação do JSON
# --------------------------------------------------------------------------- #
def montar_json(registros):
    return {
        "metadados": {
            "data_de_atualizacao": date.today().isoformat(),
            "responsavel": RESPONSAVEL,
            "nome_programa": NOME_PROGRAMA,
        },
        "dados_contexto_barril_do_petroleo": registros,
    }


def gravar_json(payload, pasta: str, arquivo: str) -> str:
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, arquivo)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[OK] Arquivo gerado: {caminho}")
    return caminho


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def main() -> int:
    inicio = datetime.now()
    print(f"[INFO] Início: {inicio.isoformat(timespec='seconds')}")

    try:
        html = baixar_pagina(URL)
        registros = extrair_tabela_eventos(html)

        if not registros:
            print("[AVISO] Nenhum registro extraído da tabela.", file=sys.stderr)
            return 1

        print(f"[INFO] Registros extraídos: {len(registros)}")
        payload = montar_json(registros)
        gravar_json(payload, PASTA_SAIDA, ARQUIVO_SAIDA)

    except requests.RequestException as e:
        print(f"[ERRO] Falha de rede ao acessar a página: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[ERRO] {type(e).__name__}: {e}", file=sys.stderr)
        return 3

    fim = datetime.now()
    print(f"[INFO] Concluído em {(fim - inicio).total_seconds():.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
