import streamlit as st
import pandas as pd
import io
from PIL import Image
import cv2
import numpy as np
import time
import queue

from streamlit_webrtc import VideoProcessorBase, webrtc_streamer, RTCConfiguration, WebRtcMode

# === Funkcja kolorująca różnicę tylko w kolumnie 'różnica' ===
def highlight_diff(val):
    if isinstance(val, (int, float)):
        if val < 0: color = 'red'
        elif val > 0: color = 'blue'
        else: color = ''
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
        self.scan_cooldown_seconds = 2.0 # Float dla time.time()
        self.result_queue = result_queue
        self._active = True # Wewnętrzny stan aktywności

    def set_active(self, active: bool):
        self._active = active

    def recv(self, frame):
        if not self._active or self.result_queue is None:
            return frame

        img = frame.to_ndarray(format="bgr24")
        decoded_text_display = None
        try:
            decoded_text, points, _ = self.qr_decoder.detectAndDecode(img)
            current_time = time.time()

            if decoded_text:
                if not (decoded_text == self.last_scanned_value and \
                        (current_time - self.last_scan_time) < self.scan_cooldown_seconds):
                    try:
                        self.result_queue.put_nowait(decoded_text)
                    except queue.Full:
                        pass
                    
                    self.last_scanned_value = decoded_text
                    self.last_scan_time = current_time
                    decoded_text_display = f"OK: {decoded_text[:20]}..." if len(decoded_text) > 20 else f"OK: {decoded_text}"
                else:
                    decoded_text_display = f"Scanned: {decoded_text[:20]}..." if len(decoded_text) > 20 else f"Scanned: {decoded_text}"

                if points is not None and len(points) > 0 and points[0] is not None and len(points[0]) > 0 :
                    contour = np.array(points[0], dtype=np.int32)
                    if contour.ndim == 2 and contour.shape[1] == 2: # Upewnij się, że to poprawne punkty
                        cv2.polylines(img, [contour], isClosed=True, color=(0, 255, 0), thickness=3, lineType=cv2.LINE_AA)
                        if decoded_text_display:
                            text_pos = (contour[0][0], contour[0][1] - 10) if len(contour) > 0 else (10,30)
                            cv2.putText(img, decoded_text_display, text_pos,
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
            
            return frame.from_ndarray(img, format="bgr24")
        except Exception as e:
            # print(f"Error in QRScannerProcessor: {e}") # Do debugowania
            return frame


# --- Główna aplikacja Streamlit ---
st.set_page_config(page_title="📦 Inwentaryzacja Sprzętu (Live Scan)", layout="wide")
st.title("📦 Inwentaryzacja sprzętu (Skanowanie Live)")

RTC_CONFIGURATION = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

# --- Inicjalizacja stanu sesji ---
# Te wartości muszą być zainicjalizowane przed jakimkolwiek użyciem
if "result_queue" not in st.session_state:
    st.session_state.result_queue = queue.Queue(maxsize=10)
if "zeskanowane" not in st.session_state:
    st.session_state.zeskanowane = {}
if "input_model_manual" not in st.session_state:
    st.session_state.input_model_manual = ""
if "last_scan_message" not in st.session_state:
    st.session_state.last_scan_message = {"text": "", "type": "info"}
if "scanner_active" not in st.session_state:
    st.session_state.scanner_active = False
# `webrtc_processor_instance` nie będzie już globalnie w session_state, 
# będzie tworzony na żądanie przez fabrykę, jeśli skaner jest aktywny.

# --- Kolumna boczna ---
with st.sidebar:
    st.header("⚙️ Ustawienia")
    uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])
    if st.button("🗑️ Wyczyść wszystkie skany", key="clear_scans_sidebar"):
        st.session_state.zeskanowane = {}
        st.session_state.last_scan_message = {"text": "", "type": "info"}
        if "result_queue" in st.session_state: # Sprawdź, zanim użyjesz
            while not st.session_state.result_queue.empty():
                try: st.session_state.result_queue.get_nowait()
                except queue.Empty: break
        st.success("Wszystkie zeskanowane pozycje zostały wyczyszczone.")
        st.rerun()

