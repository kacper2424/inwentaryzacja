import streamlit as st
import pandas as pd
import io
from PIL import Image
import cv2
import numpy as np

# === Funkcja kolorująca różnicę tylko w kolumnie 'różnica' ===
def highlight_diff(val):
    if isinstance(val, (int, float)):
        if val < 0:
            color = 'red'
        elif val > 0:
            color = 'blue'
        else:
            color = ''
        return f'color: {color}'
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
    df['stan'] = pd.to_numeric(df['stan'], errors='coerce').fillna(0).astype(int)
    return df

# === Funkcja dekodująca QR za pomocą OpenCV ===
def decode_qr_from_image_bytes(image_bytes_io):
    try:
        pil_image = Image.open(image_bytes_io).convert('RGB')
        cv_image = np.array(pil_image)
        cv_image = cv_image[:, :, ::-1].copy() # RGB to BGR
        qr_decoder = cv2.QRCodeDetector()
        decoded_text, points, _ = qr_decoder.detectAndDecode(cv_image)
        if points is not None and decoded_text:
            return decoded_text.strip()
        return None
    except Exception:
        return None

st.set_page_config(page_title="📦 Inwentaryzacja Sprzętu", layout="wide")
st.title("📦 Inwentaryzacja sprzętu")

# --- Kolumna boczna ---
with st.sidebar:
    st.header("⚙️ Ustawienia")
    uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])
    if st.button("🗑️ Wyczyść wszystkie skany", key="clear_scans_sidebar"):
        st.session_state.zeskanowane = {}
        st.session_state.last_scan_message = {"text": "", "type": "info"} # Zmieniono na słownik
        if "show_camera_input" in st.session_state:
            st.session_state.show_camera_input = False
        st.success("Wszystkie zeskanowane pozycje zostały wyczyszczone.")
        st.rerun()

