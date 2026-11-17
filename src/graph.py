import sys
import os
import sqlite3
from typing import TypedDict, Optional, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

# Osiguravamo da Python uvijek vidi korijen projekta
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.tools import get_order_details, process_refund_in_db, get_company_faq

load_dotenv()

# Inicijalizacija Groq modela
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)

# 1. Pydantic shema za Trijažu
class TriageResult(BaseModel):
    category: Literal["refund", "question", "spam"] = Field(
        description="Kategorija upita: 'refund' za povrat/reklamaciju, 'question' za općenita pitanja, 'spam' za neželjenu poštu."
    )
    order_id: Optional[str] = Field(
        default=None,
        description="ID narudžbe (npr. 'ORD-101'). Vrati None ako nije naveden."
    )
    reasoning: str = Field(
        description="Kratko objašnjenje klasifikacije na hrvatskom."
    )

# 2. Stanje grafa (State)
class AgentState(TypedDict):
    email_sender: str
    email_subject: str
    email_body: str
    
    category: Optional[str]
    order_id: Optional[str]
    triage_reasoning: Optional[str]
    
    order_details: Optional[dict]
    faq_context: Optional[str]
    
    requires_human_approval: bool
    human_approved: Optional[bool]
    refund_executed: bool
    
    draft_response: Optional[str]
    status_log: str

# --- ČVOROVI (NODES) ---

def triage_node(state: AgentState) -> dict:
    print("🧠 [1. Triage Node] Analiziram dolazni email...")
    structured_llm = llm.with_structured_output(TriageResult)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Ti si precizan AI sustav za trijažu korisničke podrške. Analiziraj email i klasificiraj ga."),
        ("human", "Pošiljatelj: {sender}\nNaslov: {subject}\nTekst: {body}")
    ])
    
    result: TriageResult = (prompt | structured_llm).invoke({
        "sender": state["email_sender"],
        "subject": state["email_subject"],
        "body": state["email_body"]
    })
    
    print(f"   -> Kategorija: {result.category} | Order ID: {result.order_id}")
    return {
        "category": result.category,
        "order_id": result.order_id,
        "triage_reasoning": result.reasoning,
        "status_log": f"Klasificirano kao '{result.category}'."
    }

def rag_node(state: AgentState) -> dict:
    print("📚 [2a. RAG Node] Dohvaćam pravila poslovanja...")
    faq = get_company_faq()
    return {
        "faq_context": faq,
        "status_log": "Dohvaćena interna pravila poslovanja."
    }

def db_lookup_node(state: AgentState) -> dict:
    print(f"🔍 [2b. DB Lookup Node] Provjeravam narudžbu: {state.get('order_id')}...")
    order = get_order_details(state.get("order_id"))
    
    if not order:
        print("   -> Narudžba nije pronađena u bazi.")
        return {
            "order_details": None,
            "requires_human_approval": False,
            "status_log": "Narudžba nije pronađena."
        }
    
    amount = order["amount"]
    status = order["status"]
    print(f"   -> Pronađeno: {order['item_name']} | Iznos: {amount} € | Status: {status}")
    
    # DETERMINISTIČKI GUARDRAIL: Ako je status 'delivered' i iznos > 50 €, traži čovjeka!
    needs_human = (status == "delivered" and amount > 50.0)
    
    if needs_human:
        print(f"   ⚠️ RIZIK: Iznos ({amount} €) prelazi limit od 50 €. Aktiviram Human-in-the-Loop!")
        
    return {
        "order_details": order,
        "requires_human_approval": needs_human,
        "status_log": f"Provjerena narudžba ({amount} €, status: {status})."
    }

def execute_refund_node(state: AgentState) -> dict:
    print("💸 [3. Execute Refund Node] Pokrećem obradu povrata novca...")
    order = state.get("order_details")
    
    # Provjera je li čovjek odbio zahtjev (ako je HITL bio potreban)
    if state.get("requires_human_approval") and state.get("human_approved") is False:
        print("   ❌ Čovjek je ODBIO povrat novca.")
        return {
            "refund_executed": False,
            "status_log": "Povrat odbijen od strane operatera."
        }
    
    # Izvršavanje povrata u SQLite bazi
    success = process_refund_in_db(order["order_id"])
    if success:
        print(f"   ✅ Povrat od {order['amount']} € uspješno evidentiran u bazi za {order['order_id']}!")
    else:
        print("   ⚠️ Povrat nije izvršen (narudžba nema status 'delivered').")
        
    return {
        "refund_executed": success,
        "status_log": "Povrat izvršen u bazi." if success else "Povrat nije moguć zbog statusa narudžbe."
    }

