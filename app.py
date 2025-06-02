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
    except Exception: # Ogólny wyjątek, aby uniknąć crashu
        # st.error(f"Błąd podczas dekodowania QR: {e}") # Można logować, ale niekoniecznie pokazywać użytkownikowi za każdym razem
        return None

st.set_page_config(page_title="📦 Inwentaryzacja Sprzętu", layout="wide")
st.title("📦 Inwentaryzacja sprzętu")

# --- Kolumna boczna ---
with st.sidebar:
    st.header("⚙️ Ustawienia")
    uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])
    if st.button("🗑️ Wyczyść wszystkie skany", key="clear_scans_sidebar"):
        st.session_state.zeskanowane = {}
        st.session_state.last_scan_message = ""
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
    if "last_scan_message" not in st.session_state:
        st.session_state.last_scan_message = ""

    def process_manually_entered_model():
        model = st.session_state.input_model_manual.strip()
        if model:
            st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1
            st.session_state.input_model_manual = ""
            st.session_state.last_scan_message = f"👍 Dodano ręcznie: **{model}** (Nowa ilość: {st.session_state.zeskanowane[model]})"
            # on_change w text_input automatycznie wywoła rerun

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
        st.write("") # Placeholder dla wyrównania
        st.write("") # Placeholder dla wyrównania
        button_label = "📷 Skanuj QR" if not st.session_state.show_camera_input else "📸 Ukryj Kamerę"
        if st.button(button_label, key="toggle_camera_button", use_container_width=True):
            st.session_state.show_camera_input = not st.session_state.show_camera_input
            if not st.session_state.show_camera_input: # Jeśli ukrywamy kamerę
                 st.session_state.last_scan_message = "" # Czyść komunikat
            st.rerun()

    # Wyświetlanie komunikatu o ostatnim skanie/działaniu
    # Używamy kontenera, aby komunikat był dobrze widoczny
    message_placeholder = st.empty()
    if st.session_state.last_scan_message:
        if "✅" in st.session_state.last_scan_message or "👍" in st.session_state.last_scan_message:
            message_placeholder.success(st.session_state.last_scan_message, icon="🎉")
        elif "⚠️" in st.session_state.last_scan_message:
            message_placeholder.warning(st.session_state.last_scan_message, icon="❗")


    if st.session_state.show_camera_input:
        st.info("Ustaw kod QR przed obiektywem i kliknij 'Take photo' poniżej.", icon="🤳")
        img_file_buffer = st.camera_input(
            "Zrób zdjęcie kodu QR",
            key="qr_camera_input", # Unikalny klucz jest ważny
            label_visibility="collapsed"
        )

        if img_file_buffer is not None:
            # Ten blok wykona się tylko raz bezpośrednio po zrobieniu zdjęcia.
            # `img_file_buffer` będzie `None` w kolejnych rerunach, dopóki nie zostanie zrobione nowe zdjęcie.
            bytes_data = img_file_buffer.getvalue()
            with st.spinner("🔍 Przetwarzanie obrazu..."):
                decoded_qr_text = decode_qr_from_image_bytes(io.BytesIO(bytes_data))

            if decoded_qr_text:
                current_count = st.session_state.zeskanowane.get(decoded_qr_text, 0) + 1
                st.session_state.zeskanowane[decoded_qr_text] = current_count
                st.session_state.last_scan_message = f"✅ Zeskanowano: **{decoded_qr_text}** (Nowa ilość: {current_count})"
            else:
                st.session_state.last_scan_message = "⚠️ Nie udało się odczytać kodu QR. Spróbuj ponownie z lepszym oświetleniem/ostrością."
            
            # Kluczowe: Po przetworzeniu zdjęcia, wywołujemy st.rerun().
            # To odświeży UI, wyświetli zaktualizowany last_scan_message i zaktualizuje tabelę.
            # st.camera_input samoczynnie zresetuje swoją wartość (img_file_buffer) do None,
            # ale pozostanie widoczny, gotowy do kolejnego zdjęcia.
            st.rerun()

    # Wyświetlanie tabeli porównawczej
    if st.session_state.zeskanowane or uploaded_file: # Pokaż tabelę, jeśli są skany LUB jeśli jest załadowany plik
        st.markdown("---")
        st.subheader("📊 Porównanie stanów")

        if not st.session_state.zeskanowane and not stany_magazynowe.empty:
            st.info("Rozpocznij skanowanie lub wprowadzanie modeli, aby zobaczyć dane w tabeli.")
            # Pokaż pustą strukturę tabeli lub tylko stany magazynowe
            df_display = stany_magazynowe.copy()
            df_display["zeskanowano"] = 0
            df_display["różnica"] = -df_display["stan"] # Różnica to to, czego brakuje
        elif not st.session_state.zeskanowane and stany_magazynowe.empty:
            st.info("Brak danych magazynowych i brak zeskanowanych przedmiotów.")
            df_display = pd.DataFrame(columns=['model', 'stan', 'zeskanowano', 'różnica']) # Pusta tabela
        else:
            df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
            if not stany_magazynowe.empty:
                df_pelne = stany_magazynowe.merge(df_skan, on="model", how="outer").fillna(0)
            else: # Jeśli plik Excel był pusty lub tylko z nagłówkami
                df_pelne = df_skan.copy()
                df_pelne["stan"] = 0 # Dodaj kolumnę stan z zerami

            df_pelne["model"] = df_pelne["model"].astype(str).str.strip()
            df_pelne = df_pelne[df_pelne["model"].str.lower().isin(["nan", "", "0"]) == False]

            df_pelne["zeskanowano"] = df_pelne["zeskanowano"].astype(int)
            df_pelne["stan"] = df_pelne["stan"].astype(int)
            df_pelne["różnica"] = df_pelne["zeskanowano"] - df_pelne["stan"]
            df_display = df_pelne.sort_values(by=['różnica', 'model'], ascending=[True, True])


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
        elif st.session_state.zeskanowane: # Są skany, ale np. plik excel niezaładowany
             st.info("Wgraj plik Excel, aby zobaczyć pełne porównanie stanów i różnice.")


else:
    st.info("👋 Witaj! Aby rozpocząć, wgraj plik Excel ze stanem magazynowym z panelu po lewej stronie.")
    st.markdown("Plik powinien zawierać kolumny `model` oraz `stan`.")
