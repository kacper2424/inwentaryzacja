import streamlit as st
import pandas as pd
import io
from PIL import Image # Nadal może być potrzebne do pewnych operacji, choć mniej
import cv2
import numpy as np
import time
import queue # Do komunikacji między wątkami

from streamlit_webrtc import VideoProcessorBase, webrtc_streamer, RTCConfiguration

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

# === Procesor klatek wideo dla streamlit-webrtc ===
class QRScannerProcessor(VideoProcessorBase):
    def __init__(self, result_queue: queue.Queue):
        self.qr_decoder = cv2.QRCodeDetector()
        self.last_scanned_value = None
        self.last_scan_time = 0
        self.scan_cooldown_seconds = 2  # Minimum 2 sekundy przerwy przed ponownym zeskanowaniem tego samego kodu
        self.result_queue = result_queue # Kolejka do przekazywania wyników do głównego wątku Streamlit

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        decoded_text_display = None # Tekst do wyświetlenia na klatce

        # Próba detekcji kodu QR
        decoded_text, points, _ = self.qr_decoder.detectAndDecode(img)
        current_time = time.time()

        if decoded_text:
            # Sprawdzenie, czy to nowy kod lub czy upłynął cooldown
            if not (decoded_text == self.last_scanned_value and \
                    (current_time - self.last_scan_time) < self.scan_cooldown_seconds):
                
                # Przekaż zeskanowany tekst do głównego wątku przez kolejkę
                try:
                    self.result_queue.put_nowait(decoded_text) # Użyj put_nowait, aby nie blokować wątku przetwarzania wideo
                except queue.Full:
                    # Kolejka pełna, zignoruj ten skan (zdarza się rzadko przy szybkim przetwarzaniu w głównym wątku)
                    pass 
                
                self.last_scanned_value = decoded_text
                self.last_scan_time = current_time
                decoded_text_display = f"OK: {decoded_text}" # Komunikat na klatce
            else:
                # Ten sam kod, w trakcie cooldownu - tylko wyświetl
                decoded_text_display = f"Scanned: {decoded_text}"


            # Rysowanie ramki wokół wykrytego kodu QR
            if points is not None:
                # points to lista (zwykle jednoelementowa) tablic punktów
                # Każda tablica punktów to [[x1, y1], [x2, y2], ..., [xN, yN]]
                # Musimy przekształcić to na format akceptowany przez cv2.polylines
                contour = np.array(points[0], dtype=np.int32) # Bierzemy pierwszy (i zwykle jedyny) wykryty kontur
                cv2.polylines(img, [contour], isClosed=True, color=(0, 255, 0), thickness=3, lineType=cv2.LINE_AA)
                
                # Opcjonalnie: wyświetl tekst obok kodu QR na klatce
                if decoded_text_display:
                     # Ustal pozycję tekstu (np. pierwszy punkt konturu)
                    text_pos = (contour[0][0], contour[0][1] - 10) if len(contour) > 0 else (10,30)
                    cv2.putText(img, decoded_text_display, text_pos,
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
        
        # Zwróć przetworzoną klatkę (konwertowaną z powrotem do formatu av.VideoFrame)
        return frame.from_ndarray(img, format="bgr24")


# --- Główna aplikacja Streamlit ---
st.set_page_config(page_title="📦 Inwentaryzacja Sprzętu (Live Scan)", layout="wide")
st.title("📦 Inwentaryzacja sprzętu (Skanowanie Live)")

# Konfiguracja RTC (ważne dla połączeń, zwłaszcza przy deploymencie)
# Dla Streamlit Community Cloud często działają domyślne serwery STUN Google
RTC_CONFIGURATION = RTCConfiguration({
    "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
})

# --- Kolumna boczna ---
with st.sidebar:
    st.header("⚙️ Ustawienia")
    uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])
    if st.button("🗑️ Wyczyść wszystkie skany", key="clear_scans_sidebar"):
        st.session_state.zeskanowane = {}
        st.session_state.last_scan_message = {"text": "", "type": "info"}
        st.success("Wszystkie zeskanowane pozycje zostały wyczyszczone.")
        # st.experimental_rerun() # Streamlit >= 1.19.0 -> st.rerun()
        st.rerun()

# --- Inicjalizacja stanu sesji ---
if "zeskanowane" not in st.session_state:
    st.session_state.zeskanowane = {}
if "input_model_manual" not in st.session_state:
    st.session_state.input_model_manual = ""
if "last_scan_message" not in st.session_state:
    st.session_state.last_scan_message = {"text": "", "type": "info"} # {text: str, type: "success" | "warning" | "error"}
if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False


# --- Kolejka wyników skanowania ---
# Inicjalizujemy kolejkę poza if uploaded_file, aby była dostępna globalnie dla procesora
if "result_queue" not in st.session_state:
    st.session_state.result_queue = queue.Queue(maxsize=5) # Ograniczona wielkość, aby uniknąć problemów z pamięcią


