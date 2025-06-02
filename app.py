import streamlit as st
import pandas as pd
import io
import streamlit.components.v1 as components

st.set_page_config(page_title="Inwentaryzacja", layout="centered")

# === Sesja i dane ===
if "zeskanowane" not in st.session_state:
    st.session_state.zeskanowane = {}

if "input_model" not in st.session_state:
    st.session_state.input_model = ""

if "show_camera" not in st.session_state:
    st.session_state.show_camera = False

def scan_model():
    model = st.session_state.input_model.strip()
    if model:
        st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1
        st.session_state.input_model = ""

# === Wczytywanie pliku Excel ===
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

uploaded_file = st.file_uploader("📤 Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])

if uploaded_file:
    try:
        stany_magazynowe = load_data(uploaded_file)
    except Exception as e:
        st.error(f"Błąd pliku: {e}")
        st.stop()

    st.text_input("🔎 Zeskanuj lub wpisz kod modelu:", key="input_model", on_change=scan_model)

    # 🔘 Przycisk uruchamiający kamerę
    if st.button("📸 Włącz kamerę do skanowania QR"):
        st.session_state.show_camera = True

    if st.session_state.show_camera:
        st.info("📷 Kamera uruchomiona – zeskanuj kod QR")

        components.html("""
        <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
        <div style="text-align:center;">
            <div id="reader" style="width: 300px; margin: auto;"></div>
        </div>
        <script>
            const qrScanner = new Html5Qrcode("reader");
            qrScanner.start(
                { facingMode: "environment" },
                { fps: 10, qrbox: 250 },
                (decodedText, decodedResult) => {
                    const inputBox = window.parent.document.querySelector('input[data-testid="stTextInput"]');
                    if (inputBox) {
                        inputBox.value = decodedText;
                        inputBox.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                }
            ).catch(err => {
                console.error("Camera start error", err);
            });
        </script>
        """, height=450)

    if st.button("🗑️ Wyczyść skany"):
        st.session_state.zeskanowane = {}
        st.rerun()

    # 🔍 Porównanie
    df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
    df_pelne = stany_magazynowe.merge(df_skan, on="model", how="outer").fillna(0)
    df_pelne["model"] = df_pelne["model"].astype(str).str.strip()
    df_pelne = df_pelne[df_pelne["model"] != ""]
    df_pelne["stan"] = df_pelne["stan"].astype(int)
    df_pelne["zeskanowano"] = df_pelne["zeskanowano"].astype(int)
    df_pelne["różnica"] = df_pelne["zeskanowano"] - df_pelne["stan"]

    def highlight_diff(val):
        if val < 0:
            return "color: red"
        elif val > 0:
            return "color: blue"
        return ""

    st.subheader("📊 Raport różnic")
    st.dataframe(df_pelne.style.applymap(highlight_diff, subset=["różnica"]))

    # ⬇️ Pobierz
    excel_buffer = io.BytesIO()
    df_pelne.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)

    st.download_button(
        label="📥 Pobierz raport (Excel)",
        data=excel_buffer,
        file_name="raport_inwentaryzacja.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