# --- Główna zawartość ---
if uploaded_file:
    try:
        stany_magazynowe = load_data(uploaded_file)
    except Exception as e:
        st.error(f"Błąd wczytywania pliku: {e}")
        st.stop()

    # Inicjalizacja sesji
    if "zeskanowane" not in st.session_state:
        st.session_state.zeskanowane = {}
    if "input_model_manual" not in st.session_state:
        st.session_state.input_model_manual = ""
    if "show_camera_input" not in st.session_state:
        st.session_state.show_camera_input = False
    # Zmieniamy last_scan_message na słownik, aby przechowywać typ komunikatu (success, warning, error)
    if "last_scan_message" not in st.session_state:
        st.session_state.last_scan_message = {"text": "", "type": "info"}

    def process_manually_entered_model():
        model = st.session_state.input_model_manual.strip()
        if model:
            current_count = st.session_state.zeskanowane.get(model, 0) + 1
            st.session_state.zeskanowane[model] = current_count
            st.session_state.input_model_manual = ""
            st.session_state.last_scan_message = {
                "text": f"👍 Dodano ręcznie: **{model}** (Nowa ilość: {current_count})",
                "type": "success"
            }

    # Sekcja wprowadzania i skanowania
    st.subheader("➕ Dodaj model")
    col_input, col_qr_toggle = st.columns([0.6, 0.4])

    with col_input:
        st.text_input(
            "Wpisz model ręcznie i naciśnij Enter:",
            key="input_model_manual",
            on_change=process_manually_entered_model,
            placeholder="Np. Laptop XYZ123"
        )

    with col_qr_toggle:
        st.write("")
        st.write("")
        button_label = "📷 Skanuj QR" if not st.session_state.show_camera_input else "📸 Ukryj Kamerę"
        if st.button(button_label, key="toggle_camera_button", use_container_width=True):
            st.session_state.show_camera_input = not st.session_state.show_camera_input
            if not st.session_state.show_camera_input:
                 st.session_state.last_scan_message = {"text": "", "type": "info"}
            st.rerun()

    # Wyświetlanie komunikatu o ostatnim skanie/działaniu
    # Używamy kontenera, aby komunikat był dobrze widoczny i na górze sekcji skanowania
    message_placeholder_scan = st.empty()
    if st.session_state.last_scan_message["text"]:
        msg_type = st.session_state.last_scan_message["type"]
        msg_text = st.session_state.last_scan_message["text"]
        if msg_type == "success":
            message_placeholder_scan.success(msg_text, icon="🎉")
        elif msg_type == "warning":
            message_placeholder_scan.warning(msg_text, icon="⚠️")
        elif msg_type == "error":
            message_placeholder_scan.error(msg_text, icon="❌")


    if st.session_state.show_camera_input:
        st.info("💡 Wskazówka: Umieść kod QR na środku kadru i kliknij 'Take photo' poniżej.", icon="🎯")
        img_file_buffer = st.camera_input(
            "Zrób zdjęcie kodu QR",
            key="qr_camera_input_live", # Zmieniony klucz, aby wymusić reset, jeśli jest to pożądane
            label_visibility="collapsed"
        )

        if img_file_buffer is not None:
            bytes_data = img_file_buffer.getvalue()
            # Czyścimy poprzedni komunikat przed przetwarzaniem nowego zdjęcia
            # message_placeholder_scan.empty() # Usunięte, bo st.rerun() czyści

            with st.spinner("🔍 Przetwarzanie obrazu..."):
                decoded_qr_text = decode_qr_from_image_bytes(io.BytesIO(bytes_data))

            if decoded_qr_text:
                current_count = st.session_state.zeskanowane.get(decoded_qr_text, 0) + 1
                st.session_state.zeskanowane[decoded_qr_text] = current_count
                st.session_state.last_scan_message = {
                    "text": f"✅ Zeskanowano: **{decoded_qr_text}** (Nowa ilość: {current_count})",
                    "type": "success"
                }
            else:
                st.session_state.last_scan_message = {
                    "text": "Nie udało się odczytać kodu QR. Spróbuj ponownie z lepszym oświetleniem/ostrością.",
                    "type": "warning"
                }
            st.rerun()

    # Wyświetlanie tabeli porównawczej
    if st.session_state.zeskanowane or uploaded_file:
        st.markdown("---")
        st.subheader("📊 Porównanie stanów")

        df_display = pd.DataFrame(columns=['model', 'stan', 'zeskanowano', 'różnica']) # Domyślnie pusta

        if not stany_magazynowe.empty:
            df_display = stany_magazynowe.copy()
            df_display["zeskanowano"] = 0
            # Dołącz zeskanowane, jeśli istnieją
            if st.session_state.zeskanowane:
                df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano_temp"])
                df_display = df_display.merge(df_skan, on="model", how="left")
                df_display["zeskanowano"] = df_display["zeskanowano_temp"].fillna(0).astype(int) + df_display["zeskanowano"]
                df_display.drop(columns=["zeskanowano_temp"], inplace=True, errors='ignore')

            # Dodaj modele, które są zeskanowane, a nie ma ich w stanach magazynowych
            if st.session_state.zeskanowane:
                skany_modele = set(st.session_state.zeskanowane.keys())
                magazyn_modele = set(df_display["model"].unique())
                tylko_w_skanach = list(skany_modele - magazyn_modele)
                if tylko_w_skanach:
                    df_tylko_skany = pd.DataFrame({
                        "model": tylko_w_skanach,
                        "stan": 0,
                        "zeskanowano": [st.session_state.zeskanowane[m] for m in tylko_w_skanach]
                    })
                    df_display = pd.concat([df_display, df_tylko_skany], ignore_index=True)
            
            df_display["zeskanowano"] = df_display["zeskanowano"].fillna(0).astype(int)
            df_display["stan"] = df_display["stan"].fillna(0).astype(int)

        elif st.session_state.zeskanowane: # Tylko skany, brak pliku magazynowego
            df_display = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
            df_display["stan"] = 0
        
        if not df_display.empty:
            df_display["model"] = df_display["model"].astype(str).str.strip()
            df_display = df_display[df_display["model"].str.lower().isin(["nan", "", "0"]) == False]
            df_display["różnica"] = df_display["zeskanowano"] - df_display["stan"]
            df_display = df_display.sort_values(by=['różnica', 'model'], ascending=[True, True])
        else:
             st.info("Rozpocznij skanowanie lub wprowadzanie modeli, aby zobaczyć dane w tabeli. Jeśli wgrałeś plik, upewnij się, że zawiera dane.")


        st.dataframe(
            df_display.style.applymap(highlight_diff, subset=['różnica']),
            use_container_width=True,
            hide_index=True
        )

        if not df_display.empty:
            excel_buffer = io.BytesIO()
            df_display.to_excel(excel_buffer, index=False, sheet_name="RaportInwentaryzacji", engine='openpyxl')
            excel_buffer.seek(0)
            st.download_button(
                label="📥 Pobierz raport różnic (Excel)",
                data=excel_buffer,
                file_name="raport_inwentaryzacja.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        elif st.session_state.zeskanowane:
             st.info("Wgraj plik Excel, aby zobaczyć pełne porównanie stanów i różnice.")

else:
    st.info("👋 Witaj! Aby rozpocząć, wgraj plik Excel ze stanem magazynowym z panelu po lewej stronie.")
    st.markdown("Plik powinien zawierać kolumny `model` oraz `stan`.")