# --- Główna zawartość ---
if uploaded_file:
    try:
        stany_magazynowe = load_data(uploaded_file)
    except Exception as e:
        st.error(f"Błąd wczytywania pliku: {e}")
        st.stop()

    st.subheader("➕ Dodaj model ręcznie")
    def process_manually_entered_model():
        model = st.session_state.input_model_manual.strip()
        if model:
            count = st.session_state.zeskanowane.get(model, 0) + 1
            st.session_state.zeskanowane[model] = count
            st.session_state.input_model_manual = ""
            st.session_state.last_scan_message = {"text": f"👍 Dodano ręcznie: **{model}** (Nowa ilość: {count})", "type": "success"}
            st.rerun()
    st.text_input("Wpisz model ręcznie i naciśnij Enter:", key="input_model_manual", on_change=process_manually_entered_model, placeholder="Np. Laptop XYZ123")
    st.markdown("---")

    st.subheader("📷 Skaner QR Live")
    if st.button("🔛 Uruchom Skaner" if not st.session_state.scanner_active else "🛑 Zatrzymaj Skaner", key="toggle_scanner"):
        st.session_state.scanner_active = not st.session_state.scanner_active
        msg_text = "Skaner uruchomiony. Skieruj kamerę na kod QR." if st.session_state.scanner_active else "Skaner zatrzymany."
        st.session_state.last_scan_message = {"text": msg_text, "type": "info"}
        st.rerun()

    message_placeholder_scan = st.empty()
    if st.session_state.last_scan_message["text"]:
        msg = st.session_state.last_scan_message
        if msg["type"] == "success": message_placeholder_scan.success(msg["text"], icon="🎉")
        elif msg["type"] == "warning": message_placeholder_scan.warning(msg["text"], icon="⚠️")
        elif msg["type"] == "info": message_placeholder_scan.info(msg["text"], icon="ℹ️")
        elif msg["type"] == "error": message_placeholder_scan.error(msg["text"], icon="❌")

    # Komponent WebRTC Streamer jest tworzony tylko, gdy skaner jest aktywny
    if st.session_state.scanner_active:
        st.info("Skaner jest aktywny. Umieść kod QR w polu widzenia kamery. Zielona ramka oznacza wykrycie.")

        # Fabryka jest teraz definiowana wewnątrz bloku, gdzie mamy pewność, że `result_queue` istnieje
        def app_video_processor_factory_local():
            # Zawsze tworzymy nową instancję procesora, gdy fabryka jest wywoływana
            # i gdy skaner jest aktywny. `streamlit-webrtc` zarządza cyklem życia procesora.
            # Upewnij się, że `result_queue` jest dostępne.
            if "result_queue" not in st.session_state:
                 # To jest ostateczne zabezpieczenie, nie powinno być potrzebne przy poprawnej inicjalizacji na górze
                st.session_state.result_queue = queue.Queue(maxsize=10)
            
            processor = QRScannerProcessor(result_queue=st.session_state.result_queue)
            processor.set_active(True) # Procesor tworzony przez tę fabrykę jest domyślnie aktywny
            return processor

        webrtc_ctx = webrtc_streamer(
            key="qr-live-scanner-active", # Zmieniony klucz, aby uniknąć konfliktów z poprzednimi wersjami
            mode=WebRtcMode.SENDRECV,
            rtc_configuration=RTC_CONFIGURATION,
            video_processor_factory=app_video_processor_factory_local, # Używamy lokalnej fabryki
            media_stream_constraints={"video": {"width": 640, "height": 480, "frameRate": {"ideal": 10, "max": 15}}, "audio": False},
            async_processing=True,
            # desired_playing_state=True # Gdy ten komponent jest renderowany, chcemy, żeby grał
        )

        if webrtc_ctx.state.playing:
            try:
                newly_scanned_codes = []
                # Sprawdź, czy result_queue istnieje, zanim spróbujesz z niej czytać
                if "result_queue" in st.session_state:
                    while not st.session_state.result_queue.empty():
                        scanned_value = st.session_state.result_queue.get_nowait()
                        newly_scanned_codes.append(scanned_value)
                
                if newly_scanned_codes:
                    parts = []
                    changed = False
                    for text in newly_scanned_codes:
                        count = st.session_state.zeskanowane.get(text, 0) + 1
                        st.session_state.zeskanowane[text] = count
                        parts.append(f"**{text}** (ilość: {count})")
                        changed = True
                    if changed:
                        st.session_state.last_scan_message = {"text": f"✅ Zeskanowano: " + ", ".join(parts), "type": "success"}
                        st.rerun()
            except queue.Empty: pass
            except AttributeError:
                 st.error("Błąd wewnętrzny: Problem z dostępem do kolejki wyników skanowania.")
            except Exception as e: st.error(f"Błąd przetwarzania kolejki: {e}")
        elif st.session_state.scanner_active : # Skaner powinien być aktywny, ale kamera nie gra
             st.warning("Kamera nie jest aktywna lub wystąpił problem z połączeniem WebRTC. Spróbuj odświeżyć stronę lub sprawdź uprawnienia kamery w przeglądarce.")
    
    # Wyświetlanie tabeli porównawczej
    if st.session_state.zeskanowane or (uploaded_file and 'stany_magazynowe' in locals() and stany_magazynowe is not None):
        st.markdown("---")
        st.subheader("📊 Porównanie stanów")
        df_display = pd.DataFrame(columns=['model', 'stan', 'zeskanowano', 'różnica']) 
        
        # Sprawdź, czy stany_magazynowe zostały poprawnie załadowane
        magazyn_df_exists = 'stany_magazynowe' in locals() and stany_magazynowe is not None and not stany_magazynowe.empty

        if magazyn_df_exists:
            df_display = stany_magazynowe.copy()
            df_display["zeskanowano"] = 0 
            for idx, row in df_display.iterrows(): # Użyj iterrows zamiast odwoływania się do row_index.name
                model_name = row['model']
                if model_name in st.session_state.zeskanowane:
                    df_display.loc[idx, 'zeskanowano'] = st.session_state.zeskanowane[model_name]
            
            modele_tylko_w_skanach = []
            for skan_model, skan_ilosc in st.session_state.zeskanowane.items():
                if skan_model not in df_display['model'].values: # Sprawdź, czy model jest w wartościach kolumny
                    modele_tylko_w_skanach.append({'model': skan_model, 'stan': 0, 'zeskanowano': skan_ilosc})
            if modele_tylko_w_skanach:
                df_display = pd.concat([df_display, pd.DataFrame(modele_tylko_w_skanach)], ignore_index=True)
            
            # Upewnij się, że kolumny są poprawnego typu
            df_display["zeskanowano"] = df_display["zeskanowano"].fillna(0).astype(int)
            df_display["stan"] = df_display["stan"].fillna(0).astype(int)

        elif st.session_state.zeskanowane: # Tylko skany, brak pliku magazynowego
            df_display = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
            df_display["stan"] = 0
        
        if not df_display.empty:
            df_display["model"] = df_display["model"].astype(str).str.strip()
            df_display = df_display[~df_display["model"].str.lower().isin(["nan", "", "0"])]
            if "stan" not in df_display.columns: df_display["stan"] = 0 # Zabezpieczenie
            if "zeskanowano" not in df_display.columns: df_display["zeskanowano"] = 0 # Zabezpieczenie
            df_display["różnica"] = df_display["zeskanowano"] - df_display["stan"]
            df_display = df_display.sort_values(by=['różnica', 'model'], ascending=[True, True])
        else: 
            if uploaded_file: # Plik wgrany, ale tabela pusta (np. plik Excel pusty)
                 st.info("Brak danych do wyświetlenia. Sprawdź zawartość pliku Excel lub rozpocznij skanowanie.")
            # Jeśli nie ma pliku, komunikat wyświetli się niżej

        # Wyświetl tabelę tylko jeśli nie jest pusta
        if not df_display.empty:
            st.dataframe(df_display.style.applymap(highlight_diff, subset=['różnica']), use_container_width=True, hide_index=True)
            
            excel_buffer = io.BytesIO()
            df_display.to_excel(excel_buffer, index=False, sheet_name="RaportInwentaryzacji", engine='openpyxl')
            excel_buffer.seek(0)
            st.download_button(label="📥 Pobierz raport różnic (Excel)", data=excel_buffer, file_name="raport_inwentaryzacja.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        elif st.session_state.zeskanowane: # Są skany, ale tabela wynikowa jest pusta (np. brak pliku magazynowego)
            st.info("Zeskanowano modele, ale brak danych magazynowych do porównania. Wgraj plik Excel.")
        elif uploaded_file: # Plik wgrany, ale brak skanów i brak danych w pliku
            st.info("Wgrano plik, ale nie zawiera on danych lub nie ma jeszcze zeskanowanych modeli.")


else: # Jeśli uploaded_file is None
    st.info("👋 Witaj! Aby rozpocząć, wgraj plik Excel ze stanem magazynowym z panelu po lewej stronie.")
    st.markdown("Plik powinien zawierać kolumny `model` oraz `stan`.")
    if st.session_state.get("scanner_active", False):
        st.warning("Skaner QR został aktywowany, ale plik Excel nie został jeszcze wgrany. Funkcjonalność będzie ograniczona.")
