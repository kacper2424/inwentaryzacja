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
        self.scan_cooldown_seconds = 2
        self.result_queue = result_queue
        self.active = True # Domyślnie aktywny, można kontrolować

    def set_active(self, active: bool):
        self.active = active

    def recv(self, frame):
        if not self.active or self.result_queue is None: # Dodatkowe zabezpieczenie
            return frame # Zwróć oryginalną klatkę, jeśli nieaktywny

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
                        pass # Kolejka pełna, zignoruj
                    
                    self.last_scanned_value = decoded_text
                    self.last_scan_time = current_time
                    decoded_text_display = f"OK: {decoded_text[:20]}..." if len(decoded_text) > 20 else f"OK: {decoded_text}"
                else:
                    decoded_text_display = f"Scanned: {decoded_text[:20]}..." if len(decoded_text) > 20 else f"Scanned: {decoded_text}"

                if points is not None:
                    contour = np.array(points[0], dtype=np.int32)
                    cv2.polylines(img, [contour], isClosed=True, color=(0, 255, 0), thickness=3, lineType=cv2.LINE_AA)
                    if decoded_text_display:
                        text_pos = (contour[0][0], contour[0][1] - 10) if len(contour) > 0 else (10,30)
                        cv2.putText(img, decoded_text_display, text_pos,
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
            
            return frame.from_ndarray(img, format="bgr24")
        except Exception as e:
            # W przypadku błędu w przetwarzaniu, zwróć oryginalną klatkę, aby streamer działał dalej
            # Można tu dodać logowanie błędu
            # print(f"Error in QRScannerProcessor: {e}")
            return frame


# --- Główna aplikacja Streamlit ---
st.set_page_config(page_title="📦 Inwentaryzacja Sprzętu (Live Scan)", layout="wide")
st.title("📦 Inwentaryzacja sprzętu (Skanowanie Live)")

RTC_CONFIGURATION = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

# --- Inicjalizacja stanu sesji ---
# Upewniamy się, że wszystkie klucze session_state są zainicjalizowane na początku
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
if "webrtc_processor_instance" not in st.session_state: # Do przechowywania instancji procesora
    st.session_state.webrtc_processor_instance = None

# --- Kolumna boczna ---
with st.sidebar:
    st.header("⚙️ Ustawienia")
    uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])
    if st.button("🗑️ Wyczyść wszystkie skany", key="clear_scans_sidebar"):
        st.session_state.zeskanowane = {}
        st.session_state.last_scan_message = {"text": "", "type": "info"}
        if "result_queue" in st.session_state:
            while not st.session_state.result_queue.empty():
                try: st.session_state.result_queue.get_nowait()
                except queue.Empty: break
        st.success("Wszystkie zeskanowane pozycje zostały wyczyszczone.")
        st.rerun()


# --- Fabryka procesora wideo ---
# Ta funkcja będzie zawsze wywoływana przez streamlit-webrtc
# Zarządzamy instancją procesora i jej aktywnością w session_state
def app_video_processor_factory():
    if st.session_state.webrtc_processor_instance is None:
        # Upewnij się, że result_queue na pewno istnieje przed stworzeniem procesora
        if "result_queue" not in st.session_state:
            st.session_state.result_queue = queue.Queue(maxsize=10) # Ostateczne zabezpieczenie
        st.session_state.webrtc_processor_instance = QRScannerProcessor(result_queue=st.session_state.result_queue)
    
    # Ustaw stan aktywności procesora na podstawie st.session_state.scanner_active
    # To jest kluczowe: procesor istnieje, ale działa tylko, gdy scanner_active jest True
    is_scanner_actually_active = st.session_state.get("scanner_active", False) and uploaded_file is not None
    st.session_state.webrtc_processor_instance.set_active(is_scanner_actually_active)
    
    return st.session_state.webrtc_processor_instance


