import streamlit as st
import pandas as pd
import io
from PIL import Image
import cv2  # Dla OpenCV
import numpy as np # OpenCV często pracuje z tablicami numpy

# === Funkcja kolorująca różnicę tylko w kolumnie 'różnica' ===
def highlight_diff(val):
    if isinstance(val, (int, float)): # Dodatkowe sprawdzenie typu
        if val < 0:
            color = 'red'
        elif val > 0:
            color = 'blue'
        else:
            color = ''
        return f'color: {color}'
    return '' # Zwróć pusty string dla innych typów

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
    # Lepsze parsowanie stanu, obsługa błędów i NaN
    df['stan'] = pd.to_numeric(df['stan'], errors='coerce').fillna(0).astype(int)
    return df

# === Funkcja dekodująca QR za pomocą OpenCV ===
def decode_qr_from_image_bytes(image_bytes_io):
    try:
        # Wczytaj obraz z bajtów używając PIL, następnie konwertuj do OpenCV
        pil_image = Image.open(image_bytes_io).convert('RGB') # Upewnij się, że jest w RGB
        cv_image = np.array(pil_image)
        # Konwersja RGB do BGR (OpenCV wewnętrznie używa BGR)
        cv_image = cv_image[:, :, ::-1].copy()

        qr_decoder = cv2.QRCodeDetector()
        decoded_text, points, _ = qr_decoder.detectAndDecode(cv_image)

        if points is not None and decoded_text: # Sprawdź, czy coś wykryto
            return decoded_text.strip()
        return None
    except Exception as e:
        st.error(f"Błąd podczas dekodowania QR: {e}")
        return None

st.set_page_config(page_title="📦 Inwentaryzacja Sprzętu", layout="wide")
st.title("📦 Inwentaryzacja sprzętu")

# --- Kolumna boczna dla wgrania pliku i przycisku czyszczenia ---
with st.sidebar:
    st.header("⚙️ Ustawienia")
    uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])

    if st.button("🗑️ Wyczyść wszystkie skany", key="clear_scans_sidebar"):
        st.session_state.zeskanowane = {}
        if "show_camera_input" in st.session_state: # Ukryj kamerę, jeśli była widoczna
            st.session_state.show_camera_input = False
        st.success("Wszystkie zeskanowane pozycje zostały wyczyszczone.")
        # Nie ma potrzeby st.rerun() tutaj, Streamlit sam odświeży po zmianie stanu i akcji przycisku

