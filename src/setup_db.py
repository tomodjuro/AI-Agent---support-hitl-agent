import sqlite3
import os

DB_PATH = os.path.join("data", "orders.db")

def init_database():
    # Osiguraj da direktorij 'data' postoji
    os.makedirs("data", exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Brisanje tablice ako već postoji (za čisto resetiranje testova)
    cursor.execute("DROP TABLE IF EXISTS orders")

    # Kreiranje tablice narudžbi
    cursor.execute("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            item_name TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            purchase_date TEXT NOT NULL
        )
    """)

    # Dummy podaci koji pokrivaju različite poslovne scenarije
    dummy_orders = [
        ("ORD-101", "Ivan Horvat", "ivan.horvat@example.com", "Bežični miš Logitech", 25.00, "delivered", "2026-11-10"),
        ("ORD-102", "Ana Kovač", "ana.kovac@example.com", "Mehanička tipkovnica Keychron", 149.99, "delivered", "2026-11-12"),
        ("ORD-103", "Marko Babić", "marko.babic@example.com", "USB-C Hub", 35.50, "refunded", "2026-11-01"),
        ("ORD-104", "Petra Novak", "petra.novak@example.com", "27-inčni 4K Monitor", 320.00, "shipped", "2026-11-15"),
        ("ORD-105", "Luka Jurić", "luka.juric@example.com", "Laptop stalak", 50.00, "delivered", "2026-11-14"),
        ("ORD-106", "Maja Vuković", "maja.vukovic@example.com", "Sony WH-1000XM5 slušalice", 450.00, "delivered", "2026-11-16")
    ]

    cursor.executemany("""
        INSERT INTO orders (order_id, customer_name, customer_email, item_name, amount, status, purchase_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, dummy_orders)

    conn.commit()
    conn.close()
    print(f"Uspješno kreirana baza '{DB_PATH}' s {len(dummy_orders)} testnih narudžbi.")

if __name__ == "__main__":
    init_database()