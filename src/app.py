import sys
import os
import sqlite3
import uuid
import streamlit as st
import pandas as pd
from src.logger import setup_logger

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langgraph.checkpoint.sqlite import SqliteSaver
from src.graph import build_graph
from src.setup_db import init_database
from src.gmail_service import fetch_test_emails, send_reply_email

st.set_page_config(page_title="AI Support & HITL Agent", page_icon="🤖", layout="wide")


# 1. Inicijalizacija loggera specifičnog za Streamlit aplikaciju
logger = setup_logger("StreamlitApp")

logger.info("Pokretanje Streamlit sučelja...")

st.title("AI Support Agent & HITL Dashboard")

# 2. Primjer praćenja akcija korisnika (npr. klik na gumb)
if st.button("📬 Provjeri nove [TEST-AI] mailove"):
    logger.info("Korisnik je pokrenuo ručnu provjeru novih mailova.")
    
    try:
        # Ovdje pozivaš svoju funkciju za dohvat mailova
        # fetch_emails_from_gmail()
        logger.info("Gmail sinkronizacija uspješno završena.")
        st.success("Mailovi su osvježeni!")
        
    except Exception as e:
        # exc=True automatski zapisuje cijeli traceback u logs/app.log
        logger.error(f"Greška tijekom sinkronizacije s Gmailom: {e}", exc_info=True)
        st.error("Došlo je do greške prilikom dohvaćanja mailova.")

# 3. Primjer praćenja Human-in-the-Loop odluke
if st.button("✅ Odobri povrat novca"):
    logger.warning("Operater je ručno ODOBRIO transakciju iznad 50 EUR.")
    # nastavak izvršavanja grafa...


# Inicijalizacija LangGraph-a s trajnom SQLite memorijom
@st.cache_resource
def get_agent():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect("data/checkpoints.db", check_same_thread=False)
    memory = SqliteSaver(conn)
    return build_graph(memory)

app = get_agent()

# Čuvanje aktivnih ticketa u sesiji sučelja
if "tickets" not in st.session_state:
    st.session_state.tickets = []

def process_incoming_email(sender, subject, body, gmail_msg_id=None, gmail_thread_id=None):
    thread_id = gmail_msg_id if gmail_msg_id else f"sim-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "email_sender": sender,
        "email_subject": subject,
        "email_body": body,
        "requires_human_approval": False,
        "human_approved": None,
        "refund_executed": False,
        "status_log": "Zaprimljeno"
    }
    
    # Pokretanje grafa
    app.invoke(initial_state, config=config)
    snapshot = app.get_state(config)
    values = snapshot.values
    
    # Ako je graf pauziran prije izvršenja povrata, provjeri je li iznos <= 50 € (Auto-Approve!)
    if snapshot.next == ("execute_refund_node",) and not values.get("requires_human_approval"):
        app.update_state(config, {"human_approved": True})
        app.invoke(None, config=config)
        snapshot = app.get_state(config)
        values = snapshot.values
        
    ticket_info = {
        "thread_id": thread_id,
        "gmail_msg_id": gmail_msg_id,
        "gmail_thread_id": gmail_thread_id,
        "is_paused": snapshot.next == ("execute_refund_node",),
        "state": values,
        "email_sent": False
    }
    
    # Ako agent nije pauziran i nije spam, a došao je s pravog Gmaila -> automatski pošalji odgovor!
    if not ticket_info["is_paused"] and values.get("draft_response") and gmail_msg_id:
        send_reply_email(sender, subject, values["draft_response"], gmail_msg_id, gmail_thread_id)
        ticket_info["email_sent"] = True
        
    st.session_state.tickets.insert(0, ticket_info)

# --- BOČNA TRAKA (SIDEBAR): Stanje baze i kontrole ---
with st.sidebar:
    st.header("🗄️ Baza narudžbi (Live)")
    if st.button("🔄 Resetiraj dummy bazu"):
        init_database()
        st.session_state.tickets = []
        st.success("Baza i ticketa resetirani!")
        
    if os.path.exists("data/orders.db"):
        conn = sqlite3.connect("data/orders.db")
        df_orders = pd.read_sql_query("SELECT order_id, item_name, amount, status FROM orders", conn)
        conn.close()
        st.dataframe(df_orders, hide_index=True, use_container_width=True)
        
    st.divider()
    st.markdown("**Pravila Guardraila:**\n- Povrat `<= 50 €`: **Automatski**\n- Povrat `> 50 €`: **Pauza (HITL)**")

# --- GLAVNI EKRAN ---
st.title("🤖 Autonomni Support Agent s Human-in-the-Loop")
st.caption("LangGraph + Groq (GPT-OSS-120B) + SQLite Checkpointer + Gmail API")

