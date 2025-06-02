import streamlit as st
import pandas as pd
import io
from PIL import Image
import cv2 
import numpy as np
from collections import Counter 

from pyzbar.pyzbar import decode as pyzbar_decode

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
        raise ValueError("Plik Excel musi zawierać kolumny: 'model' oraz 'stan'.")
    df = df[['model', 'stan']]
    df['model'] = df['model'].astype(str).str.strip()
    df['stan'] = pd.to_numeric(df['stan'], errors='coerce').fillna(0).astype(int)
    return df

# === Funkcja dekodująca WSZYSTKIE QR z obrazu za pomocą pyzbar ===
def decode_all_qrs_from_image_pyzbar(image_bytes_io):
    try:
        pil_img = Image.open(image_bytes_io)
        decoded_objects = pyzbar_decode(pil_img)
        
        detected_texts = []
        if decoded_objects:
            for obj in decoded_objects:
                if obj.data:
                    detected_texts.append(obj.data.decode("utf-8").strip())
        return detected_texts
    except Exception as e:
        # st.warning(f"Błąd dekodowania QR (pyzbar): {e}") # Można włączyć dla debugowania
        return []

st.set_page_config(page_title="📦 Inwentaryzacja (Skan Zdjęć)", layout="wide")
st.title("📦 Inwentaryzacja sprzętu (Skanowanie ze Zdjęcia)")

# --- Kolumna boczna ---
with st.sidebar:
    st.header("⚙️ Ustawienia")
    uploaded_file = st.file_uploader("Wgraj plik Excel ze stanem magazynowym", type=["xlsx"])
    if st.button("🗑️ Wyczyść wszystkie skany", key="clear_scans_photo_all"):
        st.session_state.zeskanowane = {}
        st.session_state.last_scan_message_photo_all = {"text": "", "type": "info"}
        if "show_camera_photo_all" in st.session_state:
            st.session_state.show_camera_photo_all = False
        st.success("Wszystkie zeskanowane pozycje zostały wyczyszczone.")
        st.rerun()

# --- Inicjalizacja stanu sesji ---
if "zeskanowane" not in st.session_state:
    st.session_state.zeskanowane = {}
if "input_model_manual" not in st.session_state:
    st.session_state.input_model_manual = ""
if "last_scan_message_photo_all" not in st.session_state:
    st.session_state.last_scan_message_photo_all = {"text": "", "type": "info"}
if "show_camera_photo_all" not in st.session_state:
    st.session_state.show_camera_photo_all = False

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
            st.session_state.last_scan_message_photo_all = {"text": f"👍 Dodano ręcznie: **{model}** (Nowa ilość: {count})", "type": "success"}
            # st.rerun() # Zmiana session_state i on_change powinny wystarczyć
    st.text_input(
        "Wpisz model ręcznie i naciśnij Enter:", 
        key="input_model_manual_photo_all", # Upewnij się, że klucz jest unikalny
        on_change=process_manually_entered_model, 
        placeholder="Np. Laptop XYZ123"
        # autofocus został usunięty
    )
    st.markdown("---")

    st.subheader("📸 Skaner QR (Zrób Zdjęcie - wszystkie kody)")
    
    camera_button_label = "📷 Uruchom Kamerę" if not st.session_state.show_camera_photo_all else "📸 Ukryj Kamerę"
    if st.button(camera_button_label, key="toggle_camera_button_photo_all"):
        st.session_state.show_camera_photo_all = not st.session_state.show_camera_photo_all
        st.session_state.last_scan_message_photo_all = {"text": "", "type": "info"}
        st.rerun()

    message_placeholder_photo_all = st.empty()
    if st.session_state.last_scan_message_photo_all["text"]:
        msg = st.session_state.last_scan_message_photo_all
        if msg["type"] == "success": message_placeholder_photo_all.success(msg["text"], icon="🎉")
        elif msg["type"] == "warning": message_placeholder_photo_all.warning(msg["text"], icon="⚠️")
        elif msg["type"] == "info": message_placeholder_photo_all.info(msg["text"], icon="ℹ️")

    if st.session_state.show_camera_photo_all:
        st.info("Ustaw kody QR przed obiektywem i kliknij 'Take photo'. Wszystkie wykryte kody ze zdjęcia zostaną dodane.", icon="🎯")
        
        img_file_buffer = st.camera_input(
            "Zrób zdjęcie kodów QR", 
            key="qr_camera_photo_all_shot", 
            label_visibility="collapsed"
        )

        if img_file_buffer is not None:
            bytes_data = img_file_buffer.getvalue()
            with st.spinner("🔍 Przetwarzanie zdjęcia..."):
                decoded_qr_texts_list = decode_all_qrs_from_image_pyzbar(io.BytesIO(bytes_data))

            if decoded_qr_texts_list:
                codes_on_photo_counts = Counter(decoded_qr_texts_list)
                added_models_summary = []
                for qr_text, num_on_photo in codes_on_photo_counts.items():
                    current_inventory_count = st.session_state.zeskanowane.get(qr_text, 0)
                    new_inventory_count = current_inventory_count + num_on_photo
                    st.session_state.zeskanowane[qr_text] = new_inventory_count
                    added_models_summary.append(f"**{qr_text}** (+{num_on_photo}, nowa ilość: {new_inventory_count})")
                
                st.session_state.last_scan_message_photo_all = {
                    "text": f"✅ Zeskanowano i dodano: {'; '.join(added_models_summary)}", 
                    "type": "success"
                }
            elif img_file_buffer is not None: 
                st.session_state.last_scan_message_photo_all = {
                    "text": "⚠️ Nie udało się odczytać żadnego kodu QR ze zdjęcia. Spróbuj ponownie.", 
                    "type": "warning"
                }
            st.rerun() 

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
                df_display.loc[idx, 'zeskanowano'] = st.session_state.zeskanowane.get(model_name, 0)
            
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
            if uploaded_file: st.info("Brak danych do wyświetlenia. Sprawdź zawartość pliku Excel lub rozpocznij skanowanie.")

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
    if st.session_state.get("show_camera_photo_all", False):
        st.warning("Plik Excel nie jest załadowany. Skanowanie QR jest obecnie niedostępne.")
