import streamlit as st
import pandas as pd
import io
import uuid
import streamlit.components.v1 as components

# === Funkcja kolorująca różnicę tylko w kolumnie 'różnica' ===
def highlight_diff(val):
    if val < 0:
        color = 'red'
    elif val > 0:
        color = 'blue'
    else:
        color = ''
    return f'color: {color}'

# === Wczytaj dane z Excela ===
@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = [col.lower().strip() for col in df.columns]

    # Walidacja kolumn
    required_cols = {'model', 'stan'}
    if not required_cols.issubset(df.columns):
        raise ValueError("Plik musi zawierać kolumny: model i stan")

    df = df[['model', 'stan']]
    df['model'] = df['model'].astype(str).str.strip()
    return df

# === Tytuł ===
st.title("📦 Inwentaryzacja sprzętu")

uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])

if uploaded_file:
    try:
        stany_magazynowe = load_data(uploaded_file)
    except Exception as e:
        st.error(f"Błąd wczytywania pliku: {e}")
        st.stop()

    # Inicjalizacja sesji
    if "zeskanowane" not in st.session_state:
        st.session_state.zeskanowane = {}

    if "input_model" not in st.session_state:
        st.session_state.input_model = ""

    # === Funkcja przy skanowaniu ===
    def scan_model():
        model = st.session_state.input_model.strip()
        if model:
            st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1
            st.session_state.input_model = ""  # czyścimy pole input

    # === Wprowadzanie modelu ręcznie / przez skaner ===
    st.text_input(
        "Zeskanuj kod modelu (lub wpisz ręcznie i naciśnij Enter)",
        key="input_model",
        on_change=scan_model
    )

    # === Rozwijana kamera QR ===
    with st.expander("📷 Skanuj kod QR kamerą (kliknij aby uruchomić)"):
        qr_code_scanner_html = """
        <script src="https://unpkg.com/html5-qrcode@2.3.8/minified/html5-qrcode.min.js"></script>
        <div style="display:flex; justify-content:center;">
          <div id="reader" style="width: 300px;"></div>
        </div>
        <div id="qr-error" style="color:red; text-align:center; margin-top:10px;"></div>
        <script>
          const qrErrorBox = document.getElementById("qr-error");

          function onScanSuccess(decodedText, decodedResult) {
            const streamlitInput = window.parent.document.querySelector('input[data-testid="stTextInput"]');
            if (streamlitInput) {
              streamlitInput.value = decodedText;
              const event = new Event('input', { bubbles: true });
              streamlitInput.dispatchEvent(event);
            }
          }

          function onScanFailure(error) {
            console.warn(`QR scan error: ${error}`);
          }

          const html5QrCode = new Html5Qrcode("reader");
          Html5Qrcode.getCameras().then(cameras => {
            if (cameras && cameras.length) {
              html5QrCode.start(
                { facingMode: "environment" },
                { fps: 10, qrbox: { width: 250, height: 250 } },
                onScanSuccess,
                onScanFailure
              ).catch(err => {
                qrErrorBox.innerText = "❌ Błąd uruchamiania kamery: " + err;
              });
            } else {
              qrErrorBox.innerText = "❌ Nie wykryto żadnej kamery.";
            }
          }).catch(err => {
            qrErrorBox.innerText = "❌ Błąd pobierania kamer: " + err;
          });
        </script>
        """
        components.html(qr_code_scanner_html, height=450)

    # === Przycisk czyszczenia skanów ===
    if st.button("🗑️ Wyczyść wszystkie skany"):
        st.session_state.zeskanowane = {}
        st.rerun()

    # === Porównanie ===
    df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
    df_pelne = stany_magazynowe.merge(df_skan, on="model", how="outer").fillna(0)

    # Czyścimy puste / błędne modele
    df_pelne["model"] = df_pelne["model"].astype(str).str.strip()
    df_pelne = df_pelne[df_pelne["model"].notna() & (df_pelne["model"] != "")]

    df_pelne["zeskanowano"] = df_pelne["zeskanowano"].astype(int)
    df_pelne["stan"] = df_pelne["stan"].astype(int)
    df_pelne["różnica"] = df_pelne["zeskanowano"] - df_pelne["stan"]

    st.subheader("📊 Porównanie stanów")
    st.dataframe(df_pelne.style.applymap(highlight_diff, subset=['różnica']))

    # === Eksport Excel ===
    excel_buffer = io.BytesIO()
    df_pelne.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)

    st.download_button(
        label="📥 Pobierz raport różnic (Excel)",
        data=excel_buffer,
        file_name="raport_inwentaryzacja.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