tab_gmail, tab_sim = st.tabs(["📬 Live Gmail Sinkronizacija", "🧪 Simulator dolaznih mailova"])

with tab_gmail:
    st.info("Agent traži nepročitane mailove u tvom Gmailu koji u naslovu sadrže **`[TEST-AI]`**.")
    if st.button("📥 Provjeri nove [TEST-AI] mailove u Gmailu", type="primary"):
        with st.spinner("Spajam se na Gmail API i pokrećem agenta..."):
            try:
                emails = fetch_test_emails()
                if not emails:
                    st.warning("Nema novih nepročitanih mailova s oznakom [TEST-AI]. Pošalji si jedan s mobitela!")
                else:
                    for em in emails:
                        process_incoming_email(
                            em["sender"], em["subject"], em["body"], em["id"], em["threadId"]
                        )
                    st.success(f"Obrađeno {len(emails)} novih mailova!")
            except Exception as e:
                st.error(f"Greška s Gmail API-jem: {e}")

with tab_sim:
    col1, col2 = st.columns(2)
    with col1:
        sim_sender = st.text_input("Pošiljatelj", value="ana.kovac@example.com")
        sim_subject = st.text_input("Naslov", value="Povrat tipkovnice ORD-102")
    with col2:
        sim_body = st.text_area("Tekst poruke", value="Pozdrav, tipkovnica iz narudžbe ORD-102 mi ne odgovara. Molim povrat novca.", height=105)
        
    if st.button("🚀 Pošalji u simulator"):
        with st.spinner("Agent analizira upit..."):
            process_incoming_email(sim_sender, sim_subject, sim_body)

st.divider()
st.subheader("📋 Red čekanja i obrađeni zahtjevi")

if not st.session_state.tickets:
    st.write("Trenutno nema obrađenih zahtjeva. Pokreni provjeru Gmaila ili pošalji testni upit iz simulatora.")

for idx, ticket in enumerate(st.session_state.tickets):
    state = ticket["state"]
    config = {"configurable": {"thread_id": ticket["thread_id"]}}
    
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.markdown(f"**Od:** `{state['email_sender']}` | **Naslov:** {state['email_subject']}")
        c2.markdown(f"**Kategorija:** `{state.get('category', '').upper()}`")
        
        if ticket["is_paused"]:
            c3.warning("⏸️ ČEKA ODOBRENJE")
        elif state.get("category") == "spam":
            c3.error("🗑️ SPAM")
        else:
            c3.success("✅ ZAVRŠENO")
            
        st.markdown(f"> *{state['email_body']}*")
        st.caption(f"🧠 **AI Rezoniranje:** {state.get('triage_reasoning')}")
        
        # PRIKAZ HUMAN-IN-THE-LOOP KONTROLA AKO JE GRAF PAUZIRAN
        if ticket["is_paused"]:
            order = state.get("order_details", {})
            st.error(
                f"⚠️ **ZAHTJEV ZA LJUDSKU INTERVENCIJU:** Kupac traži povrat od **{order.get('amount')} €** "
                f"za artikl *{order.get('item_name')}* (`{order.get('order_id')}`). Iznos prelazi limit od 50 €."
            )
            btn_col1, btn_col2, _ = st.columns([1, 1, 3])
            
            if btn_col1.button("✅ Odobri povrat", key=f"app_{ticket['thread_id']}", type="primary"):
                app.update_state(config, {"human_approved": True})
                final_res = app.invoke(None, config=config)
                ticket["state"] = final_res
                ticket["is_paused"] = False
                if ticket["gmail_msg_id"] and final_res.get("draft_response"):
                    send_reply_email(state["email_sender"], state["email_subject"], final_res["draft_response"], ticket["gmail_msg_id"], ticket["gmail_thread_id"])
                    ticket["email_sent"] = True
                st.rerun()
                
            if btn_col2.button("❌ Odbij povrat", key=f"rej_{ticket['thread_id']}"):
                app.update_state(config, {"human_approved": False})
                final_res = app.invoke(None, config=config)
                ticket["state"] = final_res
                ticket["is_paused"] = False
                if ticket["gmail_msg_id"] and final_res.get("draft_response"):
                    send_reply_email(state["email_sender"], state["email_subject"], final_res["draft_response"], ticket["gmail_msg_id"], ticket["gmail_thread_id"])
                    ticket["email_sent"] = True
                st.rerun()
                
        # PRIKAZ GENERIRANOG ODGOVORA NAKON ZAVRŠETKA
        if not ticket["is_paused"] and state.get("draft_response"):
            with st.expander("📧 Pogledaj generirani odgovor kupcu", expanded=True):
                st.text(state["draft_response"])
                if ticket["email_sent"]:
                    st.success("📤 Odgovor je stvarno poslan putem tvog Gmail računa!")

