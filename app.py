import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO
from datetime import time

from intraday_module import obter_dados_intraday, identificar_trades_intraday

st.set_page_config(page_title="Análise de Trades", layout="wide", page_icon="📈")

# ---------------------------------------------------------------------------
# Funções de análise diária (módulo original)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def obter_dados(ticker: str, inicio: str, fim: str) -> pd.DataFrame:
    dados = yf.download(ticker, start=inicio, end=fim, progress=False)
    if isinstance(dados.columns, pd.MultiIndex):
        dados.columns = dados.columns.get_level_values(0)
    return dados


def calcular_estatisticas_trades(trades):
    ganhos = [t for t in trades if t > 0]
    perdas = [t for t in trades if t < 0]
    ganho_maximo = max(ganhos) if ganhos else 0
    media_ganhos = sum(ganhos) / len(ganhos) if ganhos else 0
    perda_maxima = min(perdas) if perdas else 0
    media_perdas = sum(perdas) / len(perdas) if perdas else 0
    return ganho_maximo, perda_maxima, media_ganhos, media_perdas


def identificar_trades(tickers, inicio, fim, percentual_queda):
    fator = 1 - (percentual_queda / 100)
    trades_totais = []
    historico_trades = []
    erros = []

    for ticker in tickers:
        try:
            dados = obter_dados(ticker, inicio, fim)
        except Exception as e:
            erros.append(f"{ticker}: {e}")
            continue

        if dados.empty or "Close" not in dados or "Low" not in dados:
            erros.append(f"{ticker}: sem dados no período informado")
            continue

        acumulado = 0.0
        trades_com_lucro = 0
        trades_totais_ticker = 0
        lista_lucros = []

        for i in range(1, len(dados)):
            preco_anterior = float(dados["Close"].iloc[i - 1])
            preco_atual = float(dados["Close"].iloc[i])
            preco_minimo_atual = float(dados["Low"].iloc[i])
            data_entrada = dados.index[i - 1]
            data_saida = dados.index[i]

            if preco_minimo_atual < preco_anterior * fator:
                preco_entrada = round(preco_anterior * fator, 2)
                preco_saida = round(preco_atual, 2)
                lucro = preco_saida - preco_entrada
                acumulado += lucro
                lista_lucros.append(lucro)
                trades_totais_ticker += 1
                if lucro > 0:
                    trades_com_lucro += 1

                historico_trades.append({
                    "Ticker": ticker,
                    "Data de Entrada": data_entrada,
                    "Data de Saída": data_saida,
                    "Preço de Entrada": preco_entrada,
                    "Preço de Saída": preco_saida,
                    "Lucro/Prejuízo": round(lucro, 2),
                })

        probabilidade_acerto = (trades_com_lucro / trades_totais_ticker) if trades_totais_ticker > 0 else 0
        ganho_maximo, perda_maxima, media_ganhos, media_perdas = calcular_estatisticas_trades(lista_lucros)

        trades_totais.append({
            "Ticker": ticker,
            "Probabilidade de Acerto": round(probabilidade_acerto * 100, 1),
            "Valor Acumulado": round(acumulado, 2),
            "Trades Totais": trades_totais_ticker,
            "Ganho Máximo": round(ganho_maximo, 2),
            "Perda Máxima": round(perda_maxima, 2),
            "Média de Ganhos": round(media_ganhos, 2),
            "Média de Perdas": round(media_perdas, 2),
        })

    df_resultado = pd.DataFrame(trades_totais)
    if historico_trades:
        df_historico = pd.DataFrame(historico_trades)
        for col in ["Data de Entrada", "Data de Saída"]:
            if pd.api.types.is_datetime64tz_dtype(df_historico[col]):
                df_historico[col] = df_historico[col].dt.tz_localize(None)
    else:
        df_historico = pd.DataFrame()

    return df_resultado, df_historico, erros


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    return buffer.getvalue()


def normalizar_tickers(tickers, mercado_b3: bool):
    if mercado_b3:
        return [t if "." in t else f"{t}.SA" for t in tickers]
    return tickers


