import streamlit as st
import pandas as pd
import io
import uuid
import streamlit.components.v1 as components

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

    # Walidacja kolumn
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

    # Inicjalizacja sesji
    if "zeskanowane" not in st.session_state:
        st.session_state.zeskanowane = {}

    if "input_model" not in st.session_state:
        st.session_state.input_model = ""

    # Funkcja wywoływana po wpisaniu modelu i naciśnięciu Enter
    def scan_model():
        model = st.session_state.input_model.strip()
        if model:
            st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1
            st.session_state.input_model = ""

    # Pole tekstowe do ręcznego wpisywania / skanera
    st.text_input(
        "Zeskanuj kod modelu (lub wpisz ręcznie i naciśnij Enter)",
        key="input_model",
        on_change=scan_model
    )

    # Kamera QR — działa na telefonie i komputerze
    with st.expander("📷 Skanuj kod QR kamerą (kliknij aby uruchomić)"):
        qr_code_scanner_html = """
        <!DOCTYPE html>
        <html>
          <head>
            <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
          </head>
          <body>
            <div style="text-align:center;">
              <div id="reader" style="width: 300px; margin: auto;"></div>
              <div id="qr-error" style="color:red; margin-top:10px;"></div>
            </div>
            <script>
              function onScanSuccess(decodedText, decodedResult) {
                const inputBox = window.parent.document.querySelector('input[data-testid="stTextInput"]');
                if (inputBox) {
                  inputBox.value = decodedText;
                  inputBox.dispatchEvent(new Event('input', { bubbles: true }));
                }
              }

              function onScanFailure(error) {
                console.warn(`QR scan error: ${error}`);
              }

              const qrErrorBox = document.getElementById("qr-error");

              Html5Qrcode.getCameras().then(cameras => {
                if (cameras && cameras.length) {
                  const html5QrCode = new Html5Qrcode("reader");
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
          </body>
        </html>
        """
        components.html(qr_code_scanner_html, height=450)

    # Przycisk do wyczyszczenia sesji
    if st.button("🗑️ Wyczyść wszystkie skany"):
        st.session_state.zeskanowane = {}
        st.rerun()

    # Porównanie z rzeczywistym stanem
    df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
    df_pelne = stany_magazynowe.merge(df_skan, on="model", how="outer").fillna(0)

    # Czyszczenie danych
    df_pelne["model"] = df_pelne["model"].astype(str).str.strip()
    df_pelne = df_pelne[df_pelne["model"] != "nan"]
    df_pelne = df_pelne[df_pelne["model"] != ""]

    # Typy i różnice
    df_pelne["zeskanowano"] = df_pelne["zeskanowano"].astype(int)
    df_pelne["stan"] = df_pelne["stan"].astype(int)
    df_pelne["różnica"] = df_pelne["zeskanowano"] - df_pelne["stan"]

    st.subheader("📊 Porównanie stanów")
    st.dataframe(df_pelne.style.applymap(highlight_diff, subset=['różnica']))

    # Eksport do Excela
    excel_buffer = io.BytesIO()
    df_pelne.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)

    st.download_button(
        label="📥 Pobierz raport różnic (Excel)",
        data=excel_buffer,
        file_name="raport_inwentaryzacja.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
