import streamlit as st
import pandas as pd
import io
from PIL import Image
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
        decoded_text_display = None

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


# --- Główna aplikacja Streamlit ---
st.set_page_config(page_title="📦 Inwentaryzacja Sprzętu (Live Scan)", layout="wide")
st.title("📦 Inwentaryzacja sprzętu (Skanowanie Live)")

RTC_CONFIGURATION = RTCConfiguration({
    "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
})

# --- Inicjalizacja stanu sesji ---
# KLUCZOWE: Inicjalizacja kolejki na samym początku
if "result_queue" not in st.session_state:
    st.session_state.result_queue = queue.Queue(maxsize=10) # Zwiększona trochę maxsize na wszelki wypadek

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
        # Wyczyść kolejkę, jeśli jest używana
        if "result_queue" in st.session_state:
            while not st.session_state.result_queue.empty():
                try:
                    st.session_state.result_queue.get_nowait()
                except queue.Empty:
                    break
        st.success("Wszystkie zeskanowane pozycje zostały wyczyszczone.")
        st.rerun()


# --- Główna zawartość ---
if uploaded_file:
    try:
        stany_magazynowe = load_data(uploaded_file)
    except Exception as e:
        st.error(f"Błąd wczytywania pliku: {e}")
        st.stop()

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
        if not st.session_state.scanner_active:
            st.session_state.last_scan_message = {"text": "Skaner zatrzymany.", "type": "info"}
        else:
             st.session_state.last_scan_message = {"text": "Skaner uruchomiony. Skieruj kamerę na kod QR.", "type": "info"}
        st.rerun()

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
        
        def processor_factory():
            return QRScannerProcessor(result_queue=st.session_state.result_queue)

        webrtc_ctx = webrtc_streamer(
            key="qr-live-scanner",
            video_processor_factory=processor_factory,
            rtc_configuration=RTC_CONFIGURATION,
            media_stream_constraints={"video": {"width": 640, "height": 480, "frameRate": {"ideal": 10, "max": 15}}, "audio": False},
            async_processing=True,
        )
        
        if webrtc_ctx.state.playing:
            try:
                newly_scanned_codes = []
                while not st.session_state.result_queue.empty():
                    scanned_value = st.session_state.result_queue.get_nowait()
                    newly_scanned_codes.append(scanned_value)
                
                if newly_scanned_codes:
                    all_updated_models_message_parts = []
                    changed_data = False
                    for decoded_text in newly_scanned_codes:
                        # Sprawdź, czy ten kod nie został właśnie dodany w tej samej paczce (jeśli kolejka się szybko zapełni)
                        # To bardziej dla bezpieczeństwa, cooldown w procesorze powinien to łapać
                        old_count = st.session_state.zeskanowane.get(decoded_text, 0)
                        current_count = old_count + 1
                        st.session_state.zeskanowane[decoded_text] = current_count
                        all_updated_models_message_parts.append(f"**{decoded_text}** (ilość: {current_count})")
                        changed_data = True
                    
                    if changed_data:
                        st.session_state.last_scan_message = {
                            "text": f"✅ Zeskanowano: " + ", ".join(all_updated_models_message_parts),
                            "type": "success"
                        }
                        st.rerun()
            except queue.Empty:
                pass
            except Exception as e: # Logowanie innych błędów z pętli kolejki
                st.error(f"Błąd przetwarzania kolejki: {e}")


    # Wyświetlanie tabeli porównawczej
    if st.session_state.zeskanowane or uploaded_file:
        st.markdown("---")
        st.subheader("📊 Porównanie stanów")

        df_display = pd.DataFrame(columns=['model', 'stan', 'zeskanowano', 'różnica']) 

        if not stany_magazynowe.empty:
            # Utwórz kopię danych magazynowych do wyświetlenia
            df_display = stany_magazynowe.copy()
            # Zainicjuj kolumnę 'zeskanowano' zerami dla wszystkich modeli z magazynu
            df_display["zeskanowano"] = 0 
            
            # Zaktualizuj 'zeskanowano' dla modeli, które są w magazynie i zostały zeskanowane
            for model_magazyn, row_index in df_display.iterrows():
                model_name = row_index['model']
                if model_name in st.session_state.zeskanowane:
                    df_display.loc[row_index.name, 'zeskanowano'] = st.session_state.zeskanowane[model_name]

            # Dodaj modele, które zostały zeskanowane, ale nie ma ich w pliku magazynowym
            modele_tylko_w_skanach = []
            for skan_model, skan_ilosc in st.session_state.zeskanowane.items():
                if skan_model not in df_display['model'].values:
                    modele_tylko_w_skanach.append({'model': skan_model, 'stan': 0, 'zeskanowano': skan_ilosc})
            
            if modele_tylko_w_skanach:
                df_nowe_skany = pd.DataFrame(modele_tylko_w_skanach)
                df_display = pd.concat([df_display, df_nowe_skany], ignore_index=True)

            df_display["zeskanowano"] = df_display["zeskanowano"].fillna(0).astype(int)
            df_display["stan"] = df_display["stan"].fillna(0).astype(int)

        elif st.session_state.zeskanowane: # Tylko skany, brak pliku magazynowego
            df_display = pd.DataFrame(list(st.session_state.zeskanowane.items()), columns=["model", "zeskanowano"])
            df_display["stan"] = 0
        
        if not df_display.empty:
            df_display["model"] = df_display["model"].astype(str).str.strip()
            df_display = df_display[~df_display["model"].str.lower().isin(["nan", "", "0"])] # Usunięcie niepoprawnych modeli
            
            # Upewnij się, że kolumny istnieją przed obliczeniem różnicy
            if "stan" not in df_display.columns: df_display["stan"] = 0
            if "zeskanowano" not in df_display.columns: df_display["zeskanowano"] = 0

            df_display["różnica"] = df_display["zeskanowano"] - df_display["stan"]
            df_display = df_display.sort_values(by=['różnica', 'model'], ascending=[True, True])
        else:
             st.info("Brak danych do wyświetlenia. Wgraj plik lub rozpocznij skanowanie.")


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
        elif st.session_state.zeskanowane: # Są skany, ale brak pliku lub plik pusty
             st.info("Wgraj plik Excel ze stanem magazynowym, aby zobaczyć pełne porównanie.")
else: # if not uploaded_file
    st.info("👋 Witaj! Aby rozpocząć, wgraj plik Excel ze stanem magazynowym z panelu po lewej stronie.")
    st.markdown("Plik powinien zawierać kolumny `model` oraz `stan`.")
    # Można dodać komunikat, że skaner QR nie jest dostępny bez załadowanego pliku
    if st.session_state.get("scanner_active", False): # Użyj .get() dla bezpieczeństwa
        st.warning("Skaner QR jest aktywny, ale plik Excel nie został jeszcze wgrany. Dane nie będą porównywane ze stanem magazynowym.")
