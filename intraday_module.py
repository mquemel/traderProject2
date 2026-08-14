"""
Módulo de análise intraday (15 minutos).
Separado do módulo diário — mesma ideia de gatilho por percentual,
mas aplicada dentro do pregão, com referência e saída configuráveis.
"""

import pandas as pd
import yfinance as yf
import streamlit as st


@st.cache_data(show_spinner=False, ttl=900)
def obter_dados_intraday(ticker: str, dias: int) -> pd.DataFrame:
    """Baixa candles de 15 minutos. O Yahoo Finance limita histórico
    intraday de 15m a aproximadamente 60 dias corridos."""
    dados = yf.download(ticker, period=f"{dias}d", interval="15m", progress=False)
    if isinstance(dados.columns, pd.MultiIndex):
        dados.columns = dados.columns.get_level_values(0)
    return dados


def _estatisticas(trades):
    ganhos = [t for t in trades if t > 0]
    perdas = [t for t in trades if t < 0]
    ganho_maximo = max(ganhos) if ganhos else 0
    media_ganhos = sum(ganhos) / len(ganhos) if ganhos else 0
    perda_maxima = min(perdas) if perdas else 0
    media_perdas = sum(perdas) / len(perdas) if perdas else 0
    return ganho_maximo, perda_maxima, media_ganhos, media_perdas


def identificar_trades_intraday(
    tickers,
    dias: int,
    direcao: str,             # "compra" ou "venda"
    tipo_gatilho: str,        # "fechamento_anterior" ou "horario_especifico"
    horario_referencia,       # datetime.time, usado só se tipo_gatilho == "horario_especifico"
    percentual_gatilho: float,
    regra_saida: str,         # "fim_dia" ou "percentual"
    percentual_saida: float,
):
    fator_gatilho = percentual_gatilho / 100
    resultado_geral = []
    historico = []
    erros = []

    for ticker in tickers:
        try:
            dados = obter_dados_intraday(ticker, dias)
        except Exception as e:
            erros.append(f"{ticker}: {e}")
            continue

        if dados.empty or "Close" not in dados:
            erros.append(f"{ticker}: sem dados intraday no período")
            continue

        dados = dados.copy()
        dados["Dia"] = dados.index.date
        dias_unicos = sorted(dados["Dia"].unique())

        lista_lucros = []
        trades_ticker = 0
        trades_lucro = 0
        acumulado = 0.0

        for idx_dia, dia in enumerate(dias_unicos):
            barras_dia = dados[dados["Dia"] == dia]

            # Define o preço de referência e a partir de que ponto do dia observar
            if tipo_gatilho == "fechamento_anterior":
                if idx_dia == 0:
                    continue  # não há dia anterior no histórico baixado
                dia_anterior = dias_unicos[idx_dia - 1]
                barras_anterior = dados[dados["Dia"] == dia_anterior]
                preco_referencia = float(barras_anterior["Close"].iloc[-1])
                barras_observar = barras_dia
            else:  # horario_especifico
                barras_ref = barras_dia[barras_dia.index.time <= horario_referencia]
                if barras_ref.empty:
                    continue
                preco_referencia = float(barras_ref["Close"].iloc[-1])
                barras_observar = barras_dia[barras_dia.index.time > horario_referencia]

            if barras_observar.empty:
                continue

            # Procura o primeiro candle que dispara o gatilho de entrada
            entrada_ts = None
            preco_entrada = None
            for ts, row in barras_observar.iterrows():
                if direcao == "compra":
                    limite = preco_referencia * (1 - fator_gatilho)
                    if float(row["Low"]) <= limite:
                        entrada_ts, preco_entrada = ts, round(limite, 2)
                        break
                else:  # venda
                    limite = preco_referencia * (1 + fator_gatilho)
                    if float(row["High"]) >= limite:
                        entrada_ts, preco_entrada = ts, round(limite, 2)
                        break

            if entrada_ts is None:
                continue

            barras_pos_entrada = barras_dia[barras_dia.index > entrada_ts]

            preco_saida = None
            saida_ts = entrada_ts
            if regra_saida == "percentual" and not barras_pos_entrada.empty:
                for ts, row in barras_pos_entrada.iterrows():
                    if direcao == "compra":
                        alvo = preco_entrada * (1 + percentual_saida / 100)
                        if float(row["High"]) >= alvo:
                            preco_saida, saida_ts = round(alvo, 2), ts
                            break
                    else:
                        alvo = preco_entrada * (1 - percentual_saida / 100)
                        if float(row["Low"]) <= alvo:
                            preco_saida, saida_ts = round(alvo, 2), ts
                            break

            if preco_saida is None:
                # não bateu o alvo (ou a regra é "fim do dia"): fecha na última barra do pregão
                saida_ts = barras_dia.index[-1]
                preco_saida = round(float(barras_dia["Close"].iloc[-1]), 2)

            lucro = (preco_saida - preco_entrada) if direcao == "compra" else (preco_entrada - preco_saida)

            acumulado += lucro
            lista_lucros.append(lucro)
            trades_ticker += 1
            if lucro > 0:
                trades_lucro += 1

            historico.append({
                "Ticker": ticker,
                "Dia": dia,
                "Direção": "Compra" if direcao == "compra" else "Venda",
                "Horário Entrada": entrada_ts,
                "Preço Entrada": preco_entrada,
                "Horário Saída": saida_ts,
                "Preço Saída": preco_saida,
                "Lucro/Prejuízo": round(lucro, 2),
            })

        probabilidade = (trades_lucro / trades_ticker * 100) if trades_ticker > 0 else 0
        ganho_max, perda_max, media_ganhos, media_perdas = _estatisticas(lista_lucros)

        resultado_geral.append({
            "Ticker": ticker,
            "Probabilidade de Acerto": round(probabilidade, 1),
            "Valor Acumulado": round(acumulado, 2),
            "Trades Totais": trades_ticker,
            "Ganho Máximo": round(ganho_max, 2),
            "Perda Máxima": round(perda_max, 2),
            "Média de Ganhos": round(media_ganhos, 2),
            "Média de Perdas": round(media_perdas, 2),
        })

    df_resultado = pd.DataFrame(resultado_geral)
    df_historico = pd.DataFrame(historico)
    return df_resultado, df_historico, erros