# --- Główna zawartość ---
if uploaded_file:
    try:
        stany_magazynowe = load_data(uploaded_file)
    except Exception as e:
        st.error(f"Błąd wczytywania pliku: {e}")
        st.stop() # Zatrzymaj dalsze wykonywanie, jeśli plik jest błędny

    # Sekcja wprowadzania ręcznego
    st.subheader("➕ Dodaj model ręcznie")
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
            # st.experimental_rerun()
            st.rerun()

    st.text_input(
        "Wpisz model ręcznie i naciśnij Enter:",
        key="input_model_manual",
        on_change=process_manually_entered_model,
        placeholder="Np. Laptop XYZ123"
    )
    st.markdown("---")

    # Sekcja skanowania Live
    st.subheader("📷 Skaner QR Live")

    if st.button("🔛 Uruchom Skaner" if not st.session_state.scanner_active else "🛑 Zatrzymaj Skaner", key="toggle_scanner"):
        st.session_state.scanner_active = not st.session_state.scanner_active
        if not st.session_state.scanner_active: # Jeśli zatrzymujemy
            st.session_state.last_scan_message = {"text": "Skaner zatrzymany.", "type": "info"}
        else: # Jeśli uruchamiamy
             st.session_state.last_scan_message = {"text": "Skaner uruchomiony. Skieruj kamerę na kod QR.", "type": "info"}
        # st.experimental_rerun()
        st.rerun()

    # Wyświetlanie komunikatu o ostatnim skanie/działaniu
    message_placeholder_scan = st.empty()
    if st.session_state.last_scan_message["text"]:
        msg_type = st.session_state.last_scan_message["type"]
        msg_text = st.session_state.last_scan_message["text"]
        if msg_type == "success":
            message_placeholder_scan.success(msg_text, icon="🎉")
        elif msg_type == "warning":
            message_placeholder_scan.warning(msg_text, icon="⚠️")
        elif msg_type == "info":
            message_placeholder_scan.info(msg_text, icon="ℹ️")
        elif msg_type == "error":
            message_placeholder_scan.error(msg_text, icon="❌")


    if st.session_state.scanner_active:
        st.info("Skaner jest aktywny. Umieść kod QR w polu widzenia kamery. Zielona ramka oznacza wykrycie.")
        
        # Tworzenie instancji procesora wideo za każdym razem, gdy streamer jest tworzony
        # lub użycie `video_processor_factory` który zwraca nową instancję
        def processor_factory():
            return QRScannerProcessor(result_queue=st.session_state.result_queue)

        webrtc_ctx = webrtc_streamer(
            key="qr-live-scanner",
            video_processor_factory=processor_factory,
            rtc_configuration=RTC_CONFIGURATION,
            media_stream_constraints={"video": {"width": 640, "height": 480}, "audio": False}, # Można dostosować rozdzielczość
            async_processing=True, # Ważne dla płynności
        )
        
        # Sprawdzanie kolejki wyników w głównym wątku Streamlit
        # To będzie się działo przy każdym naturalnym przebiegu skryptu Streamlit
        # lub po st.rerun()
        if webrtc_ctx.state.playing: # Tylko jeśli streamer jest aktywny
            try:
                # Próbujemy pobrać wszystkie elementy z kolejki, które się tam znalazły od ostatniego sprawdzenia
                newly_scanned_codes = []
                while not st.session_state.result_queue.empty():
                    scanned_value = st.session_state.result_queue.get_nowait()
                    newly_scanned_codes.append(scanned_value)
                
                if newly_scanned_codes:
                    all_updated_models_message_parts = []
                    for decoded_text in newly_scanned_codes:
                        current_count = st.session_state.zeskanowane.get(decoded_text, 0) + 1
                        st.session_state.zeskanowane[decoded_text] = current_count
                        all_updated_models_message_parts.append(f"**{decoded_text}** (ilość: {current_count})")
                    
                    st.session_state.last_scan_message = {
                        "text": f"✅ Zeskanowano: " + ", ".join(all_updated_models_message_parts),
                        "type": "success"
                    }
                    # st.experimental_rerun() # Odśwież UI, aby pokazać nowy komunikat i zaktualizowaną tabelę
                    st.rerun()

            except queue.Empty:
                pass # Nic nowego w kolejce

    # Wyświetlanie tabeli porównawczej
    if st.session_state.zeskanowane or uploaded_file: # Pokaż tabelę, jeśli są skany LUB jeśli jest załadowany plik
        st.markdown("---")
        st.subheader("📊 Porównanie stanów")

        df_display = pd.DataFrame(columns=['model', 'stan', 'zeskanowano', 'różnica']) 

        if not stany_magazynowe.empty:
            df_display = stany_magazynowe.copy()
            df_display["zeskanowano"] = 0
            
            if st.session_state.zeskanowane:
                df_skan = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano_temp"])
                # Połącz, sumując wartości 'zeskanowano' dla modeli istniejących w obu df
                # Najpierw upewnij się, że df_display['model'] i df_skan['model'] są unikalne przed merge
                # To bardziej złożone, jeśli modele mogą się powtarzać w stany_magazynowe; zakładamy, że są unikalne
                
                # Aktualizuj zeskanowane dla istniejących modeli
                for model, count in st.session_state.zeskanowane.items():
                    if model in df_display['model'].values:
                        df_display.loc[df_display['model'] == model, 'zeskanowano'] = count
                    else: # Dodaj nowy wiersz, jeśli model nie istnieje w df_display
                        new_row = pd.DataFrame([{'model': model, 'stan': 0, 'zeskanowano': count}])
                        df_display = pd.concat([df_display, new_row], ignore_index=True)
            
            df_display["zeskanowano"] = df_display["zeskanowano"].fillna(0).astype(int)
            df_display["stan"] = df_display["stan"].fillna(0).astype(int)

        elif st.session_state.zeskanowane: # Tylko skany, brak pliku magazynowego
            df_display = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
            df_display["stan"] = 0
        
        if not df_display.empty:
            df_display["model"] = df_display["model"].astype(str).str.strip()
            # Usuń wiersze, gdzie model to 'nan', pusty string lub '0' (jeśli '0' nie jest prawidłowym modelem)
            df_display = df_display[~df_display["model"].str.lower().isin(["nan", "", "0"])]
            
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
