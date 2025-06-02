import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import io

# === Funkcja kolorująca różnicę tylko w kolumnie 'różnica' ===
def highlight_diff(val):
    if val < 0:
        return 'color: red'
    elif val > 0:
        return 'color: blue'
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

    # Sesja
    if "zeskanowane" not in st.session_state:
        st.session_state.zeskanowane = {}

    if "input_model" not in st.session_state:
        st.session_state.input_model = ""

    if "show_qr" not in st.session_state:
        st.session_state.show_qr = False

    # 📷 Przycisk aparatu obok inputa
    cols = st.columns([4, 1])
    with cols[0]:
        st.text_input(
            "Zeskanuj lub wpisz kod modelu:",
            key="input_model",
            on_change=lambda: scan_model()
        )
    with cols[1]:
        if st.button("📷", use_container_width=True):
            st.session_state.show_qr = not st.session_state.show_qr

    # === Skanowanie z kamery ===
    if st.session_state.show_qr:
        st.info("Włączono kamerę. Zeskanuj kod QR.")
        qr_code_html = """
        <script src="https://unpkg.com/html5-qrcode@2.3.8/minified/html5-qrcode.min.js"></script>
        <div id="reader" style="width: 100%;"></div>
        <script>
          const html5QrCode = new Html5Qrcode("reader");
          html5QrCode.start(
            { facingMode: "environment" },
            { fps: 10, qrbox: { width: 250, height: 250 } },
            (decodedText) => {
              const input = window.parent.document.querySelector('input[data-testid="stTextInput"]');
              if (input) {
                input.value = decodedText;
                input.dispatchEvent(new Event('input', { bubbles: true }));
              }
            }
          );
        </script>
        """
        components.html(qr_code_html, height=400)

    # === Obsługa modelu ===
    def scan_model():
        model = st.session_state.input_model.strip()
        if model:
            st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1
            st.session_state.input_model = ""

    # Przycisk do resetu
    if st.button("🗑️ Wyczyść wszystkie skany"):
        st.session_state.zeskanowane = {}
        st.rerun()

    # Porównanie i raport
    df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
    df_pelne = stany_magazynowe.merge(df_skan, on="model", how="outer").fillna(0)

    # Usuń puste modele
    df_pelne["model"] = df_pelne["model"].astype(str).str.strip()
    df_pelne = df_pelne[df_pelne["model"] != ""]
    df_pelne = df_pelne[df_pelne["model"].str.lower() != "nan"]

    df_pelne["stan"] = df_pelne["stan"].astype(int)
    df_pelne["zeskanowano"] = df_pelne["zeskanowano"].astype(int)
    df_pelne["różnica"] = df_pelne["zeskanowano"] - df_pelne["stan"]

    st.subheader("📊 Porównanie stanów")
    st.dataframe(df_pelne.style.applymap(highlight_diff, subset=["różnica"]))

    excel_buffer = io.BytesIO()
    df_pelne.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)

    st.download_button(
        label="📥 Pobierz raport różnic (Excel)",
        data=excel_buffer,
        file_name="raport_inwentaryzacja.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
