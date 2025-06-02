import streamlit as st
import pandas as pd
import io
from PIL import Image
import cv2
import numpy as np
import time
import queue

from pyzbar.pyzbar import decode as pyzbar_decode

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
        raise ValueError("Plik Excel musi zawierać kolumny: 'model' oraz 'stan'. Sprawdź nazwy kolumn i ewentualne spacje.")
    df = df[['model', 'stan']]
    df['model'] = df['model'].astype(str).str.strip()
    df['stan'] = pd.to_numeric(df['stan'], errors='coerce').fillna(0).astype(int)
    return df

# === Procesor klatek wideo dla streamlit-webrtc z pyzbar ===
class QRScannerProcessorPyzbar(VideoProcessorBase):
    def __init__(self, result_queue: queue.Queue):
        self.last_scanned_value = None
        self.last_scan_time = 0
        self.scan_cooldown_seconds = 2.0
        self.result_queue = result_queue
        self._active = True

    def set_active(self, active: bool):
        self._active = active

    def recv(self, frame):
        if not self._active or self.result_queue is None:
            return frame

        img_bgr = frame.to_ndarray(format="bgr24")
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        decoded_text_display = None
        try:
            decoded_objects = pyzbar_decode(pil_img)
            current_time = time.time()
            for obj in decoded_objects:
                decoded_text = obj.data.decode("utf-8")
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
                    
                    (x, y, w, h) = obj.rect
                    cv2.rectangle(img_bgr, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    if decoded_text_display:
                        cv2.putText(img_bgr, decoded_text_display, (x, y - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
                    break 
            return frame.from_ndarray(img_bgr, format="bgr24")
        except Exception as e:
            return frame.from_ndarray(img_bgr, format="bgr24")

# --- Główna aplikacja Streamlit ---
st.set_page_config(page_title="📦 Inwentaryzacja Sprzętu (Live Scan)", layout="wide")
st.title("📦 Inwentaryzacja sprzętu (Skanowanie Live)")

RTC_CONFIGURATION = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

# --- Inicjalizacja stanu sesji ---
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
            st.session_state.input_model_manual = "" # Czyść pole po przetworzeniu
            st.session_state.last_scan_message = {"text": f"👍 Dodano ręcznie: **{model}** (Nowa ilość: {count})", "type": "success"}
            # Nie ma potrzeby st.rerun() tutaj, on_change i zmiana session_state to zrobią
    st.text_input(
        "Wpisz model ręcznie i naciśnij Enter:", 
        key="input_model_manual", 
        on_change=process_manually_entered_model, 
        placeholder="Np. Laptop XYZ123",
        autofocus=not st.session_state.scanner_active # Ustaw autofocus tylko jeśli skaner nie jest aktywny
                                                      # lub przy pierwszym ładowaniu tej sekcji
    )
    st.markdown("---")

    st.subheader("📷 Skaner QR Live (z pyzbar)")
    
    scanner_button_label = "🔛 Uruchom Skaner" if not st.session_state.scanner_active else "🛑 Zatrzymaj Skaner"
    if st.button(scanner_button_label, key="toggle_scanner"):
        st.session_state.scanner_active = not st.session_state.scanner_active
        msg_text = "Skaner uruchomiony. Skieruj kamerę na kod QR." if st.session_state.scanner_active else "Skaner zatrzymany."
        st.session_state.last_scan_message = {"text": msg_text, "type": "info"}
        st.rerun() # Rerun jest OK po akcji przycisku

    message_placeholder_scan = st.empty()
    if st.session_state.last_scan_message["text"]:
        msg = st.session_state.last_scan_message
        if msg["type"] == "success": message_placeholder_scan.success(msg["text"], icon="🎉")
        elif msg["type"] == "warning": message_placeholder_scan.warning(msg["text"], icon="⚠️")
        elif msg["type"] == "info": message_placeholder_scan.info(msg["text"], icon="ℹ️")
        elif msg["type"] == "error": message_placeholder_scan.error(msg["text"], icon="❌")

    if st.session_state.scanner_active:
        st.info("Próba uruchomienia kamery... Upewnij się, że przeglądarka ma uprawnienia dostępu do kamery.", icon="📸")

        def app_video_processor_factory_local_pyzbar():
            if "result_queue" not in st.session_state:
                st.session_state.result_queue = queue.Queue(maxsize=10) 
            processor = QRScannerProcessorPyzbar(result_queue=st.session_state.result_queue)
            processor.set_active(True) 
            return processor
        
        desired_play_state = st.session_state.scanner_active

        webrtc_ctx = webrtc_streamer(
            key="qr-live-scanner-pyzbar", 
            mode=WebRtcMode.SENDRECV,
            rtc_configuration=RTC_CONFIGURATION,
            video_processor_factory=app_video_processor_factory_local_pyzbar,
            media_stream_constraints={"video": {"width": 640, "height": 480, "frameRate": {"ideal": 10, "max": 15}}, "audio": False},
            async_processing=True,
            desired_playing_state=desired_play_state
        )

        if webrtc_ctx:
            if webrtc_ctx.state.playing:
                try:
                    newly_scanned_codes = []
                    if "result_queue" in st.session_state and st.session_state.result_queue is not None:
                        while not st.session_state.result_queue.empty():
                            scanned_value = st.session_state.result_queue.get_nowait()
                            newly_scanned_codes.append(scanned_value)
                    
                    if newly_scanned_codes:
                        parts = []
                        changed_data_in_run = False
                        for text in newly_scanned_codes:
                            count = st.session_state.zeskanowane.get(text, 0) + 1
                            st.session_state.zeskanowane[text] = count
                            parts.append(f"**{text}** (ilość: {count})")
                            changed_data_in_run = True
                        if changed_data_in_run:
                            st.session_state.last_scan_message = {"text": f"✅ Zeskanowano: " + ", ".join(parts), "type": "success"}
                            # Usunięto st.rerun() stąd. Zmiana session_state powinna wystarczyć.
                except queue.Empty: pass
                except AttributeError: st.error("Błąd wewnętrzny: Problem z dostępem do kolejki wyników skanowania.")
                except Exception as e: st.error(f"Błąd przetwarzania kolejki: {e}")

            elif webrtc_ctx.state.error_message:
                 st.error(f"Błąd WebRTC: {webrtc_ctx.state.error_message}")
            elif not desired_play_state:
                pass 
            else: 
                st.warning(
                    f"Stan kamery: {webrtc_ctx.state.signaling_state} / {webrtc_ctx.state.ice_connection_state} / {webrtc_ctx.state.connection_state}. "
                    "Oczekiwanie na połączenie lub dostęp do kamery. "
                    "Sprawdź uprawnienia kamery w przeglądarce i połączenie sieciowe. "
                    "Jeśli problem będzie się powtarzał, odśwież stronę.", icon="⏳")
                if hasattr(webrtc_ctx.state, 'ice_gathering_state') and webrtc_ctx.state.ice_gathering_state == 'failed':
                    st.caption("Problem z zbieraniem kandydatów ICE. Może to być problem z siecią/firewallem lub konfiguracją STUN/TURN.")
        else:
            st.error("Nie udało się zainicjalizować komponentu kamery WebRTC. Sprawdź logi aplikacji.")
    
    # Wyświetlanie tabeli porównawczej
    magazyn_df_exists_and_loaded = 'stany_magazynowe' in locals() and stany_magazynowe is not None

    if st.session_state.zeskanowane or (uploaded_file and magazyn_df_exists_and_loaded):
        st.markdown("---")
        st.subheader("📊 Porównanie stanów")
        df_display = pd.DataFrame(columns=['model', 'stan', 'zeskanowano', 'różnica']) 
        
        if magazyn_df_exists_and_loaded and not stany_magazynowe.empty:
            df_display = stany_magazynowe.copy()
            df_display["zeskanowano"] = 0 
            for idx in range(len(df_display)):
                model_name = df_display.loc[idx, 'model']
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
        else: 
            if uploaded_file:
                 st.info("Brak danych do wyświetlenia. Sprawdź zawartość pliku Excel lub rozpocznij skanowanie.")

        if not df_display.empty:
            st.dataframe(df_display.style.applymap(highlight_diff, subset=['różnica']), use_container_width=True, hide_index=True)
            
            excel_buffer = io.BytesIO()
            df_display.to_excel(excel_buffer, index=False, sheet_name="RaportInwentaryzacji", engine='openpyxl')
            excel_buffer.seek(0)
            st.download_button(label="📥 Pobierz raport różnic (Excel)", data=excel_buffer, file_name="raport_inwentaryzacja.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        elif st.session_state.zeskanowane:
            st.info("Zeskanowano modele, ale brak danych magazynowych do porównania. Wgraj plik Excel.")
        elif uploaded_file:
            st.info("Wgrano plik, ale nie zawiera on danych lub nie ma jeszcze zeskanowanych modeli.")
else:
    st.info("👋 Witaj! Aby rozpocząć, wgraj plik Excel ze stanem magazynowym z panelu po lewej stronie.")
    st.markdown("Plik Excel powinien zawierać kolumny `model` oraz `stan`.")
    if st.session_state.get("scanner_active", False):
        st.warning("Skaner QR został aktywowany, ale plik Excel nie został jeszcze wgrany. Funkcjonalność będzie ograniczona.")
