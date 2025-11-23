import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta

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

    @staticmethod
    def load_history():
        try:
            with open(DataManager.HISTORY_FILE, 'r') as f:
                raw_data = json.load(f)

            processed_data = []
            today = datetime.now()

            for entry in raw_data:
                if 'buy_date_offset' in entry:
                    buy_date = today + timedelta(days=entry['buy_date_offset'])
                    expiry_date = today + \
                        timedelta(days=entry['expiry_offset'])
                else:
                    buy_date = datetime.strptime(entry['buy_date'], "%Y-%m-%d")
                    expiry_date = datetime.strptime(
                        entry['expiry_date'], "%Y-%m-%d")

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


# ==========================================
# 🖥️ PART 3: THE UI
# ==========================================
st.set_page_config(page_title="Smart Grocery Agent",
                   page_icon="🛒", layout="wide")

agent = SmartAgent()

# --- SIDEBAR (Controls Only) ---
with st.sidebar:
    st.header("⚙️ Simulation Controls")
    days_offset = st.slider("Fast Forward Time (Days)", 0, 14, 0)
    sim_date = datetime.now() + timedelta(days=days_offset)
    st.session_state['sim_date'] = sim_date
    st.markdown(f"**Date:** `{sim_date.strftime('%Y-%m-%d')}`")
    st.divider()
    st.info("💡 Tip: Use this slider to test Expiry & Restock logic.")

# --- MAIN PAGE HEADER ---
st.title("🛒 Smart Grocery Assistant")

# --- NON-INTRUSIVE ALERT (TOAST) - FIXED ---
if 'last_alert_count' not in st.session_state:
    st.session_state['last_alert_count'] = -1

expiry_alerts = agent.check_expiry_status()
prediction_alerts = agent.predict_needs()
current_alert_count = len(expiry_alerts) + len(prediction_alerts)

# Only show toast if count > 0 AND the count has changed since last rerun
if current_alert_count > 0 and current_alert_count != st.session_state['last_alert_count']:
    st.toast(
        f"Agent has {current_alert_count} new alerts! Check the 'Notifications' tab.", icon="🔔")
    st.session_state['last_alert_count'] = current_alert_count
elif current_alert_count == 0:
    st.session_state['last_alert_count'] = 0


# --- MAIN TABS ---
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
                    # Health suggestion available
                    st.session_state.pending_suggestion = {
                        "type": "health",
                        "original": selected_item,
                        "alt": better_alt
                    }
                elif stock_count > 0:
                    # Healthy but duplicate
                    st.session_state.pending_suggestion = {
                        "type": "duplicate",
                        "item": selected_item,
                        "count": stock_count
                    }
                else:
                    # Healthy and New
                    agent.add_item(selected_item)
                    st.success(f"Added {selected_item}")
                    st.rerun()

            if st.session_state.pending_suggestion:
                sugg = st.session_state.pending_suggestion

                # --- TYPE 1: HEALTH WARNING ---
                if sugg['type'] == 'health':
                    st.warning(
                        f"⚠️ **Wait!** '{sugg['original']}' is not healthy.")
                    st.info(f"Suggestion: Buy **{sugg['alt']}** instead?")
                    c1, c2 = st.columns(2)

                    # 1. User accepts healthy suggestion
                    if c1.button(f"✅ Switch to {sugg['alt']}"):
                        alt_stock_count = agent.check_pantry_stock(sugg['alt'])
                        if alt_stock_count > 0:
                            st.session_state.pending_suggestion = {
                                "type": "duplicate",
                                "item": sugg['alt'],
                                "count": alt_stock_count
                            }
                            st.rerun()
                        else:
                            agent.add_item(sugg['alt'])
                            st.session_state.pending_suggestion = None
                            st.rerun()

                    # 2. User rejects, keeps original
                    if c2.button(f"❌ Keep {sugg['original']}"):
                        stock_count = agent.check_pantry_stock(
                            sugg['original'])
                        if stock_count > 0:
                            st.session_state.pending_suggestion = {
                                "type": "duplicate",
                                "item": sugg['original'],
                                "count": stock_count
                            }
                            st.rerun()
                        else:
                            agent.add_item(sugg['original'])
                            st.session_state.pending_suggestion = None
                            st.rerun()

                # --- TYPE 2: DUPLICATE WARNING ---
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
                    for index, row in enumerate(st.session_state.shopping_list):
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
                    st.success(
                        f"Checkout Complete! Total: LKR {total_price}")
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
        # Create a Grid Layout for the Table
        h1, h2, h3, h4, h5 = st.columns([2, 1.5, 1.5, 1.5, 0.5])
        h1.markdown("**Item**")
        h2.markdown("**Buy Date**")
        h3.markdown("**Expiry Date**")
        h4.markdown("**Status**")
        h5.markdown("**Action**")
        st.divider()

        index_to_remove = None
        # Loop through pantry items to create rows
        for i, entry in enumerate(st.session_state.pantry):
            c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 0.5])

            # Format dates nicely
            buy_str = entry['buy_date'].strftime('%Y-%m-%d')
            exp_str = entry['expiry_date'].strftime('%Y-%m-%d')

            # Status Coloring
            status = entry['status']
            color = "green"
            if status == "Expired":
                color = "red"
            elif status == "Critical":
                color = "orange"
            elif status == "Expiring Soon":
                color = "orange"

            # Render Row
            c1.write(entry['item'])
            c2.write(buy_str)
            c3.write(exp_str)
            c4.markdown(f":{color}[{status}]")

            # DELETE BUTTON LOGIC
            if c5.button("🗑️", key=f"delete_pantry_{i}"):
                index_to_remove = i

        # Handle Deletion
        if index_to_remove is not None:
            removed_item = st.session_state.pantry.pop(index_to_remove)
            DataManager.save_history(st.session_state.pantry)
            st.warning(
                f"Removed {removed_item['item']} from pantry and database.")
            st.rerun()

    else:
        st.info("Pantry is empty.")

# === TAB 3: ANALYTICS (SIMPLIFIED) ===
with tab3:
    st.subheader("📊 Overview")

    if st.session_state.pantry:
        # Prepare Data
        pantry_data = []
        for item in st.session_state.pantry:
            details = ALL_PRODUCTS.get(item['item'], {})
            pantry_data.append({
                "Category": details.get('category', 'Unknown'),
                "Price": details.get('price', 0),
                "Healthy": details.get('healthy', False)
            })

        df = pd.DataFrame(pantry_data)

        # 1. Clean Metrics Row
        total_value = df['Price'].sum()
        # Calculate health score: percentage of items that are healthy
        healthy_count = len(df[df['Healthy']])
        total_items = len(df)
        health_score = (healthy_count / total_items) * \
            100 if total_items > 0 else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Total Value", f"LKR {total_value}")
        c2.metric("❤️ Health Score", f"{health_score:.0f}%")
        c3.metric("📦 Item Count", total_items)

        st.divider()

        # 2. Single Important Chart
        st.caption("💰 Spending Breakdown by Category")
        spend_by_cat = df.groupby("Category")["Price"].sum()
        st.bar_chart(spend_by_cat, color="#4CAF50")

    else:
        st.info("No data available yet. Add items to your pantry!")

# === TAB 4: NOTIFICATIONS ===
with tab4:
    st.subheader("🔔 Agent Notifications")
    st.caption("The AI Agent predicts your needs and monitors food freshness.")
    st.divider()

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
