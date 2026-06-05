import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ensure the root folder is in the python path so we can import from db
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.mongo import get_db_client

load_dotenv()

def seed_database():
    client = get_db_client()
    if not client:
        print("❌ Could not connect to database for seeding.")
        return

    db = client['morsegrid_outfitters']
    print("Starting clean database seeding...")

    # 1. Clear out any old existing test data
    db.products.drop()
    db.customers.drop()
    db.behavior_events.drop()
    db.orders.drop()
    db.messages_sent.drop()

    # 2. Mock Product Catalog (~50 products, with price/cost/margin fields)
    products = [
        # Scenario 1 & 2 Products (Helmets)
        {"product_id": "P001", "title": "Rallye Adventure Helmet", "description": "Dual-sport adventure helmet with drop-down sun visor and ultra-wide field of view. Premium aerodynamics for dual-sport tracks.", "category": "Helmets", "price": 350.00, "cost": 150.00, "margin": 200.00, "in_stock": True},
        {"product_id": "P002", "title": "Apex Carbon Full-Face Helmet", "description": "Ultra-lightweight aerospace carbon fiber weave shell. Maximum track ventilation.", "category": "Helmets", "price": 599.00, "cost": 250.00, "margin": 349.00, "in_stock": True},
        # Scenario 3 Product (Cafe Racer Jacket - Newly Stocked!)
        {"product_id": "P003", "title": "Classic Leather Cafe Racer Jacket", "description": "Premium top-grain cowhide leather jacket with CE armor inserts and vintage distressed finishing. Sleek aesthetic.", "category": "Jackets", "price": 450.00, "cost": 180.00, "margin": 270.00, "in_stock": True},
    ]
    
    # Fill up to 50 items with quick variations for catalog density
    for i in range(4, 51):
        category = "Gloves" if i % 3 == 0 else ("Boots" if i % 3 == 1 else "Apparel")
        price = 80.00 + (i * 5)
        cost = price * 0.4
        products.append({
            "product_id": f"P{str(i).zfill(3)}",
            "title": f"Enduro Shield Pro {category} V{i}",
            "description": f"High-performance rugged protective {category.lower()} built for extreme weather conditions and long-distance touring safety.",
            "category": category,
            "price": price,
            "cost": cost,
            "margin": price - cost,
            "in_stock": True if i % 5 != 0 else False
        })
    
    db.products.insert_many(products)
    print(f"✅ Loaded {len(products)} products into 'products' collection.")

    # 3. Mock Customers (~18 customers including our key scenario personas)
    now = datetime.utcnow()
    customers = [
        # Scenario 1 Persona: Mike (Active chat user, inquired about a helmet)
        {
            "customer_id": "C001", "name": "Mike Henderson", "email": "mike.h.testapp@gmail.com", "phone": "+15550192", "ig_handle": "@mike_rides", "segment": "engaged",
            "total_orders": 2, "total_spend": 420.00, "created_at": now - timedelta(days=90), "last_active_at": now - timedelta(days=2),
            "engagement": {"open_rate": 0.85, "click_rate": 0.40, "sms_optin": True, "last5_opens": [True, True, False, True, True]},
            "behavior_summary": "Inquired explicitly about Rallye Adventure Helmet via chat widget when it was flagged out of stock. Prefers premium headgear."
        },
        # Scenario 2 Persona: Sarah (Cold email channel, needs SMS switch)
        {
            "customer_id": "C002", "name": "Sarah Jenkins", "email": "sarah.j.testapp@gmail.com", "phone": "+15558831", "ig_handle": "@sarah_moto", "segment": "dormant_email",
            "total_orders": 1, "total_spend": 150.00, "created_at": now - timedelta(days=120), "last_active_at": now - timedelta(days=14),
            "engagement": {"open_rate": 0.05, "click_rate": 0.00, "sms_optin": True, "last5_opens": [False, False, False, False, False]}, # 0 of last 5 opened!
            "behavior_summary": "Browsed high-end carbon helmets heavily 2 weeks ago but has completely ignored the last 5 broadcast marketing emails."
        },
        # Scenario 3 Persona: Diego (Latent want buyer)
        {
            "customer_id": "C003", "name": "Diego Alvarez", "email": "diego.a.testapp@gmail.com", "phone": "+15559923", "ig_handle": "@diego_customs", "segment": "engaged",
            "total_orders": 3, "total_spend": 680.00, "created_at": now - timedelta(days=60), "last_active_at": now - timedelta(days=4),
            "engagement": {"open_rate": 0.70, "click_rate": 0.35, "sms_optin": False, "last5_opens": [True, False, True, True, False]},
            "behavior_summary": "Searched database context manually for 'cafe racer jacket' 6 weeks ago. No matches were present in inventory at that time."
        }
    ]

    # Generate remaining generic profiles up to 18
    for i in range(4, 19):
        customers.append({
            "customer_id": f"C{str(i).zfill(3)}",
            "name": f"Test Customer {i}",
            "email": f"testuser{i}@example.com",
            "phone": f"+1555900{i}",
            "ig_handle": f"@moto_user_{i}",
            "segment": "standard",
            "total_orders": i % 3,
            "total_spend": (i % 3) * 120.00,
            "created_at": now - timedelta(days=45),
            "last_active_at": now - timedelta(days=5),
            "engagement": {"open_rate": 0.50, "click_rate": 0.15, "sms_optin": True if i % 2 == 0 else False, "last5_opens": [True, False, True, False, True]},
            "behavior_summary": "Standard customer profile browsing general safety gear protective equipment."
        })

    db.customers.insert_many(customers)
    print(f"✅ Loaded {len(customers)} customers into 'customers' collection.")

    # 4. Generate ~200 Historical Behavior Events
    events = []
    # Feed explicit historical contexts matching scenarios
    events.append({"customer_id": "C001", "type": "chat", "ts": now - timedelta(days=60), "query": "Is the Rallye Adventure Helmet coming back in stock soon?"})
    events.append({"customer_id": "C002", "type": "view", "ts": now - timedelta(days=14), "product_id": "P002"})
    events.append({"customer_id": "C003", "type": "search", "ts": now - timedelta(days=42), "query": "vintage cafe racer jacket leather"})

    # Bulk generic events to reach data threshold
    for i in range(1, 201):
        c_id = f"C{str((i % 18) + 1).zfill(3)}"
        p_id = f"P{str((i % 50) + 1).zfill(3)}"
        e_type = "view" if i % 2 == 0 else ("cart_add" if i % 5 == 0 else "email_open")
        events.append({
            "customer_id": c_id,
            "type": e_type,
            "ts": now - timedelta(days=i % 30, hours=i % 24),
            "product_id": p_id if e_type != "email_open" else None
        })

    db.behavior_events.insert_many(events)
    print(f"✅ Loaded {len(events)} events into 'behavior_events' collection.")
    print("🎉 Seeding complete! Database populated cleanly.")
    client.close()

if __name__ == "__main__":
    seed_database()