# --- Główna zawartość ---
if uploaded_file:
    try:
        stany_magazynowe = load_data(uploaded_file)
    except Exception as e:
        st.error(f"Błąd wczytywania pliku: {e}")
        st.stop()

    # Inicjalizacja sesji, jeśli nie istnieje
    if "zeskanowane" not in st.session_state:
        st.session_state.zeskanowane = {}
    if "input_model_manual" not in st.session_state: # Zmieniono klucz dla ręcznego wprowadzania
        st.session_state.input_model_manual = ""
    if "show_camera_input" not in st.session_state:
        st.session_state.show_camera_input = False
    if "last_qr_result" not in st.session_state:
        st.session_state.last_qr_result = None


    # Funkcja wywoływana po wpisaniu modelu i naciśnięciu Enter
    def process_manually_entered_model():
        model = st.session_state.input_model_manual.strip()
        if model:
            st.session_state.zeskanowane[model] = st.session_state.zeskanowane.get(model, 0) + 1
            st.session_state.input_model_manual = ""  # Czyścimy pole input
            st.session_state.last_qr_result = None # Czyścimy ostatni wynik QR
            st.success(f"Dodano ręcznie: {model}")


    col_input, col_qr_toggle = st.columns([3,1])

    with col_input:
        st.text_input(
            "Wpisz model ręcznie i naciśnij Enter:",
            key="input_model_manual",
            on_change=process_manually_entered_model,
            # help="Po wpisaniu naciśnij Enter, aby dodać model."
        )

    with col_qr_toggle:
        st.write("") # Dodanie małego odstępu dla wyrównania
        st.write("")
        if st.button("📷 Skanuj QR", key="toggle_camera_button"):
            st.session_state.show_camera_input = not st.session_state.show_camera_input
            st.session_state.last_qr_result = None # Resetuj wynik przy przełączaniu kamery

    if st.session_state.show_camera_input:
        st.info("Ustaw kod QR przed obiektywem i zrób zdjęcie. Wynik pojawi się poniżej.")
        img_file_buffer = st.camera_input("Zrób zdjęcie kodu QR", key="qr_camera_input", label_visibility="collapsed")

        if img_file_buffer is not None:
            # Odczytaj bajty obrazu
            bytes_data = img_file_buffer.getvalue()

            # Zdekoduj QR
            with st.spinner("Przetwarzanie obrazu..."):
                decoded_qr_text = decode_qr_from_image_bytes(io.BytesIO(bytes_data))

            if decoded_qr_text:
                st.session_state.last_qr_result = decoded_qr_text
                st.session_state.zeskanowane[decoded_qr_text] = st.session_state.zeskanowane.get(decoded_qr_text, 0) + 1
                st.success(f"✅ Zeskanowano i dodano model: {decoded_qr_text}")
                # Ukrywamy kamerę po udanym skanie, aby uniknąć przypadkowych kolejnych zdjęć
                st.session_state.show_camera_input = False
                st.rerun() # Odświeżenie, aby ukryć kamerę i zaktualizować tabelę
            else:
                st.session_state.last_qr_result = "Nie udało się odczytać kodu QR."
                st.warning("⚠️ Nie udało się odczytać kodu QR ze zdjęcia. Spróbuj ponownie z lepszym oświetleniem lub bliżej kodu.")
            # Ważne: Po przetworzeniu zdjęcia, widget camera_input "resetuje" swój stan (img_file_buffer staje się None).
            # Aby uniknąć ponownego przetwarzania tego samego None, nie potrzebujemy jawnego czyszczenia img_file_buffer.


    # Wyświetlanie tabeli porównawczej
    if st.session_state.zeskanowane:
        st.markdown("---")
        st.subheader("📊 Porównanie stanów")

        df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
        df_pelne = stany_magazynowe.merge(df_skan, on="model", how="outer").fillna(0)

        # Czyszczenie modeli (usuwanie pustych, 'nan', '0' które mogły powstać)
        df_pelne["model"] = df_pelne["model"].astype(str).str.strip()
        df_pelne = df_pelne[df_pelne["model"].str.lower() != "nan"]
        df_pelne = df_pelne[df_pelne["model"] != ""]
        df_pelne = df_pelne[df_pelne["model"] != "0"] # Jeśli '0' nie jest poprawnym modelem

        # Konwersja typów i obliczenie różnicy
        df_pelne["zeskanowano"] = df_pelne["zeskanowano"].astype(int)
        df_pelne["stan"] = df_pelne["stan"].astype(int) # Upewnij się, że stan z Excela jest int
        df_pelne["różnica"] = df_pelne["zeskanowano"] - df_pelne["stan"]

        # Sortowanie dla lepszej czytelności
        df_pelne_sorted = df_pelne.sort_values(by=['różnica', 'model'], ascending=[True, True])

        st.dataframe(
            df_pelne_sorted.style.applymap(highlight_diff, subset=['różnica']),
            use_container_width=True
        )

        # Eksport do Excela
        excel_buffer = io.BytesIO()
        # Upewnij się, że openpyxl jest w requirements.txt
        df_pelne_sorted.to_excel(excel_buffer, index=False, sheet_name="RaportInwentaryzacji", engine='openpyxl')
        excel_buffer.seek(0)

        st.download_button(
            label="📥 Pobierz raport różnic (Excel)",
            data=excel_buffer,
            file_name="raport_inwentaryzacja.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    elif uploaded_file: # Jeśli plik jest wgrany, ale nic nie zeskanowano
        st.info("Rozpocznij skanowanie lub wprowadzanie modeli, aby zobaczyć porównanie.")

else:
    st.info("👋 Witaj! Aby rozpocząć, wgraj plik Excel ze stanem magazynowym z panelu po lewej stronie.")
    st.markdown("Plik powinien zawierać kolumny `model` oraz `stan`.")
