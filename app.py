import streamlit as st
import pandas as pd
import io
import uuid

# === Wczytaj dane z Excela ===
@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = [col.lower().strip() for col in df.columns]
    df = df[['model', 'stan']]
    df['model'] = df['model'].astype(str).str.strip()
    return df

st.title("📦 Inwentaryzacja sprzętu")
uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])

if uploaded_file:
    stany_magazynowe = load_data(uploaded_file)

    # Inicjalizacja sesji
    if "zeskanowane" not in st.session_state:
        st.session_state.zeskanowane = {}

    if "input_reset_token" not in st.session_state:
        st.session_state.input_reset_token = str(uuid.uuid4())

    st.success("Plik załadowany poprawnie!")

    # === Skaner kodów (modeli) ===
    input_model = st.text_input(
        "Zeskanuj kod modelu (lub wpisz ręcznie i naciśnij Enter)",
        key="input_" + st.session_state.input_reset_token
    )

    model = input_model.strip()
    if model:
        st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1

        # Reset inputu przez zmianę klucza
        st.session_state.input_reset_token = str(uuid.uuid4())
        st.experimental_rerun()

    # === Porównanie z rzeczywistym stanem ===
    df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])

    df_pelne = stany_magazynowe.merge(df_skan, on="model", how="outer").fillna(0)
    df_pelne["zeskanowano"] = df_pelne["zeskanowano"].astype(int)
    df_pelne["różnica"] = df_pelne["zeskanowano"] - df_pelne["stan"]

    st.subheader("📊 Porównanie stanów")

    # Funkcja podświetlająca wiersze
    def highlight_diff(row):
        if row['różnica'] < 0:
            return ['background-color: #f8d7da'] * len(row)  # jasnoczerwony
        elif row['różnica'] > 0:
            return ['background-color: #cce5ff'] * len(row)  # jasnoniebieski
        else:
            return [''] * len(row)

    st.dataframe(df_pelne.style.apply(highlight_diff, axis=1))

    # === Eksport do Excela ===
    excel_buffer = io.BytesIO()
    df_pelne.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)

    st.download_button(
        label="📥 Pobierz raport różnic (Excel)",
        data=excel_buffer,
        file_name="raport_inwentaryzacja.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
