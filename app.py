import streamlit as st
import pandas as pd
import json
import re
from datetime import datetime, timedelta
import google.generativeai as genai

# ==========================================
# 🔑 CONFIGURATION
# ==========================================
# ⚠️ SECURITY NOTE: For a real app, use st.secrets.
GEMINI_API_KEY = "AIzaSyAkK97arUum4ADBRZV2TbYDWg-GF1rDSAg"  # <--- PASTE YOUR KEY HERE

# Configure Gemini
try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error(f"Error configuring Gemini: {e}")

# ==========================================
# 🎨 CUSTOM CSS (STYLING)
# ==========================================


def load_custom_styles():
    st.markdown("""
        <style>
        /* Custom Style for the Chat Button in Sidebar */
        div[data-testid="stSidebar"] .stButton > button {
            background: linear-gradient(90deg, #6a11cb 0%, #2575fc 100%);
            color: white;
            border: none;
            font-weight: bold;
            box-shadow: 0px 4px 10px rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
        }
        div[data-testid="stSidebar"] .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0px 6px 15px rgba(0, 0, 0, 0.3);
            color: white;
        }
        
        /* Chat Bubble Improvements */
        .stChatMessage {
            background-color: transparent; 
        }
        </style>
    """, unsafe_allow_html=True)

# ==========================================
# 📂 PART 1: DATA MANAGER (READ & WRITE)
# ==========================================


