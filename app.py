import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO

st.set_page_config(page_title="Análise de Trades", layout="wide", page_icon="📈")

# ---------------------------------------------------------------------------
# Funções de análise (adaptadas do script original)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def obter_dados(ticker: str, inicio: str, fim: str) -> pd.DataFrame:
    dados = yf.download(ticker, start=inicio, end=fim, progress=False)
    # yfinance às vezes devolve colunas MultiIndex mesmo para 1 ticker
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
    """percentual_queda: ex. 1.5 significa gatilho quando a mínima do dia
    cai abaixo de 98.5% do fechamento anterior."""
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


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

st.title("📈 Análise de Trades — Reversão de Queda")
st.caption("Baseado na estratégia: entra quando a mínima do dia cai X% abaixo do fechamento anterior.")

with st.sidebar:
    st.header("Configuração")

    fonte = st.radio("Como informar os tickers?", ["Upload de CSV/Excel", "Digitar manualmente"])
    tickers = []

    if fonte == "Upload de CSV/Excel":
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

    percentual = st.number_input(
        "Percentual de queda para gatilho (%)",
        min_value=0.1, max_value=20.0, value=1.5, step=0.1,
        help="Entra quando a mínima do dia fica abaixo de (100% - esse percentual) do fechamento anterior.",
    )

    col1, col2 = st.columns(2)
    with col1:
        data_inicio = st.date_input("Data início", value=pd.to_datetime("2026-01-01"))
    with col2:
        data_fim = st.date_input("Data fim", value=pd.to_datetime("today"))

    rodar = st.button("🚀 Rodar Análise", type="primary", use_container_width=True)

if rodar:
    if not tickers:
        st.error("Informe ao menos um ticker (upload ou manual).")
        st.stop()
    if data_inicio >= data_fim:
        st.error("A data de início precisa ser anterior à data de fim.")
        st.stop()

    with st.spinner(f"Baixando e analisando {len(tickers)} ticker(s)..."):
        df_resultado, df_historico, erros = identificar_trades(
            tickers, str(data_inicio), str(data_fim), percentual
        )

    st.session_state["df_resultado"] = df_resultado
    st.session_state["df_historico"] = df_historico
    st.session_state["erros"] = erros

if "df_resultado" in st.session_state:
    df_resultado = st.session_state["df_resultado"]
    df_historico = st.session_state["df_historico"]
    erros = st.session_state["erros"]

    if erros:
        with st.expander(f"⚠️ {len(erros)} aviso(s)"):
            for e in erros:
                st.write("-", e)

    if df_resultado.empty:
        st.warning("Nenhum resultado gerado.")
    else:
        st.subheader("Comparativo entre ações")

        ordenar_por = st.selectbox(
            "Ordenar tabela por",
            ["Valor Acumulado", "Probabilidade de Acerto", "Trades Totais", "Ganho Máximo"],
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
        ticker_sel = st.selectbox("Escolha um ticker", df_resultado["Ticker"].tolist())

        hist_ticker = df_historico[df_historico["Ticker"] == ticker_sel].sort_values("Data de Entrada")
        if not hist_ticker.empty:
            hist_ticker = hist_ticker.copy()
            hist_ticker["Acumulado"] = hist_ticker["Lucro/Prejuízo"].cumsum()

            fig_equity = go.Figure()
            fig_equity.add_trace(go.Scatter(
                x=hist_ticker["Data de Saída"], y=hist_ticker["Acumulado"],
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
                file_name="resultado_trades.xlsx",
                use_container_width=True,
            )
        with cd2:
            st.download_button(
                "⬇️ Baixar histórico detalhado (Excel)",
                data=to_excel_bytes(df_historico) if not df_historico.empty else b"",
                file_name="historico_trades.xlsx",
                disabled=df_historico.empty,
                use_container_width=True,
            )
else:
    st.info("Configure os tickers, percentual e datas na barra lateral e clique em **Rodar Análise**.")
