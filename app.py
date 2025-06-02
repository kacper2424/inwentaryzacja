import streamlit as st
import pandas as pd
import io
from streamlit_camera_input_live import camera_input_live
import cv2
import numpy as np

# === Funkcja kolorująca różnicę tylko w kolumnie 'różnica' ===
def highlight_diff(val):
    if val < 0:
        return 'color: red'
    elif val > 0:
        return 'color: blue'
    else:
        return ''

# === Wczytaj dane z Excela ===
@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = [col.lower().strip() for col in df.columns]
    required_cols = {'model', 'stan'}
    if not required_cols.issubset(df.columns):
        raise ValueError("Plik musi zawierać kolumny: model i stan")
    df = df[['model', 'stan']]
    df['model'] = df['model'].astype(str).str.strip()
    return df

st.title("📦 Inwentaryzacja sprzętu")

uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])

if uploaded_file:
    try:
        stany_magazynowe = load_data(uploaded_file)
    except Exception as e:
        st.error(f"Błąd wczytywania pliku: {e}")
        st.stop()

    if "zeskanowane" not in st.session_state:
        st.session_state.zeskanowane = {}

    if "input_model" not in st.session_state:
        st.session_state.input_model = ""

    def scan_model():
        model = st.session_state.input_model.strip()
        if model:
            st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1
            st.session_state.input_model = ""

    # Pole tekstowe do skanowania lub wpisywania
    st.text_input(
        "Zeskanuj kod modelu (lub wpisz ręcznie i naciśnij Enter)",
        key="input_model",
        on_change=scan_model
    )

    # 📷 Skanowanie kamerą – opcjonalne
    with st.expander("📷 Skanuj kod QR kamerą"):
        img = camera_input_live()
        if img:
            bytes_data = img.getvalue()
            img_array = np.frombuffer(bytes_data, np.uint8)
            image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            detector = cv2.QRCodeDetector()
            data, bbox, _ = detector.detectAndDecode(image)
            if data:
                model = data.strip()
                st.success(f"Zeskanowano: {model}")
                st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1
            else:
                st.warning("Nie udało się odczytać kodu QR.")

    # 🗑️ Przycisk czyszczenia
    if st.button("🗑️ Wyczyść wszystkie skany"):
        st.session_state.zeskanowane = {}
        st.rerun()

    # 🔄 Porównanie skanów ze stanem
    df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
    df_pelne = stany_magazynowe.merge(df_skan, on="model", how="outer").fillna(0)

    # Filtracja pustych modeli
    df_pelne["model"] = df_pelne["model"].astype(str).str.strip()
    df_pelne = df_pelne[(df_pelne["model"] != "nan") & (df_pelne["model"] != "")]

    df_pelne["zeskanowano"] = df_pelne["zeskanowano"].astype(int)
    df_pelne["stan"] = df_pelne["stan"].astype(int)
    df_pelne["różnica"] = df_pelne["zeskanowano"] - df_pelne["stan"]

    st.subheader("📊 Porównanie stanów")
    st.dataframe(df_pelne.style.applymap(highlight_diff, subset=["różnica"]))

    # 📥 Eksport do Excela
    excel_buffer = io.BytesIO()
    df_pelne.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)

    st.download_button(
        label="📥 Pobierz raport różnic (Excel)",
        data=excel_buffer,
        file_name="raport_inwentaryzacja.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