class DataManager:
    HISTORY_FILE = "pantry_history.json"
    CATALOG_FILE = "products.json"

    @staticmethod
    def load_catalog():
        try:
            with open(DataManager.CATALOG_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    # NEW: Method to save the updated catalog
    @staticmethod
    def save_catalog(catalog_data):
        with open(DataManager.CATALOG_FILE, 'w') as f:
            json.dump(catalog_data, f, indent=4)

    @staticmethod
    def load_history():
        try:
            with open(DataManager.HISTORY_FILE, 'r') as f:
                raw_data = json.load(f)

            processed_data = []
            today = datetime.now()

            for entry in raw_data:
                # Handle simulated dates vs real dates
                if 'buy_date_offset' in entry:
                    buy_date = today + timedelta(days=entry['buy_date_offset'])
                    expiry_date = today + \
                        timedelta(days=entry['expiry_offset'])
                else:
                    # Handle string formats from saved JSON
                    try:
                        buy_date = datetime.strptime(
                            entry['buy_date'], "%Y-%m-%d")
                        expiry_date = datetime.strptime(
                            entry['expiry_date'], "%Y-%m-%d")
                    except TypeError:
                        # Fallback if already datetime objects in session (rare edge case)
                        buy_date = entry['buy_date']
                        expiry_date = entry['expiry_date']

                processed_data.append({
                    "item": entry['item'],
                    "buy_date": buy_date,
                    "expiry_date": expiry_date,
                    "status": entry['status']
                })
            return processed_data
        except FileNotFoundError:
            return []

    @staticmethod
    def save_history(pantry_data):
        serializable_data = []
        for entry in pantry_data:
            serializable_data.append({
                "item": entry['item'],
                "buy_date": entry['buy_date'].strftime("%Y-%m-%d"),
                "expiry_date": entry['expiry_date'].strftime("%Y-%m-%d"),
                "status": entry['status']
            })

        with open(DataManager.HISTORY_FILE, 'w') as f:
            json.dump(serializable_data, f, indent=4)


# Load Static Knowledge Base
PRODUCT_CATALOG = DataManager.load_catalog()
ALL_PRODUCTS = {}
for cat, items in PRODUCT_CATALOG.items():
    for name, details in items.items():
        ALL_PRODUCTS[name] = details
        ALL_PRODUCTS[name]['category'] = cat

# ==========================================
# 🤖 PART 2: THE AGENT LOGIC
# ==========================================


class SmartAgent:
    def __init__(self):
        if 'pantry' not in st.session_state:
            st.session_state.pantry = DataManager.load_history()
        if 'shopping_list' not in st.session_state:
            st.session_state.shopping_list = []
        if 'pending_suggestion' not in st.session_state:
            st.session_state.pending_suggestion = None
        # Chat History for Gemini
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
        # State for Chat-based Adding Flow
        if "add_flow_item" not in st.session_state:
            st.session_state.add_flow_item = None

    def get_simulation_date(self):
        return st.session_state.get('sim_date', datetime.now())

    def check_expiry_status(self):
        current_date = self.get_simulation_date()
        alerts = []
        for entry in st.session_state.pantry:
            days_left = (entry['expiry_date'] - current_date).days
            if days_left < 0:
                entry['status'] = "Expired"
                alerts.append(f"❌ **{entry['item']}** has expired!")
            elif days_left <= 2:
                entry['status'] = "Critical"
                alerts.append(
                    f"⚠️ **{entry['item']}** expires in {days_left} days!")
            elif days_left <= 5:
                entry['status'] = "Expiring Soon"
                alerts.append(
                    f"⏳ **{entry['item']}** expires in {days_left} days.")
            else:
                entry['status'] = "Good"
        return alerts

    def check_pantry_stock(self, item_name):
        count = 0
        for entry in st.session_state.pantry:
            if entry['item'] == item_name and entry['status'] in ['Good', 'Expiring Soon', 'Critical']:
                count += 1
        return count

    def predict_needs(self):
        suggestions = []
        current_date = self.get_simulation_date()
        suggested_items = set()

        for entry in st.session_state.pantry:
            if entry['item'] in suggested_items:
                continue

            days_since_buy = (current_date - entry['buy_date']).days
            details = ALL_PRODUCTS.get(entry['item'])

            if details:
                cat = details['category']
                msg = None

                if cat == "Dairy & Chill" and days_since_buy >= 7:
                    msg = f"🥛 It's been {days_since_buy} days since you bought **{entry['item']}**. Need more?"
                elif cat == "Bakery & Snacks" and days_since_buy >= 4:
                    msg = f"🍞 Your **{entry['item']}** might be finished by now. Restock?"
                elif cat == "Rice & Grains" and days_since_buy >= 30:
                    msg = f"🍚 It's been a month since you bought **{entry['item']}**. Checking stock?"
                elif cat == "Produce" and days_since_buy >= 7:
                    msg = f"🥦 Fresh veggies like **{entry['item']}** might need replacing."
                elif cat == "Beverages" and days_since_buy >= 14:
                    msg = f"🥤 Running low on **{entry['item']}**?"
                elif cat == "Pantry Staples" and days_since_buy >= 60:
                    msg = f"🧂 Check your **{entry['item']}** supply."

                if msg:
                    suggestions.append(msg)
                    suggested_items.add(entry['item'])

        return suggestions

    def analyze_cart_add(self, item_name):
        details = ALL_PRODUCTS.get(item_name)
        if not details:
            return None
        if not details['healthy'] and details['alt']:
            return details['alt']
        return None

    def add_item(self, item_name):
        details = ALL_PRODUCTS.get(item_name)
        if details:
            st.session_state.shopping_list.append({
                "item": item_name,
                "category": details['category'],
                "price": details['price'],
                "status": "Pending"
            })
        else:
            st.error(f"⚠️ Database Error: '{item_name}' not found.")

    # --- AI: EXTRACT PRICE & DAYS FROM USER TEXT ---
    def extract_details_from_text(self, text):
        prompt = f"""
        Extract the 'price' (number) and 'days' (number) from this text: "{text}".
        If missing, return null.
        Return JSON: {{ "price": number_or_null, "days": number_or_null }}
        """
        try:
            response = model.generate_content(prompt)
            cleaned = response.text.replace(
                "```json", "").replace("```", "").strip()
            return json.loads(cleaned)
        except:
            return {"price": None, "days": None}

    # NEW: Updated to strict category rules
    def analyze_new_product(self, name, current_products_list, existing_categories):
        prompt = f"""
        I am adding a new product: "{name}".
        
        Current Database items: {current_products_list}
        Existing Categories: {existing_categories}
        
        Task:
        1. Is "{name}" healthy? (true/false)
        2. Find the BEST alternative.
           - First, look in the Current Database.
           - IF NO GOOD MATCH EXISTS: Invent a new, realistic healthy alternative available in Sri Lanka.
           - Example: If input is "Chicken Burger", substitute could be "Grilled Chicken Salad".
        
        3. If you INVENT a new alternative, estimate its details.
           - CRITICAL: For "category", you MUST pick one from the 'Existing Categories' list provided above. 
             Only invent a new category if the item absolutely cannot fit into any existing one (e.g., trying to put 'Chicken' into 'Beverages').
        
        Return JSON ONLY:
        {{
            "input_product": {{
                "healthy": true/false,
                "price": 100,
                "days_to_expire": 3,
                "category": "Exact Category Name"
            }},
            "alt_name": "Name of alternative" or null,
            "alt_source": "existing" or "new",
            "new_product_details": {{ 
                "price": 100, 
                "days_to_expire": 7, 
                "category": "Exact Category Name"
            }}
        }}
        """
        try:
            response = model.generate_content(prompt)
            cleaned_text = response.text.replace(
                "```json", "").replace("```", "").strip()
            return json.loads(cleaned_text)
        except Exception as e:
            return {"input_product": {"healthy": True, "price": 0, "days_to_expire": 0, "category": "Unknown"}, "alt_name": None}

    # --- GEMINI CONTEXT HELPER ---
    def get_context_string(self):
        """Creates a string summary of the current pantry and cart for the AI"""
        sim_date = self.get_simulation_date().strftime('%Y-%m-%d')

        pantry_items = [f"{i['item']} (Expires: {i['expiry_date'].strftime('%Y-%m-%d')}, Status: {i['status']})"
                        for i in st.session_state.pantry]

        cart_items = [i['item'] for i in st.session_state.shopping_list]

        context = f"""
        Current Date: {sim_date}
        My Pantry Inventory: {', '.join(pantry_items) if pantry_items else 'Empty'}
        My Shopping List: {', '.join(cart_items) if cart_items else 'Empty'}
        """
        return context


# ==========================================
# 🖥️ PART 3: THE UI SETUP
# ==========================================
st.set_page_config(page_title="Smart Grocery Agent",
                   page_icon="🛒", layout="wide")

# Load CSS
load_custom_styles()

agent = SmartAgent()

# ==========================================
# 💬 PART 4: POPUPS (CHAT & ADD/EDIT ITEM)
# ==========================================


@st.dialog("📝 Manage Products", width="small")
def open_add_product_modal():
    # Toggle between Add and Edit Modes
    mode = st.radio("Select Mode", [
                    "➕ Add New Product", "✏️ Edit Existing Product"], horizontal=True)
    st.divider()

    # ==========================
    # MODE 1: ADD NEW PRODUCT
    # ==========================
    if mode == "➕ Add New Product":
        st.caption("Add a brand new item. AI will help find alternatives.")
        with st.form("new_product_form"):
            new_name = st.text_input(
                "Product Name", placeholder="e.g. Chicken Burger")
            existing_cats = list(PRODUCT_CATALOG.keys())
            new_category = st.selectbox("Category", existing_cats)
            new_price = st.number_input("Price (LKR)", min_value=0, value=500)
            new_expiry_days = st.number_input(
                "Shelf Life (Days)", min_value=1, value=3)
            submitted = st.form_submit_button("Save New Product")

            if submitted and new_name:
                # Prevent duplicates
                if new_name in ALL_PRODUCTS:
                    st.error(
                        f"'{new_name}' already exists! Switch to Edit mode to update it.")
                else:
                    with st.spinner("AI is analyzing & generating alternatives..."):
                        current_keys = list(ALL_PRODUCTS.keys())
                        ai_result = agent.analyze_new_product(
                            new_name, current_keys, existing_cats)
                        final_alt_name = ai_result.get('alt_name')

                        # Logic: Did AI invent a new product?
                        if ai_result.get('alt_source') == "new" and final_alt_name:
                            details = ai_result['new_product_details']
                            new_healthy_item = {
                                "price": details['price'],
                                "days_to_expire": details['days_to_expire'],
                                "healthy": True,
                                "alt": None
                            }
                            cat = details['category']
                            if cat not in PRODUCT_CATALOG:
                                PRODUCT_CATALOG[cat] = {}
                            PRODUCT_CATALOG[cat][final_alt_name] = new_healthy_item
                            ALL_PRODUCTS[final_alt_name] = new_healthy_item
                            ALL_PRODUCTS[final_alt_name]['category'] = cat
                            st.toast(
                                f"🎉 AI auto-created: {final_alt_name} ({cat})")

                        # Create the user's ORIGINAL product entry
                        user_item_entry = {
                            "price": new_price,
                            "days_to_expire": new_expiry_days,
                            "healthy": ai_result['input_product'].get('healthy', False),
                            "alt": final_alt_name
                        }

                        if new_category in PRODUCT_CATALOG:
                            PRODUCT_CATALOG[new_category][new_name] = user_item_entry
                        else:
                            PRODUCT_CATALOG[new_category] = {
                                new_name: user_item_entry}

                        DataManager.save_catalog(PRODUCT_CATALOG)
                        st.success(f"Added {new_name} successfully!")
                        st.rerun()

    # ==========================
    # MODE 2: EDIT EXISTING PRODUCT
    # ==========================
    else:
        st.caption("Update details for items already in your database.")

        # Dropdown to select item
        all_item_names = sorted(list(ALL_PRODUCTS.keys()))
        selected_item_name = st.selectbox(
            "Select Item to Edit", all_item_names)

        if selected_item_name:
            # Retrieve current details
            current_details = ALL_PRODUCTS[selected_item_name]
            current_cat = current_details.get('category', 'Pantry Staples')
            current_price = current_details.get('price', 0)
            current_expiry = current_details.get('days_to_expire', 7)

            with st.form("edit_product_form"):
                # Allow editing fields
                existing_cats = list(PRODUCT_CATALOG.keys())
                # Safe index finding
                cat_index = existing_cats.index(
                    current_cat) if current_cat in existing_cats else 0

                edit_category = st.selectbox(
                    "Category", existing_cats, index=cat_index)
                edit_price = st.number_input(
                    "Price (LKR)", min_value=0, value=int(current_price))
                edit_expiry = st.number_input(
                    "Shelf Life (Days)", min_value=1, value=int(current_expiry))

                submitted_edit = st.form_submit_button("Update Item")

                if submitted_edit:
                    # 1. Create Updated Entry (Preserve healthy/alt status)
                    updated_entry = current_details.copy()
                    updated_entry['price'] = edit_price
                    updated_entry['days_to_expire'] = edit_expiry
                    # 'healthy' and 'alt' remain unchanged from original to avoid losing AI logic

                    # 2. Handle Category Change (Move Item)
                    if edit_category != current_cat:
                        # Remove from old category
                        if current_cat in PRODUCT_CATALOG and selected_item_name in PRODUCT_CATALOG[current_cat]:
                            del PRODUCT_CATALOG[current_cat][selected_item_name]

                        # Add to new category
                        if edit_category not in PRODUCT_CATALOG:
                            PRODUCT_CATALOG[edit_category] = {}
                        PRODUCT_CATALOG[edit_category][selected_item_name] = updated_entry

                        # Update local cache category
                        updated_entry['category'] = edit_category
                    else:
                        # Just update the entry in place
                        PRODUCT_CATALOG[edit_category][selected_item_name] = updated_entry

                    # 3. Save and Refresh
                    DataManager.save_catalog(PRODUCT_CATALOG)
                    st.success(
                        f"✅ Updated '{selected_item_name}' successfully!")
                    st.rerun()


@st.dialog("✨ Smart Grocery AI", width="medium")
def open_chat_modal():
    # Header Section
    c1, c2 = st.columns([4, 1])
    with c1:
        st.markdown(
            "👋 *I can help you plan meals, check expiry dates, or **Add** new items!*")
    with c2:
        if st.button("🗑️ Clear", help="Clear Chat History"):
            st.session_state.chat_history = []
            st.session_state.add_flow_item = None

    st.divider()

    # Chat Container
    chat_container = st.container(height=400)

    with chat_container:
        if not st.session_state.chat_history:
            st.info(
                "💡 Tip: Type 'Add Pizza' to start adding an item to the database.")

        for message in st.session_state.chat_history:
            avatar = "🤖" if message["role"] == "assistant" else "👤"
            with st.chat_message(message["role"], avatar=avatar):
                st.markdown(message["content"])

    # Chat Input
    if prompt := st.chat_input("Type 'Add Pizza' or ask a question..."):
        # 1. Show User Message
        st.session_state.chat_history.append(
            {"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user", avatar="👤"):
                st.markdown(prompt)

            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Thinking..."):

                    # === FLOW 1: USER IS PROVIDING DETAILS FOR PENDING ADD ===
                    if st.session_state.add_flow_item:
                        item_name = st.session_state.add_flow_item
                        # Extract details from user's natural language text
                        extracted = agent.extract_details_from_text(prompt)

                        if extracted['price'] and extracted['days']:
                            # We have the details! Execute Add Logic.
                            st.markdown(
                                f"🔄 Analyzing **{item_name}** and finding healthy alternatives...")

                            current_keys = list(ALL_PRODUCTS.keys())
                            existing_cats = list(PRODUCT_CATALOG.keys())

                            # 1. Run AI Analysis
                            ai_result = agent.analyze_new_product(
                                item_name, current_keys, existing_cats)

                            final_alt_name = ai_result.get('alt_name')

                            # 2. Save Alternative (if new)
                            if ai_result.get('alt_source') == "new" and final_alt_name:
                                det = ai_result['new_product_details']
                                new_alt_entry = {
                                    "price": det['price'],
                                    "days_to_expire": det['days_to_expire'],
                                    "healthy": True,
                                    "alt": None
                                }
                                cat = det['category']
                                if cat not in PRODUCT_CATALOG:
                                    PRODUCT_CATALOG[cat] = {}

                                PRODUCT_CATALOG[cat][final_alt_name] = new_alt_entry
                                ALL_PRODUCTS[final_alt_name] = new_alt_entry
                                ALL_PRODUCTS[final_alt_name]['category'] = cat

                            # 3. Save User Item
                            target_cat = "Pantry Staples"
                            if final_alt_name:
                                target_cat = ALL_PRODUCTS.get(final_alt_name, {}).get(
                                    'category', 'Pantry Staples')

                            user_entry = {
                                "price": extracted['price'],
                                "days_to_expire": extracted['days'],
                                "healthy": ai_result['input_product'].get('healthy', False),
                                "alt": final_alt_name
                            }

                            if target_cat not in PRODUCT_CATALOG:
                                PRODUCT_CATALOG[target_cat] = {}
                            PRODUCT_CATALOG[target_cat][item_name] = user_entry

                            # Update global memory so the chat knows about it immediately
                            ALL_PRODUCTS[item_name] = user_entry
                            ALL_PRODUCTS[item_name]['category'] = target_cat

                            DataManager.save_catalog(PRODUCT_CATALOG)

                            success_msg = f"✅ **Saved {item_name}** to database!\n\n" \
                                f"💰 Price: {extracted['price']} | ⏳ Days: {extracted['days']}\n" \
                                f"📂 Category: {target_cat}"
                            if final_alt_name:
                                success_msg += f"\n\n💡 Linked Alternative: **{final_alt_name}** (Also added!)"

                            st.markdown(success_msg)
                            st.session_state.chat_history.append(
                                {"role": "assistant", "content": success_msg})
                            st.session_state.add_flow_item = None  # Reset Flow

                        else:
                            err_msg = f"⚠️ I couldn't find the numbers. Please type exactly like this: **500 3** (Price then Days)."
                            st.markdown(err_msg)
                            st.session_state.chat_history.append(
                                {"role": "assistant", "content": err_msg})

                    # === FLOW 2: NORMAL CHAT / START ADD ===
                    else:
                        context_data = agent.get_context_string()
                        system_instruction = f"""
                        You are a smart grocery assistant. 
                        Context: {context_data}
                        
                        COMMAND RULE:
                        If user wants to ADD a new item (e.g. "Add Pizza", "Save Apples"), return ONLY JSON:
                        {{"action": "start_add", "item": "Pizza"}}
                        
                        Otherwise, answer normally as a friendly assistant.
                        """

                        try:
                            response = model.generate_content(
                                f"{system_instruction}\nUser: {prompt}")
                            text_response = response.text

                            # Check for JSON command
                            command = None
                            try:
                                clean_json = text_response.replace(
                                    "```json", "").replace("```", "").strip()
                                if clean_json.startswith("{"):
                                    command = json.loads(clean_json)
                            except:
                                pass

                            if command and command.get('action') == "start_add":
                                item = command['item']
                                st.session_state.add_flow_item = item
                                msg = f"🛒 Okay, let's add **{item}**. What is the **Price (LKR)** and **Shelf Life (Days)**? (e.g., type '1500 2')"
                                st.markdown(msg)
                                st.session_state.chat_history.append(
                                    {"role": "assistant", "content": msg})
                            else:
                                st.markdown(text_response)
                                st.session_state.chat_history.append(
                                    {"role": "assistant", "content": text_response})
                        except Exception as e:
                            st.error(f"Error: {e}")


# ==========================================
# 🖥️ PART 5: MAIN INTERFACE
# ==========================================

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Simulation Controls")
    days_offset = st.slider("Fast Forward Time (Days)", 0, 14, 0)
    sim_date = datetime.now() + timedelta(days=days_offset)
    st.session_state['sim_date'] = sim_date
    st.markdown(f"**Date:** `{sim_date.strftime('%Y-%m-%d')}`")
    st.divider()

    # === NEW: ADD PRODUCT BUTTON ===
    if st.button("➕ Manage Products", use_container_width=True):
        open_add_product_modal()

    st.divider()

    # === CHAT BUTTON (Triggers Popup) ===
    st.markdown("### 🤖 AI Assistant")

    if st.button("✨ Chat with Agent", use_container_width=True):
        open_chat_modal()

    st.divider()
    st.info("💡 Tip: Use the slider to test Expiry & Restock logic.")

# --- MAIN PAGE HEADER ---
st.title("🛒 Smart Grocery Assistant")

# --- ALERTS & NOTIFICATIONS ---
if 'last_alert_count' not in st.session_state:
    st.session_state['last_alert_count'] = -1

expiry_alerts = agent.check_expiry_status()
prediction_alerts = agent.predict_needs()
current_alert_count = len(expiry_alerts) + len(prediction_alerts)

if current_alert_count > 0 and current_alert_count != st.session_state['last_alert_count']:
    st.toast(
        f"Agent has {current_alert_count} new alerts! Check the 'Notifications' tab.", icon="🔔")
    st.session_state['last_alert_count'] = current_alert_count
elif current_alert_count == 0:
    st.session_state['last_alert_count'] = 0

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(
    ["🛍️ Shop Now", "🏠 My Pantry", "📊 Analytics", "🔔 Notifications"])

# === TAB 1: SHOPPING ===
with tab1:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("Add Items")
        if PRODUCT_CATALOG:
            category = st.selectbox(
                "Select Category", list(PRODUCT_CATALOG.keys()))
            items_in_cat = list(PRODUCT_CATALOG[category].keys())
            selected_item = st.selectbox("Select Item", items_in_cat)

            if st.button("Add to Cart", use_container_width=True):
                better_alt = agent.analyze_cart_add(selected_item)
                stock_count = agent.check_pantry_stock(selected_item)

                if better_alt:
                    st.session_state.pending_suggestion = {
                        "type": "health",
                        "original": selected_item,
                        "alt": better_alt
                    }
                elif stock_count > 0:
                    st.session_state.pending_suggestion = {
                        "type": "duplicate",
                        "item": selected_item,
                        "count": stock_count
                    }
                else:
                    agent.add_item(selected_item)
                    st.success(f"Added {selected_item}")
                    st.rerun()

            if st.session_state.pending_suggestion:
                sugg = st.session_state.pending_suggestion
                if sugg['type'] == 'health':
                    st.warning(
                        f"⚠️ **Wait!** '{sugg['original']}' is not healthy.")
                    st.info(f"Suggestion: Buy **{sugg['alt']}** instead?")

                    c1, c2, c3 = st.columns(3)
                    if c1.button(f"✅ Switch to {sugg['alt']}"):
                        agent.add_item(sugg['alt'])
                        st.session_state.pending_suggestion = None
                        st.rerun()
                    if c2.button(f"✋ Keep {sugg['original']}"):
                        agent.add_item(sugg['original'])
                        st.session_state.pending_suggestion = None
                        st.rerun()
                    if c3.button("🚫 Cancel"):
                        st.session_state.pending_suggestion = None
                        st.rerun()

                elif sugg['type'] == 'duplicate':
                    st.warning(
                        f"🏠 **Pantry Alert:** You have **{sugg['count']}** unit(s) of **{sugg['item']}**.")
                    st.write("Buy again?")
                    c1, c2 = st.columns(2)
                    if c1.button("✅ Add Anyway"):
                        agent.add_item(sugg['item'])
                        st.session_state.pending_suggestion = None
                        st.rerun()
                    if c2.button("🚫 Cancel"):
                        st.session_state.pending_suggestion = None
                        st.rerun()
        else:
            st.error("Catalog empty.")

    with col2:
        st.subheader("📝 Shopping List")
        if st.session_state.shopping_list:
            h1, h2, h3 = st.columns([3, 1, 1])
            h1.markdown("**Item**")
            h2.markdown("**Price**")
            h3.markdown("**Action**")
            st.divider()

            index_to_remove = None
            for i, item in enumerate(st.session_state.shopping_list):
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(item['item'])
                c2.write(f"{item['price']}")
                if c3.button("🗑️", key=f"remove_{i}"):
                    index_to_remove = i

            if index_to_remove is not None:
                del st.session_state.shopping_list[index_to_remove]
                st.rerun()

            st.divider()
            total_price = sum(i['price']
                              for i in st.session_state.shopping_list)
            st.markdown(f"### Total: LKR {total_price}")

            col_checkout, col_clear = st.columns(2)
            with col_checkout:
                if st.button("✅ Checkout", use_container_width=True):
                    for row in st.session_state.shopping_list:
                        details = ALL_PRODUCTS.get(row['item'])
                        if details:
                            new_pantry_item = {
                                "item": row['item'],
                                "buy_date": sim_date,
                                "expiry_date": sim_date + timedelta(days=details['days_to_expire']),
                                "status": "Good"
                            }
                            st.session_state.pantry.append(new_pantry_item)

                    DataManager.save_history(st.session_state.pantry)
                    st.session_state.shopping_list = []
                    st.balloons()
                    st.success(f"Checkout Complete! Total: LKR {total_price}")
                    st.rerun()

            with col_clear:
                if st.button("🗑️ Clear Cart", use_container_width=True):
                    st.session_state.shopping_list = []
                    st.warning("Cart cleared.")
                    st.rerun()
        else:
            st.info("List is empty.")

# === TAB 2: PANTRY ===
with tab2:
    st.subheader("🏠 Pantry Inventory")
    if st.session_state.pantry:
        h1, h2, h3, h4, h5 = st.columns([2, 1.5, 1.5, 1.5, 0.5])
        h1.markdown("**Item**")
        h2.markdown("**Buy Date**")
        h3.markdown("**Expiry Date**")
        h4.markdown("**Status**")
        h5.markdown("**Action**")
        st.divider()

        index_to_remove = None
        for i, entry in enumerate(st.session_state.pantry):
            c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 0.5])
            buy_str = entry['buy_date'].strftime('%Y-%m-%d')
            exp_str = entry['expiry_date'].strftime('%Y-%m-%d')
            status = entry['status']
            color = "green"
            if status == "Expired":
                color = "red"
            elif status == "Critical":
                color = "orange"
            elif status == "Expiring Soon":
                color = "orange"

            c1.write(entry['item'])
            c2.write(buy_str)
            c3.write(exp_str)
            c4.markdown(f":{color}[{status}]")
            if c5.button("🗑️", key=f"delete_pantry_{i}"):
                index_to_remove = i

        if index_to_remove is not None:
            removed = st.session_state.pantry.pop(index_to_remove)
            DataManager.save_history(st.session_state.pantry)
            st.warning(f"Removed {removed['item']} from pantry.")
            st.rerun()
    else:
        st.info("Pantry is empty.")