def renderiza_comparativo(df_resultado, df_historico, erros, col_data_entrada, col_data_saida, prefixo):
    """Bloco de dashboard reutilizado pelas duas abas."""
    if erros:
        with st.expander(f"⚠️ {len(erros)} aviso(s)"):
            for e in erros:
                st.write("-", e)

    if df_resultado.empty:
        st.warning("Nenhum resultado gerado.")
        return

    st.subheader("Comparativo entre ações")
    ordenar_por = st.selectbox(
        "Ordenar tabela por",
        ["Valor Acumulado", "Probabilidade de Acerto", "Trades Totais", "Ganho Máximo"],
        key=f"{prefixo}_ordenar",
    )
    df_ordenado = df_resultado.sort_values(ordenar_por, ascending=False)
    st.dataframe(df_ordenado, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        fig_barra = px.bar(
            df_ordenado, x="Ticker", y="Valor Acumulado",
            color="Valor Acumulado", color_continuous_scale="RdYlGn",
            title="Valor Acumulado por Ticker",
        )
        st.plotly_chart(fig_barra, use_container_width=True)
    with c2:
        fig_disp = px.scatter(
            df_resultado, x="Probabilidade de Acerto", y="Valor Acumulado",
            size="Trades Totais", color="Ticker", text="Ticker",
            title="Probabilidade de Acerto x Valor Acumulado",
        )
        fig_disp.update_traces(textposition="top center")
        st.plotly_chart(fig_disp, use_container_width=True)

    st.divider()
    st.subheader("Detalhe por ticker")
    ticker_sel = st.selectbox("Escolha um ticker", df_resultado["Ticker"].tolist(), key=f"{prefixo}_ticker_sel")

    hist_ticker = df_historico[df_historico["Ticker"] == ticker_sel].sort_values(col_data_entrada)
    if not hist_ticker.empty:
        hist_ticker = hist_ticker.copy()
        hist_ticker["Acumulado"] = hist_ticker["Lucro/Prejuízo"].cumsum()

        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(
            x=hist_ticker[col_data_saida], y=hist_ticker["Acumulado"],
            mode="lines+markers", name="Resultado acumulado",
        ))
        fig_equity.update_layout(title=f"Curva de resultado — {ticker_sel}")
        st.plotly_chart(fig_equity, use_container_width=True)

        st.dataframe(hist_ticker.drop(columns=["Acumulado"]), use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum trade encontrado para esse ticker no período.")

    st.divider()
    cd1, cd2 = st.columns(2)
    with cd1:
        st.download_button(
            "⬇️ Baixar resultado consolidado (Excel)",
            data=to_excel_bytes(df_resultado),
            file_name=f"resultado_trades_{prefixo}.xlsx",
            use_container_width=True,
            key=f"{prefixo}_download_resultado",
        )
    with cd2:
        st.download_button(
            "⬇️ Baixar histórico detalhado (Excel)",
            data=to_excel_bytes(df_historico) if not df_historico.empty else b"",
            file_name=f"historico_trades_{prefixo}.xlsx",
            disabled=df_historico.empty,
            use_container_width=True,
            key=f"{prefixo}_download_historico",
        )


# ---------------------------------------------------------------------------
# Sidebar — fonte de tickers, compartilhada pelas duas abas
# ---------------------------------------------------------------------------

st.title("📈 Análise de Trades")

with st.sidebar:
    st.header("Tickers")

    fonte = st.radio(
        "Como informar os tickers?",
        ["Usar arquivo do repositório (acoes_b3.csv)", "Upload de CSV/Excel", "Digitar manualmente"],
    )
    tickers = []

    if fonte == "Usar arquivo do repositório (acoes_b3.csv)":
        try:
            planilha = pd.read_csv("acoes_b3.csv")
            col_ticker = "Ticker" if "Ticker" in planilha.columns else planilha.columns[0]
            tickers = planilha[col_ticker].dropna().astype(str).tolist()
            st.success(f"{len(tickers)} tickers carregados de acoes_b3.csv")
        except FileNotFoundError:
            st.error("Arquivo acoes_b3.csv não encontrado no repositório.")
    elif fonte == "Upload de CSV/Excel":
        arquivo = st.file_uploader("Arquivo com coluna 'Ticker'", type=["csv", "xlsx"])
        if arquivo is not None:
            if arquivo.name.endswith(".csv"):
                planilha = pd.read_csv(arquivo)
            else:
                planilha = pd.read_excel(arquivo)
            col_ticker = "Ticker" if "Ticker" in planilha.columns else planilha.columns[0]
            tickers = planilha[col_ticker].dropna().astype(str).tolist()
            st.success(f"{len(tickers)} tickers carregados.")
    else:
        texto = st.text_area("Um ticker por linha (ex: PETR4.SA)", height=150)
        tickers = [t.strip() for t in texto.splitlines() if t.strip()]

    st.divider()
    mercado = st.radio(
        "Mercado dos tickers",
        ["B3 (Brasil) — adicionar .SA automaticamente", "Já incluo o sufixo / mercado internacional"],
    )
    mercado_b3 = mercado.startswith("B3")

# ---------------------------------------------------------------------------
# Abas
# ---------------------------------------------------------------------------

tab_diario, tab_intraday = st.tabs(["📅 Diário (Swing)", "⏱️ Intraday (15 min)"])

# ===================== ABA 1 — DIÁRIO =====================
with tab_diario:
    st.caption("Estratégia original: entra quando a mínima do dia cai X% abaixo do fechamento anterior, fecha no fechamento do dia seguinte.")

    with st.expander("⚙️ Configuração da análise diária", expanded=True):
        percentual = st.number_input(
            "Percentual de queda para gatilho (%)",
            min_value=0.1, max_value=20.0, value=1.5, step=0.1,
            help="Entra quando a mínima do dia fica abaixo de (100% - esse percentual) do fechamento anterior.",
            key="diario_percentual",
        )
        col1, col2 = st.columns(2)
        with col1:
            data_inicio = st.date_input("Data início", value=pd.to_datetime("2026-01-01"), key="diario_inicio")
        with col2:
            data_fim = st.date_input("Data fim", value=pd.to_datetime("today"), key="diario_fim")

        rodar_diario = st.button("🚀 Rodar Análise Diária", type="primary", use_container_width=True, key="diario_rodar")

    if rodar_diario:
        if not tickers:
            st.error("Informe ao menos um ticker na barra lateral.")
            st.stop()
        if data_inicio >= data_fim:
            st.error("A data de início precisa ser anterior à data de fim.")
            st.stop()

        tickers_normalizados = normalizar_tickers(tickers, mercado_b3)
        with st.spinner(f"Baixando e analisando {len(tickers_normalizados)} ticker(s)..."):
            df_r, df_h, erros = identificar_trades(tickers_normalizados, str(data_inicio), str(data_fim), percentual)

        st.session_state["diario_df_resultado"] = df_r
        st.session_state["diario_df_historico"] = df_h
        st.session_state["diario_erros"] = erros

    if "diario_df_resultado" in st.session_state:
        renderiza_comparativo(
            st.session_state["diario_df_resultado"],
            st.session_state["diario_df_historico"],
            st.session_state["diario_erros"],
            col_data_entrada="Data de Entrada",
            col_data_saida="Data de Saída",
            prefixo="diario",
        )
    else:
        st.info("Configure os parâmetros acima e clique em **Rodar Análise Diária**.")

# ===================== ABA 2 — INTRADAY =====================
with tab_intraday:
    st.caption(
        "Analisa candles de 15 minutos dentro do próprio pregão. "
        "O Yahoo Finance limita o histórico intraday de 15m a aprox. 60 dias corridos."
    )

    with st.expander("⚙️ Configuração da análise intraday", expanded=True):
        dias = st.slider(
            "Quantos dias corridos analisar (máx. 60, limite do Yahoo Finance)",
            min_value=1, max_value=60, value=15, key="intraday_dias",
        )

        direcao_label = st.radio(
            "O que você quer fazer?",
            ["Comprar quando o preço cai X%", "Vender quando o preço sobe X%"],
            key="intraday_direcao",
        )
        direcao = "compra" if direcao_label.startswith("Comprar") else "venda"

        tipo_gatilho_label = st.radio(
            "Em relação a que o percentual é calculado?",
            [
                "Fechamento do dia anterior (mesma lógica do diário, mas monitorando o dia inteiro em candles de 15min)",
                "Um horário específico do dia (ex: preço às 10:00)",
            ],
            key="intraday_tipo_gatilho",
        )
        tipo_gatilho = "fechamento_anterior" if tipo_gatilho_label.startswith("Fechamento") else "horario_especifico"

        horario_referencia = None
        if tipo_gatilho == "horario_especifico":
            horario_referencia = st.time_input(
                "Horário de referência", value=time(10, 0), key="intraday_horario_ref"
            )

        percentual_gatilho = st.number_input(
            "Percentual do gatilho de entrada (%)",
            min_value=0.1, max_value=20.0, value=1.0, step=0.1, key="intraday_pct_entrada",
        )

        regra_saida_label = st.radio(
            "Quando fechar a operação?",
            [
                "Apenas no fim do dia (fecha no último candle do pregão)",
                "No fim do dia OU ao atingir um percentual de saída (o que vier primeiro)",
            ],
            key="intraday_regra_saida",
        )
        regra_saida = "fim_dia" if regra_saida_label.startswith("Apenas") else "percentual"

        percentual_saida = 0.0
        if regra_saida == "percentual":
            percentual_saida = st.number_input(
                "Percentual de saída (alvo de lucro a partir do preço de entrada, %)",
                min_value=0.1, max_value=50.0, value=2.0, step=0.1, key="intraday_pct_saida",
            )

        rodar_intraday = st.button("🚀 Rodar Análise Intraday", type="primary", use_container_width=True, key="intraday_rodar")

    if rodar_intraday:
        if not tickers:
            st.error("Informe ao menos um ticker na barra lateral.")
            st.stop()

        tickers_normalizados = normalizar_tickers(tickers, mercado_b3)
        with st.spinner(f"Baixando candles de 15min e analisando {len(tickers_normalizados)} ticker(s)..."):
            df_r, df_h, erros = identificar_trades_intraday(
                tickers_normalizados,
                dias=dias,
                direcao=direcao,
                tipo_gatilho=tipo_gatilho,
                horario_referencia=horario_referencia,
                percentual_gatilho=percentual_gatilho,
                regra_saida=regra_saida,
                percentual_saida=percentual_saida,
            )

        st.session_state["intraday_df_resultado"] = df_r
        st.session_state["intraday_df_historico"] = df_h
        st.session_state["intraday_erros"] = erros

    if "intraday_df_resultado" in st.session_state:
        renderiza_comparativo(
            st.session_state["intraday_df_resultado"],
            st.session_state["intraday_df_historico"],
            st.session_state["intraday_erros"],
            col_data_entrada="Horário Entrada",
            col_data_saida="Horário Saída",
            prefixo="intraday",
        )
    else:
        st.info("Configure os parâmetros acima e clique em **Rodar Análise Intraday**.")