# --- Komponent WebRTC Streamer ---
# Definiujemy go raz, w głównym przepływie. Jego zachowanie będzie kontrolowane przez
# stan aktywności procesora i warunkowe wyświetlanie w UI.
webrtc_ctx = webrtc_streamer(
    key="qr-live-scanner-main", # Unikalny klucz
    mode=WebRtcMode.SENDRECV, # Musi odbierać wideo i wysyłać przetworzone
    rtc_configuration=RTC_CONFIGURATION,
    video_processor_factory=app_video_processor_factory,
    media_stream_constraints={"video": {"width": 640, "height": 480, "frameRate": {"ideal": 10, "max": 15}}, "audio": False},
    async_processing=True,
    # desired_playing_state=st.session_state.get("scanner_active", False) # Można próbować kontrolować stan odtwarzania
)

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
        # Ważne: aktualizujemy stan aktywności istniejącego procesora
        if st.session_state.webrtc_processor_instance:
            st.session_state.webrtc_processor_instance.set_active(st.session_state.scanner_active)
        st.rerun()

    message_placeholder_scan = st.empty()
    if st.session_state.last_scan_message["text"]:
        msg = st.session_state.last_scan_message
        if msg["type"] == "success": message_placeholder_scan.success(msg["text"], icon="🎉")
        elif msg["type"] == "warning": message_placeholder_scan.warning(msg["text"], icon="⚠️")
        elif msg["type"] == "info": message_placeholder_scan.info(msg["text"], icon="ℹ️")
        elif msg["type"] == "error": message_placeholder_scan.error(msg["text"], icon="❌")

    # Wyświetl informację o stanie skanera tylko jeśli jest aktywny
    if st.session_state.scanner_active:
        if webrtc_ctx.state.playing:
            st.info("Skaner jest aktywny. Umieść kod QR w polu widzenia kamery. Zielona ramka oznacza wykrycie.")
            # Przetwarzanie kolejki
            try:
                newly_scanned_codes = []
                while not st.session_state.result_queue.empty(): # Sprawdź, czy kolejka na pewno istnieje
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
                        st.rerun() # Rerun tylko jeśli coś się zmieniło
            except queue.Empty: pass
            except AttributeError: # Jeśli kolejka nie istnieje, co nie powinno się zdarzyć
                st.error("Błąd wewnętrzny: Kolejka wyników skanowania nie jest dostępna.")
            except Exception as e: st.error(f"Błąd przetwarzania kolejki: {e}")
        else:
            st.warning("Kamera nie jest aktywna lub wystąpił problem z połączeniem WebRTC. Spróbuj odświeżyć stronę lub sprawdź uprawnienia kamery.")
    else:
        # Jeśli skaner nie jest aktywny, można wyświetlić placeholder lub nic
        pass


    # Wyświetlanie tabeli porównawczej (logika bez zmian, ale upewnij się, że stany_magazynowe istnieje)
    if st.session_state.zeskanowane or (uploaded_file and 'stany_magazynowe' in locals()):
        st.markdown("---")
        st.subheader("📊 Porównanie stanów")
        df_display = pd.DataFrame(columns=['model', 'stan', 'zeskanowano', 'różnica']) 
        if 'stany_magazynowe' in locals() and not stany_magazynowe.empty:
            df_display = stany_magazynowe.copy()
            df_display["zeskanowano"] = 0 
            for idx, row in df_display.iterrows():
                model_name = row['model']
                if model_name in st.session_state.zeskanowane:
                    df_display.loc[idx, 'zeskanowano'] = st.session_state.zeskanowane[model_name]
            
            modele_tylko_w_skanach = []
            for skan_model, skan_ilosc in st.session_state.zeskanowane.items():
                if skan_model not in df_display['model'].values:
                    modele_tylko_w_skanach.append({'model': skan_model, 'stan': 0, 'zeskanowano': skan_ilosc})
            if modele_tylko_w_skanach:
                df_display = pd.concat([df_display, pd.DataFrame(modele_tylko_w_skanach)], ignore_index=True)
            df_display["zeskanowano"] = df_display["zeskanowano"].fillna(0).astype(int)
            df_display["stan"] = df_display["stan"].fillna(0).astype(int)
        elif st.session_state.zeskanowane:
            df_display = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
            df_display["stan"] = 0
        
        if not df_display.empty:
            df_display["model"] = df_display["model"].astype(str).str.strip()
            df_display = df_display[~df_display["model"].str.lower().isin(["nan", "", "0"])]
            if "stan" not in df_display.columns: df_display["stan"] = 0
            if "zeskanowano" not in df_display.columns: df_display["zeskanowano"] = 0
            df_display["różnica"] = df_display["zeskanowano"] - df_display["stan"]
            df_display = df_display.sort_values(by=['różnica', 'model'], ascending=[True, True])
        else: st.info("Brak danych do wyświetlenia. Wgraj plik lub rozpocznij skanowanie.")

        st.dataframe(df_display.style.applymap(highlight_diff, subset=['różnica']), use_container_width=True, hide_index=True)
        if not df_display.empty:
            excel_buffer = io.BytesIO()
            df_display.to_excel(excel_buffer, index=False, sheet_name="RaportInwentaryzacji", engine='openpyxl')
            excel_buffer.seek(0)
            st.download_button(label="📥 Pobierz raport różnic (Excel)", data=excel_buffer, file_name="raport_inwentaryzacja.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        elif st.session_state.zeskanowane: st.info("Wgraj plik Excel ze stanem magazynowym, aby zobaczyć pełne porównanie.")
else:
    st.info("👋 Witaj! Aby rozpocząć, wgraj plik Excel ze stanem magazynowym z panelu po lewej stronie.")
    st.markdown("Plik powinien zawierać kolumny `model` oraz `stan`.")
    if st.session_state.get("scanner_active", False):
        st.warning("Skaner QR jest aktywny, ale plik Excel nie został jeszcze wgrany. Dane nie będą porównywane ze stanem magazynowym.")