def draft_response_node(state: AgentState) -> dict:
    print("✍️ [4. Draft Response Node] Sastavljam profesionalni odgovor kupcu...")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Ti si ljubazan i profesionalan agent korisničke podrške. Napiši odgovor kupcu na hrvatskom jeziku na temelju konteksta.
        Pravila:
        - Ako je povrat izvršen (refund_executed=True), potvrdi iznos povrata i zahvali na strpljenju.
        - Ako je povrat odbijen od strane operatera (requires_human_approval=True i human_approved=False), pristojno objasni da zahtjev trenutno ne može biti odobren te da će ih kontaktirati voditelj odjela.
        - Ako narudžba nije pronađena, zamoli kupca da provjeri i pošalje točan broj narudžbe (npr. ORD-101).
        - Ako narudžba ima status 'shipped' ili 'refunded', objasni situaciju prema pravilima poslovanja.
        - Ako je riječ o općenitom pitanju, odgovori isključivo na temelju priloženih pravila poslovanja.
        Nemoj izmišljati informacije. Potpiši se kao 'AI & Human Support Tim'."""),
        ("human", """Dolazni email od {sender}:
        Naslov: {subject}
        Tekst: {body}
        
        Interni podaci sustava:
        - Kategorija: {category}
        - Detalji narudžbe iz baze: {order_details}
        - Zahtijevalo odobrenje čovjeka: {requires_human}
        - Čovjek odobrio: {human_approved}
        - Povrat izvršen u bazi: {refund_executed}
        - Pravila poslovanja (FAQ): {faq}
        """)
    ])
    
    response = (prompt | llm).invoke({
        "sender": state["email_sender"],
        "subject": state["email_subject"],
        "body": state["email_body"],
        "category": state.get("category"),
        "order_details": state.get("order_details"),
        "requires_human": state.get("requires_human_approval"),
        "human_approved": state.get("human_approved"),
        "refund_executed": state.get("refund_executed", False),
        "faq": state.get("faq_context") or get_company_faq()
    })
    
    return {
        "draft_response": response.content,
        "status_log": "Nacrt odgovora spreman."
    }

# --- UVJETNO GRANANJE (ROUTING) ---

def route_after_triage(state: AgentState) -> str:
    cat = state.get("category")
    if cat == "spam":
        print("🗑️ [Routing] Spam detektiran. Prekidam obradu.")
        return END
    elif cat == "question":
        return "rag_node"
    else:
        return "db_lookup_node"

def route_after_db(state: AgentState) -> str:
    order = state.get("order_details")
    # Ako narudžba postoji i ima status 'delivered', idemo na izvršenje povrata (gdje čeka HITL ako je > 50 €)
    if order and order["status"] == "delivered":
        return "execute_refund_node"
    # Inače (ne postoji, već je 'refunded' ili je 'shipped') idemo direktno na pisanje objašnjenja kupcu
    return "draft_response_node"

# --- SASTAVLJANJE GRAFA ---

def build_graph(checkpointer):
    workflow = StateGraph(AgentState)
    
    # Dodavanje čvorova
    workflow.add_node("triage_node", triage_node)
    workflow.add_node("rag_node", rag_node)
    workflow.add_node("db_lookup_node", db_lookup_node)
    workflow.add_node("execute_refund_node", execute_refund_node)
    workflow.add_node("draft_response_node", draft_response_node)
    
    # Početna točka
    workflow.set_entry_point("triage_node")
    
    # Rubovi (Edges)
    workflow.add_conditional_edges("triage_node", route_after_triage)
    workflow.add_edge("rag_node", "draft_response_node")
    workflow.add_conditional_edges("db_lookup_node", route_after_db)
    workflow.add_edge("execute_refund_node", "draft_response_node")
    workflow.add_edge("draft_response_node", END)
    
    # KLJUČNO ZA HITL: Pauziraj graf prije nego što agent izvrši povrat novca!
    # U samom čvoru/rutiranju odlučujemo hoćemo li ga pustiti ili tražiti odobrenje
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["execute_refund_node"]
    )

# --- TESTIRANJE HITL MEHANIZMA U KONZOLI ---
if __name__ == "__main__":
    # Resetiramo bazu da test uvijek bude čist
    from src.setup_db import init_database
    init_database()
    
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect("data/checkpoints.db", check_same_thread=False)
    memory = SqliteSaver(conn)
    app = build_graph(memory)
    
    # Svaki mail ima svoj jedinstveni thread_id
    config = {"configurable": {"thread_id": "test-ticket-ord-102"}}
    
    initial_state = {
        "email_sender": "ana.kovac@example.com",
        "email_subject": "Povrat tipkovnice ORD-102",
        "email_body": "Pozdrav, kupila sam mehaničku tipkovnicu (ORD-102), ali mi ne odgovara. Molim povrat novca.",
        "requires_human_approval": False,
        "human_approved": None,
        "refund_executed": False,
        "status_log": "Zaprimljeno"
    }
    
    print("\n--- KORAK 1: Pokrećem agenta za narudžbu od 149.99 € ---")
    app.invoke(initial_state, config=config)
    
    # Provjera trenutnog stanja u memoriji
    snapshot = app.get_state(config)
    print(f"\n⏸️ STANJE NAKON PAUZE: Sljedeći čvor na čekanju -> {snapshot.next}")
    print(f"   Zahtijeva odobrenje čovjeka? -> {snapshot.values.get('requires_human_approval')}")
    
    # Simuliramo čovjeka koji u sučelju klikne "ODOBRI"
    if snapshot.next == ("execute_refund_node",):
        print("\n--- KORAK 2: Čovjek u sučelju klika 'ODOBRI' (Nastavljam graf...) ---")
        app.update_state(config, {"human_approved": True})
        
        # Nastavljamo izvršavanje s None kao ulazom (LangGraph nastavlja iz checkpointa!)
        final_result = app.invoke(None, config=config)
        
        print("\n📧 KONAČNI GENERIRANI ODGOVOR KUPCU:\n")
        print(final_result["draft_response"])