# === TAB 3: ANALYTICS ===
with tab3:
    st.subheader("📊 Overview")
    if st.session_state.pantry:
        pantry_data = []
        for item in st.session_state.pantry:
            details = ALL_PRODUCTS.get(item['item'], {})
            pantry_data.append({
                "Category": details.get('category', 'Unknown'),
                "Price": details.get('price', 0),
                "Healthy": details.get('healthy', False)
            })
        df = pd.DataFrame(pantry_data)

        total_value = df['Price'].sum()
        healthy_count = len(df[df['Healthy']])
        total_items = len(df)
        health_score = (healthy_count / total_items) * \
            100 if total_items > 0 else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Total Value", f"LKR {total_value}")
        c2.metric("❤️ Health Score", f"{health_score:.0f}%")
        c3.metric("📦 Item Count", total_items)
        st.divider()
        st.caption("💰 Spending Breakdown by Category")
        spend_by_cat = df.groupby("Category")["Price"].sum()
        st.bar_chart(spend_by_cat, color="#4CAF50")
    else:
        st.info("No data available yet.")

# === TAB 4: NOTIFICATIONS ===
with tab4:
    st.subheader("🔔 Agent Notifications")
    col_alerts, col_suggestions = st.columns(2)
    with col_alerts:
        st.markdown("### ⚠️ Attention Needed")
        if expiry_alerts:
            for alert in expiry_alerts:
                st.error(alert)
        else:
            st.success("Everything is fresh! ✅")
    with col_suggestions:
        st.markdown("### 💡 Restock Suggestions")
        if prediction_alerts:
            for alert in prediction_alerts:
                st.info(alert)
        else:
            st.success("No restock predictions needed yet. ✅")
