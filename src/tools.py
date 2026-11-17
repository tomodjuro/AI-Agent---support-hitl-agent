import sqlite3
import os
from typing import Optional, Dict, Any

DB_PATH = os.path.join("data", "orders.db")
FAQ_PATH = os.path.join("data", "faq.txt")

def get_order_details(order_id: str) -> Optional[Dict[str, Any]]:
    """Dohvaća detalje narudžbe iz SQLite baze prema order_id."""
    if not order_id:
        return None
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Omogućuje pristup stupcima po imenu
    cursor = conn.cursor()
    
    # Čistimo unos (npr. 'ord-101' -> 'ORD-101')
    clean_id = order_id.strip().upper()
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (clean_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def process_refund_in_db(order_id: str) -> bool:
    """Ažurira status narudžbe u 'refunded'. Poziva se TEK nakon provjere/odobrenja."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    clean_id = order_id.strip().upper()
    cursor.execute(
        "UPDATE orders SET status = 'refunded' WHERE order_id = ? AND status = 'delivered'",
        (clean_id,)
    )
    updated_rows = cursor.rowcount
    conn.commit()
    conn.close()
    
    return updated_rows > 0

def get_company_faq() -> str:
    """Čita pravila poslovanja iz faq.txt datoteke."""
    if not os.path.exists(FAQ_PATH):
        return "Nema dostupnih pravila poslovanja."
    with open(FAQ_PATH, "r", encoding="utf-8") as f:
        return f.read()